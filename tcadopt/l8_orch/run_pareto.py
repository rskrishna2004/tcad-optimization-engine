"""l8_orch.run_pareto -- multi-objective (Pareto) campaign via ParEGO.

The generalization proof. Same engine as run_campaign (ParamSpace + GP facade +
executor + experiment DB), but instead of maximizing ION at fixed IOFF caps, it
traces the full ION-vs-IOFF Pareto front. ParEGO: each round draw a random weight
on the objective simplex, scalarize the whole archive with an augmented-Tchebycheff
function, fit the GP to that scalarization, and propose -- so the union of rounds
sweeps the front. The archive's non-dominated set IS the front.

Self-validation: warm-started with hp/std/lp, the certified champions must land ON
the produced front (or be dominated by it).

Usage: python -m tcadopt.l8_orch.run_pareto problems/nmos_planar_pareto.yaml
$Id: run_pareto.py, 2026/06/18 [YOUR NAME] $
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tcadopt.l1_spec import compile                       # noqa: E402
from tcadopt.l1_spec.scorer import ParetoScorer, mval     # noqa: E402
from tcadopt.l5_opt.optimizer import Optimizer            # noqa: E402
from tcadopt.l7_memory import ExperimentDB, code_version  # noqa: E402


def pareto_front(points):
    """Non-dominated set for (maximize ION, minimize IOFF).
    points: list of dicts with 'ION' and 'IOFF'. Returns front sorted by IOFF."""
    front = []
    for p in points:
        dom = False
        for q in points:
            if q is p:
                continue
            if (q["ION"] >= p["ION"] and q["IOFF"] <= p["IOFF"]
                    and (q["ION"] > p["ION"] or q["IOFF"] < p["IOFF"])):
                dom = True
                break
        if not dom:
            front.append(p)
    front.sort(key=lambda r: r["IOFF"])
    return front


def _archive(db, problem_id, campaign):
    """All successful trials with metrics + encoded vectors."""
    rows = [r for r in db.query(problem_id=problem_id, status="ok",
                                campaign=campaign)
            if r.get("metrics") and r.get("encoded")]
    pts = []
    for r in rows:
        ion = mval(r["metrics"], "ION")
        ioff = mval(r["metrics"], "IOFF")
        if ion and ioff:
            pts.append({"ION": ion, "IOFF": ioff, "encoded": r["encoded"],
                        "metrics": r["metrics"], "params": r.get("params"),
                        "trial_id": r.get("trial_id")})
    return pts


def _eval_record(U, cp, evaluator, db, campaign, code_ver, tag, seed):
    params_list = [cp.space.decode(u) for u in U]
    results = evaluator.evaluate_batch(params_list, tag=tag)
    for u, params, r in zip(U, params_list, results):
        m = r.get("metrics")
        db.record(cp.problem_id, params=params, encoded=list(u), metrics=m,
                  status=r.get("status", "fail"), score=None, campaign=campaign,
                  trial_id=r.get("run_id"), failure_class=r.get("failure_class"),
                  models=cp.models, seed=seed, code_ver=code_ver,
                  wall_time=r.get("wall_s"))


def run_pareto(spec_path, evaluator=None, db_path=None, init_n=60, round_n=20,
               max_rounds=20, seed=0, seeds=None, verbose=True):
    cp = compile(spec_path)
    if not cp.is_pareto:
        raise ValueError("run_pareto needs a pareto-mode spec (objectives.mode: pareto)")
    scorer = cp.make_scorer()
    assert isinstance(scorer, ParetoScorer)
    k = len(scorer.objectives)

    db = ExperimentDB(db_path or os.path.join(ROOT, "results", "pareto.db"))
    opt = Optimizer(cp.space)
    cv = code_version(ROOT)
    campaign = "pareto"
    if evaluator is None:
        from tcadopt.l3_exec.execute import TCADEvaluator
        dc = cp.device_class
        base = ("nw" if ("nanowire" in dc or "gaa" in dc)
                else "finn" if "finfet" in dc
                else "pmos" if "pmos" in dc else "nmos")
        meas = getattr(cp, "measurement", "idvg")
        deck = {"idvg": base, "2vd": base + "_2vd", "idvd": base + "_idvd"}.get(meas, base)
        plt = "%s_idvg.plt" % base
        evaluator = TCADEvaluator(n_parallel=cp.budget.get("parallel", 64),
                                       plt_name=plt, deck=deck)

    # warm-start seeds (champions should sit on the front)
    seed_U = []
    if seeds:
        from tcadopt.l7_memory.seeds import valid_seeds
        seed_U = [cp.space.encode(s) for s in valid_seeds(cp.space, seeds, verbose)]

    if verbose:
        print("=" * 66)
        print("PARETO CAMPAIGN %s  objectives=%s  (ParEGO, %d-D)" % (
            cp.problem_id, [o[0] + ":" + o[1] for o in scorer.objectives], k))
        print("  init_n=%d round_n=%d max_rounds=%d seeds=%d" % (
            init_n, round_n, max_rounds, len(seed_U)))

    # ---- initial design ----
    U = list(seed_U) + opt.propose([], [], init_n, mode="lhs_init", seed=seed)
    _eval_record(U, cp, evaluator, db, campaign, cv, tag="par_init", seed=seed)

    # ---- ParEGO rounds ----
    import numpy as np
    for rd in range(max_rounds):
        pts = _archive(db, cp.problem_id, campaign)
        vecs = [scorer.vector(p["metrics"]) for p in pts]
        vecs = [(p, v) for p, v in zip(pts, vecs) if v is not None]
        if len(vecs) < 3:
            break
        # observed per-objective range (for ParEGO normalization)
        ref_lo = [min(v[i] for _, v in vecs) for i in range(k)]
        ref_hi = [max(v[i] for _, v in vecs) for i in range(k)]
        w = ParetoScorer.random_weight(k, seed=seed + rd + 1)
        X = [p["encoded"] for p, _ in vecs]
        y = [scorer.parego(p["metrics"], w, ref_lo, ref_hi) for p, _ in vecs]
        U = opt.propose(X, y, round_n, mode="bo_round", seed=seed + rd + 1)
        _eval_record(U, cp, evaluator, db, campaign, cv,
                     tag="par_r%d" % rd, seed=seed + rd + 1)
        if verbose:
            fr = pareto_front(_archive(db, cp.problem_id, campaign))
            print("  round %2d  weight=[%.2f,%.2f]  archive=%d  front=%d points "
                  "(IOFF %.2e..%.2e)" % (
                      rd, w[0], w[1], len(pts) + len(U), len(fr),
                      fr[0]["IOFF"], fr[-1]["IOFF"]))

    # ---- final front ----
    front = pareto_front(_archive(db, cp.problem_id, campaign))
    try:
        import json
        outp = os.path.join(ROOT, "results", "pareto_front.json")
        json.dump([{"ION": p["ION"], "IOFF": p["IOFF"], "params": p["params"]}
                   for p in front], open(outp, "w"), indent=1)
    except Exception:
        outp = None
    if verbose:
        print("-" * 66)
        print("PARETO FRONT (%d points)%s:" % (
            len(front), " -> " + outp if outp else ""))
        for p in front:
            print("    ION=%.3e  IOFF=%.3e  (ratio=%.2e)" % (
                p["ION"], p["IOFF"], p["ION"] / p["IOFF"]))
    return front, db


def champions_on_front(front, champions, tol=0.02):
    """Each champion must be matched-or-dominated by a front point:
    exists f with ION_f >= (1-tol)*ION_c AND IOFF_f <= (1+tol)*IOFF_c."""
    out = {}
    for lab, c in champions.items():
        ok = any(f["ION"] >= (1 - tol) * c["ION"] and
                 f["IOFF"] <= (1 + tol) * c["IOFF"] for f in front)
        out[lab] = ok
    return out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m tcadopt.l8_orch.run_pareto <pareto_spec.yaml>")
        sys.exit(1)
    run_pareto(sys.argv[1])
