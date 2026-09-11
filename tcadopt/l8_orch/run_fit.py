"""l8_orch.run_fit -- staged BSIM-CMG parameter extraction.

WHY EXTRACTION IS STAGED, NOT ONE BIG SEARCH
--------------------------------------------
BSIM-CMG has hundreds of parameters. Handing all of them to the optimizer at
once is not "letting it work harder"; it is asking a physically meaningless
question, because most of those parameters are degenerate with each other.
A threshold shift can be produced by the gate work function, by body doping, or
by a short-channel coefficient. A drive-current error can be absorbed by
mobility or by series resistance. Fit them together and the optimizer will find
SOME combination that matches the curve -- and that combination will be wrong
in every way that matters: it will not extrapolate to a geometry or a
temperature it was not fitted at, and its parameters will not mean what their
names say.

The industry answer, and the one used here, is to extract in stages, each stage
using the bias region where its parameters dominate and everything already
extracted held FROZEN:

  Stage 1  electrostatics    PHIG, CIT, ... on the sub-threshold region at low
                             Vd, where mobility and series resistance barely
                             matter
  Stage 2  short-channel     DVT0, DVT1, ETA0, DSUB, ... on the Vd dependence
                             of threshold (DIBL), with Stage-1 values frozen
  Stage 3  mobility + Rds    U0, UA, UD, RDSWMIN, ... on the on-state, where
                             they dominate and the electrostatics are settled
  Stage 4  capacitance       CGSP, CGDP, CGBO, ... on the C-V curves, which the
                             DC fit never constrained
  Stage 5  global polish     a small trust region around everything at once,
                             to remove residual interaction, starting from a
                             point that is already physically meaningful

Each stage is a normal TCADOpt campaign. Same ParamSpace, same GP, same trust
region, same experiment DB. What changes per stage is which parameters are free,
which target sweeps are scored, and what the previous stage froze.

Freezing is what makes the result an EXTRACTION rather than a curve fit. It is
also what makes it defensible in a viva: for every parameter you can say which
measurement determined it and which ones were held fixed while it was found.

USE
    python -m tcadopt.l8_orch.run_fit problems/nsfet_gaa_fit.yaml
    python -m tcadopt.l8_orch.run_fit problems/nsfet_gaa_fit.yaml --stage 2
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import yaml                                                    # noqa: E402

from tcadopt.l1_spec.paramspace import ParamSpace              # noqa: E402
from tcadopt.l1_spec.curve_scorer import build_curve_scorer    # noqa: E402
from tcadopt.l3_exec.targets import load_targets, summarize    # noqa: E402
from tcadopt.l3_exec.spice_exec import HSpiceEvaluator         # noqa: E402
from tcadopt.l5_opt.optimizer import Optimizer                 # noqa: E402
from tcadopt.l7_memory import ExperimentDB, code_version       # noqa: E402


def _default_db():
    return os.path.join(ROOT, "results", "extraction.db")


def _frozen_path(spec_path):
    return os.path.join(ROOT, "results",
                        "frozen_%s.json" % os.path.splitext(
                            os.path.basename(spec_path))[0])


def load_frozen(spec_path):
    p = _frozen_path(spec_path)
    if os.path.exists(p):
        with open(p) as fh:
            return json.load(fh)
    return {}


def save_frozen(spec_path, frozen):
    p = _frozen_path(spec_path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        json.dump(frozen, fh, indent=1, sort_keys=True)
    return p


def _stage_targets(all_targets, stage):
    """Select the sweeps this stage is scored on, and their weights."""
    names = stage.get("sweeps")
    ts = [dict(t) for t in all_targets
          if (names is None or t["name"] in names)]
    wmap = stage.get("sweep_weights") or {}
    for t in ts:
        t["weight"] = float(wmap.get(t["name"], t.get("weight", 1.0)))
    return ts


def run_stage(spec_path, stage_index=None, db_path=None, verbose=True,
              evaluator_factory=None, seed=0):
    """Run one stage (or every remaining stage when stage_index is None).

    `evaluator_factory(targets, scorer, spec, stage) -> evaluator` lets a caller
    substitute the simulator. This mirrors how `run_campaign` accepts an
    injected evaluator, and it is what makes the whole staged loop testable
    without a SPICE licence: the ParamSpace, the GP, the trust region, the
    scorer, the database and the freezing logic are all exercised for real
    against a stand-in simulator.
    """
    with open(spec_path) as fh:
        spec = yaml.safe_load(fh)
    fit = spec["fit"]
    stages = spec["stages"]
    all_targets, dropped = load_targets(fit, root=ROOT)
    if verbose:
        print("=" * 70)
        print("EXTRACTION  %s" % spec["problem_id"])
        print(summarize(all_targets, dropped))

    db = ExperimentDB(db_path or _default_db())
    cv = code_version(ROOT)
    frozen = load_frozen(spec_path)
    todo = ([stages[stage_index - 1]] if stage_index
            else stages)

    for st in todo:
        label = st["name"]
        params = st["parameters"]
        space = ParamSpace(params, coupled=st.get("coupled", []))
        targets = _stage_targets(all_targets, st)
        scorer = build_curve_scorer(targets, st.get("objective", fit))

        if verbose:
            print("-" * 70)
            print("STAGE %s  free=%d  frozen=%d  sweeps=%d" % (
                label, space.dim, len(frozen), len(targets)))
            print("  free      : %s" % ", ".join(space.names))
            if frozen:
                print("  frozen    : %s" % ", ".join(
                    "%s=%.4g" % (k, v) for k, v in sorted(frozen.items())))
            print("  scored on : %s" % ", ".join(t["name"] for t in targets))

        ev = (evaluator_factory(targets, scorer, spec, st)
              if evaluator_factory else HSpiceEvaluator(
            targets,
            models=fit.get("models", {}),
            structures=fit.get("structures"),
            n_parallel=int(spec.get("budget", {}).get("parallel", 8)),
            temp=float(spec.get("operating", {}).get("T_K", 300.0)) - 273.15
            if spec.get("operating", {}).get("T_K", 300.0) > 200 else 27.0,
            nf=int(fit.get("nf", 1)),
            scorer=scorer))

        opt = Optimizer(space)
        budget = st.get("budget", spec.get("budget", {}))
        parallel = int(budget.get("parallel", 8))
        max_evals = int(budget.get("max_evals", 120))
        init_n = int(budget.get("init_n", max(parallel, 2 * space.dim + 4)))
        round_n = int(budget.get("round_n", parallel))
        max_rounds = max(1, (max_evals - init_n) // max(round_n, 1))

        def evaluate(U, tag):
            plists = []
            for u in U:
                p = dict(frozen)          # everything already extracted
                p.update(space.decode(u))  # this stage's free parameters
                plists.append(p)
            results = ev.evaluate_batch(plists, tag=tag)
            for u, p, r in zip(U, plists, results):
                s = (scorer(r.get("curves")) if r.get("curves") else None)
                if s is not None and not (s == s and abs(s) < 1e30):
                    s = None
                if s is not None and s <= -1e8:
                    s = None               # non-simulating: keep out of the GP
                db.record(spec["problem_id"], params=p, encoded=list(u),
                          metrics=r.get("metrics"), status=r.get("status"),
                          score=s, campaign=label, trial_id=r.get("run_id"),
                          failure_class=r.get("failure_class"), seed=seed,
                          code_ver=cv, wall_time=r.get("wall_s"))
            return results

        U = opt.propose([], [], init_n, mode="lhs_init", seed=seed)
        evaluate(U, "%s_init" % label)
        best = _best(db, spec["problem_id"], label)
        hist = [best["score"]] if best else []
        if verbose and best:
            print("  init best error = %.5f" % (-best["score"]))

        for rd in range(max_rounds):
            X, y = db.history_encoded(spec["problem_id"], campaign=label)
            if len(y) < 3:
                break
            U = opt.propose(X, y, round_n, mode="bo_round", seed=seed + rd + 1)
            evaluate(U, "%s_r%d" % (label, rd))
            best = _best(db, spec["problem_id"], label)
            if not best:
                continue
            hist.append(best["score"])
            if verbose:
                print("  round %-2d best error = %.5f" % (rd, -best["score"]))
            if Optimizer.floor_detected(hist, patience=2, eps=1e-4):
                if opt.exhausted(max_restarts=int(budget.get("max_restarts", 2))):
                    if verbose:
                        print("  floor + trust region exhausted -> stage done")
                    break
                opt.force_restart()

        champ = _best(db, spec["problem_id"], label)
        if champ is None:
            print("  STAGE %s produced no usable fit -- stopping." % label)
            print("  Nothing is frozen from a stage that did not converge.")
            return frozen, db
        # freeze ONLY this stage's own free parameters
        for k in space.names:
            frozen[k] = champ["params"][k]
        for k, v in space.fixed.items():
            frozen.setdefault(k, v)
        p = save_frozen(spec_path, frozen)
        if verbose:
            print("  STAGE %s COMPLETE  error = %.5f" % (label, -champ["score"]))
            _report(champ, space.names)
            print("  frozen -> %s" % p)

    return frozen, db


def _best(db, problem_id, label):
    rows = [r for r in db.query(problem_id=problem_id, campaign=label)
            if r.get("score") is not None]
    return max(rows, key=lambda r: r["score"]) if rows else None


def _report(champ, names):
    print("  extracted:")
    for k in names:
        print("     %-12s = %.6g" % (k, champ["params"][k]))
    m = champ.get("metrics") or {}
    if m.get("fit_worst_sub_decades") is not None:
        print("  worst sub-threshold error : %.4f decades (%.1f%% in current)"
              % (m["fit_worst_sub_decades"],
                 100.0 * (10.0 ** m["fit_worst_sub_decades"] - 1.0)))
    if m.get("fit_worst_on_pct") is not None:
        print("  worst on-state error      : %.2f %%" % m["fit_worst_on_pct"])


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m tcadopt.l8_orch.run_fit <fit_spec.yaml> "
              "[--stage N]")
        sys.exit(1)
    idx = None
    if "--stage" in sys.argv:
        idx = int(sys.argv[sys.argv.index("--stage") + 1])
    run_stage(sys.argv[1], stage_index=idx)
