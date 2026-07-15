"""l8_orch.run_campaign -- the autonomous optimization loop (L2 campaign).

ingest spec -> per cap: LHS init -> evaluate -> record -> {GP propose -> evaluate ->
record} until budget or floor-detection -> select champion. Verification (L6) is a
follow-on step. The the TCAD simulator evaluator is injected so the same loop is unit-tested
with a synthetic evaluator (no the TCAD simulator) -- this is how we validate orchestration
logic here and run it for real on the workstation.

Usage (real): python -m tcadopt.l8_orch.run_campaign problems/nmos_planar_caps.yaml
$Id: run_campaign.py, 2026/06/18 [YOUR NAME] $
"""
import os
import sys
import math

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tcadopt.l1_spec import compile                      # noqa: E402
from tcadopt.l5_opt.optimizer import Optimizer           # noqa: E402
from tcadopt.l7_memory import ExperimentDB, code_version  # noqa: E402
# v3 (D-DAY): physics-guided init seeds wired; parallel default 64;
# restart budget 4; every seam exception-guarded; convergence report.

# friendly campaign labels for the canonical IOFF caps
_CAP_LABEL = {1e-7: "hp", 1e-8: "std", 1e-9: "lp"}


def _label(cap):
    if cap is None:
        return "single"
    return _CAP_LABEL.get(cap, "cap_%.0e" % cap)


def _default_db_path():
    return os.path.join(ROOT, "results", "experiments.db")


# headline metrics to print per measurement (label, metrics-key, fmt)
_CHAMP_DISPLAY = {
    "idvg": [("ION", "ION_A_per_um", "%.3e"), ("IOFF", "IOFF_A_per_um", "%.3e"),
             ("gm", "gm_peak_S_per_um", "%.3e")],
    "2vd":  [("ION", "ION_A_per_um", "%.3e"), ("IOFF", "IOFF_A_per_um", "%.3e"),
             ("DIBL", "DIBL_mV_per_V", "%.1f")],
    "idvd": [("gain", "intrinsic_gain", "%.2f"), ("Idsat", "Idsat_A_per_um", "%.3e"),
             ("gds", "gds_S_per_um", "%.3e"), ("Ron", "Ron_Ohm_um", "%.0f")],
}


def _fmt_champ(measurement, m):
    disp = _CHAMP_DISPLAY.get(measurement, _CHAMP_DISPLAY["idvg"])
    parts = [(("%s=" + fmt) % (lab, m[key])) for (lab, key, fmt) in disp
             if m.get(key) is not None]
    return " ".join(parts) if parts else "(metrics: %s)" % ",".join(sorted(m))


def _physics_seed_U(cp, n=8, verbose=True):
    """PHYSICS-GUIDED initial points (chain entry, with knowledge). Pushes KB
    levers for the objective's max/min metrics from the space midpoint. Fully
    guarded: any KB/param/shape mismatch -> [] and init falls back to LHS,
    never crashing the campaign."""
    try:
        from tcadopt.l4_knowledge.physics_guard import physics_seeds
        base = cp.space.decode([0.5] * cp.space.dim)
        objs = [(o["metric"], o["sense"])
                for o in cp.spec.get("objectives", [])
                if isinstance(o, dict) and o.get("sense") in ("max", "min")]
        if not objs:
            return []
        seeds = physics_seeds(objs, base, cp.space, n=n)
        U = []
        for p in seeds:
            try:
                U.append(cp.space.encode(p))
            except Exception:
                continue
        if verbose and U:
            print("    [physics-seed] %d knowledge-guided init points "
                  "(objective %s)" % (len(U),
                  ", ".join("%s^%s" % (m, s) for m, s in objs)))
        return U
    except Exception as e:
        if verbose:
            print("    [physics-seed] skipped (%s) -> LHS-only init"
                  % type(e).__name__)
        return []


def _convergence_report(db, cp, label, champ, opt):
    """Evidence the champion deserves trust as a (near-)global optimum: the
    dominance gap, the top-field spread, and how many independent trust-region
    restarts were spent. The day-of operator reads this to judge global-ness."""
    try:
        rows = [r for r in db.query(problem_id=cp.problem_id, campaign=label)
                if r.get("score") is not None]
        ss = sorted((r["score"] for r in rows), reverse=True)
        if not ss:
            return
        runner = next((s for s in ss[1:] if s < ss[0] - 1e-9), None)
        gap = (ss[0] - runner) if runner is not None else 0.0
        restarts = getattr(getattr(opt, "tr", None), "restarts", 0)
        print("    ---- convergence evidence ----")
        print("    trials scored    : %d" % len(rows))
        print("    gap to runner-up : %.4f  (%s)" % (
            gap, "sharp, well-separated optimum" if gap > 0.05
            else "flat top: many near-equal optima (any is a valid win)"))
        print("    top-5 scores     : %s" % ", ".join("%.4f" % s for s in ss[:5]))
        print("    basin restarts   : %d independent trust-region attacks"
              % restarts)
        print("    -> run 3-5 seeds; agreement across seeds = strongest "
              "practical global evidence (dossier F_dominance quantifies it).")
    except Exception:
        pass


def run_campaign(spec_path, evaluator=None, db_path=None, init_n=None,
                 round_n=None, max_rounds=None, seed=0, verbose=True,
                 floor_patience=2, floor_eps=1e-3, seeds=None,
                 parallel=None, max_evals=None, max_restarts=4):
    cp = compile(spec_path)
    if cp.is_pareto:
        raise NotImplementedError(
            "pareto loop is P4; run a capped-scalar spec for now "
            "(the pareto front driver reuses this loop with ParEGO weights).")

    db = ExperimentDB(db_path or _default_db_path())
    opt = Optimizer(cp.space)
    cv = code_version(ROOT)

    # warm-start seeds (transfer): keep only encodable ones, clamp for coherence
    seed_U = []
    if seeds:
        from tcadopt.l7_memory.seeds import valid_seeds
        good = valid_seeds(cp.space, seeds, verbose=verbose)
        seed_U = [cp.space.encode(s) for s in good]
        if verbose:
            print("warm-start: %d/%d seeds usable" % (len(seed_U), len(seeds)))

    if evaluator is None:
        from tcadopt.l3_exec.execute import TCADEvaluator
        dc = cp.device_class
        base = ("nw" if ("nanowire" in dc or "gaa" in dc)
                else "finn" if "finfet" in dc
                else "pmos" if "pmos" in dc else "nmos")
        meas = getattr(cp, "measurement", "idvg")
        # measurement -> (deck registered in runner.DECK_SETS, current plt name)
        _DECK_BY_MEAS = {
            "idvg": (base,             "%s_idvg.plt" % base),
            "2vd":  ("%s_2vd" % base,  "%s_idvg.plt" % base),
            "idvd": ("%s_idvd" % base, "%s_idvd.plt" % base),
        }
        deck, plt = _DECK_BY_MEAS.get(meas, (base, "%s_idvg.plt" % base))
        evaluator = TCADEvaluator(n_parallel=cp.budget.get("parallel", 8),
                                       metric_config=cp.metric_config,
                                       plt_name=plt, deck=deck)

    # budget knobs (spec defaults, overridable by args)
    # D-DAY throughput: saturate the workstation (50-80 parallel sims).
    parallel = parallel or cp.budget.get("parallel", 64)
    max_evals = max_evals or cp.budget.get("max_evals", 700)
    init_n = init_n or max(parallel, 48)
    round_n = round_n or parallel
    if max_rounds is None:
        max_rounds = max(1, (max_evals - init_n) // round_n)

    if verbose:
        print("=" * 66)
        print("CAMPAIGN %s  backend=%s  caps=%s" % (
            cp.problem_id, opt.backend_name, cp.cap_values))
        print("  init_n=%d round_n=%d max_rounds=%d parallel=%d" % (
            init_n, round_n, max_rounds, parallel))

    champions = {}
    for ci, cap in enumerate(cp.cap_values):
        label = _label(cap)
        scorer = cp.make_scorer(cap)
        seed_c = seed + 1000 * ci          # decorrelate campaigns
        if verbose:
            print("-" * 66)
            print("  cap=%s  campaign=%s  (seed=%d)" % (cap, label, seed_c))

        # ---- initial design: PHYSICS-GUIDED seeds + warm-start + LHS ----
        # The chain now STARTS with knowledge: physics_seeds pushes the KB
        # levers for the objective from the space midpoint, giving the GP a
        # few high-value anchors before any random point is drawn. Non-
        # harmful (the GP discards bad anchors) and fully guarded.
        phys_U = _physics_seed_U(cp, n=min(10, max(2, init_n // 5)),
                                 verbose=verbose)
        n_lhs = max(init_n - len(seed_U) - len(phys_U), parallel)
        U = (list(seed_U) + phys_U
             + opt.propose([], [], n_lhs, mode="lhs_init", seed=seed_c))
        _eval_record(U, cp, scorer, evaluator, db, label, cap, cv,
                     tag="%s_init" % label, seed=seed_c)
        best = _best(db, cp.problem_id, label)
        if verbose and best:
            print("    init best score=%.4f (%d evals%s)" % (
                best["score"], len(U),
                ", %d seeded" % len(seed_U) if seed_U else ""))

        # ---- BO rounds: trust-region + feasibility-aware, restart-then-stop ----
        best_hist = [best["score"]] if best else []
        for rd in range(max_rounds):
            # ROUND GUARD: a transient error (solver, GP, IO) skips the round
            # instead of killing the campaign -- the champion so far is always
            # safe in the DB. Zero-traceback guarantee for D-day.
            try:
                X, y = db.history_encoded(cp.problem_id, campaign=label)
                try:
                    cdata = _constraints_data(db, cp, label, cap)
                except Exception:
                    cdata = None
                U = opt.propose(X, y, round_n, mode="bo_round",
                                seed=seed_c + rd + 1, constraints_data=cdata)
                _eval_record(U, cp, scorer, evaluator, db, label, cap, cv,
                             tag="%s_r%d" % (label, rd), seed=seed_c + rd + 1)
            except Exception as e:
                print("    [round %d] recovered from %s: %s -- continuing"
                      % (rd, type(e).__name__, e))
                continue
            best = _best(db, cp.problem_id, label)
            best_hist.append(best["score"])
            if verbose:
                print("    round %d best=%.4f overall=%.4f" % (
                    rd, best_hist[-1], max(best_hist)))
            if opt.floor_detected(best_hist, patience=floor_patience,
                                  eps=floor_eps):
                # v2 policy: a floor is a trust-region event, not a death
                # sentence. The TR backend shrinks/restarts internally; only
                # stop once it reports every attacked direction exhausted.
                if opt.exhausted(max_restarts=max_restarts):
                    if verbose:
                        print("    floor + trust-region exhausted -> stop")
                    break
                opt.force_restart()          # the actual restart (audit fix)
                if verbose:
                    print("    floor-detected -> trust-region restart, continuing")

        champ = _best(db, cp.problem_id, label)
        champions[label] = champ
        if verbose and champ:
            _convergence_report(db, cp, label, champ, opt)
        if verbose and champ:
            m = champ.get("metrics") or {}
            print("    CHAMPION %s: %s score=%.4f" % (
                label, _fmt_champ(getattr(cp, "measurement", "idvg"), m),
                champ["score"]))

    if verbose:
        print("=" * 66)
        print("CAMPAIGN COMPLETE. champions:", {k: round(v["score"], 4)
              for k, v in champions.items() if v})
    return champions, db


def _eval_record(U, cp, scorer, evaluator, db, label, cap, code_ver, tag, seed):
    """Decode encoded points, evaluate as a batch, score, and record each trial.
    Every ok/partial trial passes the physics guard: metrics violating a KB
    invariant (Boltzmann SS limit, ION>IOFF, gain=gm/gds consistency, ...) are
    recorded with score=None + failure_class=physics_suspect, which EXCLUDES
    them from the surrogate -- the engine never learns from unphysical data."""
    try:
        from tcadopt.l4_knowledge.physics_guard import validate as _phys_validate
    except ImportError:
        _phys_validate = None
    T_K = float(((cp.spec.get("operating") or {}).get("T_K")) or 350.0)
    params_list = [cp.space.decode(u) for u in U]
    results = evaluator.evaluate_batch(params_list, tag=tag)
    n_suspect = 0
    for u, params, r in zip(U, params_list, results):
        metrics = r.get("metrics")
        status = r.get("status", "fail")
        score = scorer(metrics) if (metrics is not None and status in ("ok", "partial")) else None
        if score is not None and not (score == score and abs(score) < 1e30):
            score = None                      # NaN/inf scorer output: never poison the DB
        fclass = r.get("failure_class")
        if score is not None and _phys_validate is not None:
            try:
                ok_phys, viol = _phys_validate(metrics, T_K=T_K)
            except Exception:
                ok_phys, viol = True, []   # guard error never sinks a trial
            if not ok_phys:
                score = None
                fclass = "physics_suspect"
                n_suspect += 1
                print("      [physics_guard] %s excluded: %s" % (
                    r.get("run_id", "?"), "; ".join(viol[:2])))
        db.record(
            cp.problem_id, params=params, encoded=list(u), metrics=metrics,
            status=status, score=score, campaign=label,
            trial_id=r.get("run_id"), failure_class=fclass,
            models=cp.models, fidelity={"cap": cap}, seed=seed, code_ver=code_ver,
            wall_time=r.get("wall_s"))
    if n_suspect:
        print("      [physics_guard] %d/%d trials quarantined this batch"
              % (n_suspect, len(results)))


def _constraints_data(db, cp, label, cap):
    """For capped problems, hand the optimizer the constraint observations so
    it can model feasibility: (Xc, log10(IOFF), log10(cap), 'le'). Includes
    infeasible AND physics-suspect rows -- their IOFF is real information
    about WHERE the cap is violated even when their score is unusable."""
    if cap is None:
        return None
    import math as _m
    Xc, cv = [], []
    for row in db.query(problem_id=cp.problem_id, campaign=label):
        mets = row.get("metrics") or {}
        io = mets.get("IOFF_A_per_um")
        if row.get("encoded") is not None and io:
            Xc.append(row["encoded"])
            cv.append(_m.log10(max(io, 1e-30)))
    if len(cv) < 3:
        return None
    return [(Xc, cv, _m.log10(cap), "le")]


def _best(db, problem_id, label):
    rows = db.best(problem_id, n=1, by="score")
    # best() filters status='ok' AND score not null; restrict to this campaign
    rows = [r for r in db.query(problem_id=problem_id, status="ok", campaign=label)
            if r.get("score") is not None]
    if not rows:
        return None
    return max(rows, key=lambda r: r["score"])


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m tcadopt.l8_orch.run_campaign <spec.yaml>")
        sys.exit(1)
    run_campaign(sys.argv[1])
