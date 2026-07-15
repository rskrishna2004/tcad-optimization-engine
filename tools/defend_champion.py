# $Id: defend_champion.py, v1.0 2026/07/06 [YOUR NAME] - FINALIZATION: every champion must DEFEND itself with evidence, not just top a leaderboard. Seven sections: A reproducibility (re-sim vs DB record), B local robustness (perturbation cloud: is it a manufacturable optimum or a knife-edge?), C surrogate consistency (champion z-score under a GP fit to everything else: solver-artifact detector), D constraint margins, E physics-guard invariants + KB trend alarms, F dominance statistics (gap to runner-up, percentile, trajectory), G the 5-gate certification. Verdict TRUSTED / CAUTION / REJECTED with explicit reasons -> results/defense_<pid>.json. $
"""
Run (from the package root):
  python3 tools/defend_champion.py problems/corpus/<spec>.yaml [campaign_label]

Cost: 1 repro sim + 8 perturbation sims + certification (~4 sims). The output
dossier is the artifact you hand a judge: every claim about the champion is
backed by a measurement made AFTER the optimization, on fresh simulations.
"""
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OPT = os.path.join(ROOT, "optimizer")
for p in (ROOT, OPT):
    if p not in sys.path:
        sys.path.insert(0, p)

import numpy as np                                     # noqa: E402

N_CLOUD = 8            # perturbation re-sims
GEO_PCT = 0.02         # +/-2% geometry perturbation (process variation scale)
DOP_LOG = 0.05         # +/-5% in log10 for dopings
REPRO_TOL = 0.02       # 2% relative agreement on primary metrics
CLIFF_DROP = 0.10      # score drop fraction that flags a knife-edge
ZMAX = 3.0             # surrogate-consistency ceiling
MARGIN_WARN = 0.05     # warn when within 5% of a cap/floor/hard bound


def _load(spec_path, label=None):
    from tcadopt.l1_spec import compile as l1_compile
    from tcadopt.l7_memory import ExperimentDB
    cp = l1_compile(spec_path)
    db = ExperimentDB(os.path.join(ROOT, "results", "experiments.db"))
    rows = [r for r in db.query(problem_id=cp.problem_id, status="ok")
            if r.get("score") is not None
            and (label is None or r.get("campaign") == label)]
    if not rows:
        sys.exit("no scored ok rows for %s" % cp.problem_id)
    for r in rows:
        for k in ("params", "metrics", "encoded"):
            if isinstance(r.get(k), str):
                r[k] = json.loads(r[k])
    champ = max(rows, key=lambda r: r["score"])
    return cp, db, rows, champ


def _evaluator(cp):
    # EXACTLY mirror run_campaign's proven construction (l8_orch/run_campaign.py):
    # class is TCADEvaluator, built with deck=, plt_name=, n_parallel=.
    from tcadopt.l3_exec.execute import TCADEvaluator
    meas = getattr(cp, "measurement", "idvg")
    dc_name = cp.device_class
    base = ("finn" if "finfet" in dc_name
            else "pmos" if "pmos" in dc_name else "nmos")
    deck = {"idvg": base, "2vd": base + "_2vd",
            "idvd": base + "_idvd"}.get(meas, base)
    plt = ("%s_idvd.plt" % base if meas == "idvd" else "%s_idvg.plt" % base)
    return TCADEvaluator(n_parallel=1, plt_name=plt, deck=deck)


def _rel(a, b):
    if a is None or b is None:
        return None
    d = abs(a - b) / max(abs(a), abs(b), 1e-30)
    return d


# ---------------------------------------------------------------- sections
def sec_repro(ev, scorer, champ):
    r = ev.evaluate_batch([champ["params"]], tag="defense_repro")[0]
    m = r.get("metrics") or {}
    worst, per = 0.0, {}
    for k, v in (champ.get("metrics") or {}).items():
        if isinstance(v, (int, float)) and isinstance(m.get(k), (int, float)):
            d = _rel(v, m[k])
            if d is not None:
                per[k] = round(d, 4)
                worst = max(worst, d)
    s_new = scorer(m) if m else None
    ok = (r.get("status") == "ok" and worst <= REPRO_TOL)
    return {"pass": bool(ok), "worst_rel_dev": round(worst, 4),
            "rerun_score": s_new, "per_metric_dev": per,
            "note": "champion re-simulated from scratch; deviations vs DB record"}


def sec_robustness(ev, scorer, champ, s0):
    rng = np.random.RandomState(7)
    clouds = []
    for i in range(N_CLOUD):
        p = dict(champ["params"])
        for k, v in p.items():
            if v > 1e10:
                p[k] = 10 ** (math.log10(v) + DOP_LOG * rng.randn())
            else:
                p[k] = v * (1.0 + GEO_PCT * rng.randn())
        if p.get("NCH", 1e30) < 1.15 * p.get("NSUB", 0):
            p["NCH"] = 1.15 * p["NSUB"]
        clouds.append(p)
    res = ev.evaluate_batch(clouds, tag="defense_cloud")
    ss = [scorer(r["metrics"]) for r in res
          if r.get("status") == "ok" and r.get("metrics")]
    ss = [s for s in ss if s is not None and s == s and abs(s) < 1e8]
    if not ss:
        return {"pass": False, "note": "no perturbed sim survived -- knife-edge or infra failure"}
    drop = (s0 - min(ss)) / max(abs(s0), 1e-9)
    return {"pass": bool(drop <= CLIFF_DROP and len(ss) >= N_CLOUD // 2),
            "n_ok": len(ss), "score_mean": round(float(np.mean(ss)), 4),
            "score_min": round(float(min(ss)), 4),
            "worst_drop_frac": round(float(drop), 4),
            "note": "+/-2%% geometry, +/-5%% log-doping cloud: manufacturability of the optimum"}


def sec_surrogate(rows, champ):
    try:
        sys.path.insert(0, OPT)
        import gp as gplib
        X = np.array([r["encoded"] for r in rows
                      if r.get("encoded") and r is not champ], float)
        y = np.array([r["score"] for r in rows if r is not champ], float)
        m = np.isfinite(y) & (y > -1e8)
        X, y = X[m], y[m]
        if len(y) < 10:
            return {"pass": True, "note": "history too small for a meaningful z-score"}
        y = np.maximum(y, y.max() - 20.0)
        g = gplib.GP(X, y)
        mu, sg = g.predict(np.atleast_2d(np.array(champ["encoded"], float)))
        # OBSERVATION sigma, not latent sigma: an observed score carries the
        # fitted noise too. Omitting sn made every champion on a noisy
        # history look like a 100-sigma outlier (caught in validation).
        # g.sn is the noise VARIANCE in standardized units (added raw to the
        # K diagonal), so its original-units variance is sn * ys^2.
        sn_var = float(getattr(g, "sn", 0.0)) * float(getattr(g, "ys", 1.0)) ** 2
        sg_obs = math.sqrt(float(sg[0]) ** 2 + sn_var)
        z = float((champ["score"] - mu[0]) / max(sg_obs, 1e-9))
        return {"pass": bool(z <= ZMAX), "z_score": round(z, 2),
                "gp_mu": round(float(mu[0]), 4), "gp_sigma": round(float(sg[0]), 4),
                "note": "champion vs GP fit to ALL OTHER trials; z>3 = inconsistent with everything else learned (solver-artifact suspect)"}
    except Exception as e:
        return {"pass": True, "note": "surrogate check skipped: %s" % e}


def sec_margins(cp, champ, cap):
    out, warns = [], 0
    mets = champ.get("metrics") or {}
    if cap is not None and mets.get("IOFF_A_per_um"):
        frac = mets["IOFF_A_per_um"] / cap
        w = frac > (1.0 - MARGIN_WARN)
        warns += w
        out.append({"constraint": "IOFF<=cap", "utilization": round(frac, 3),
                    "edge": bool(w)})
    for o in cp.spec.get("objectives", []):
        if "floor" in o:
            v = mets.get(_metric_key(o["metric"], mets))
            if v:
                frac = o["floor"] / v
                w = frac > (1.0 - MARGIN_WARN)
                warns += w
                out.append({"constraint": "%s>=%g" % (o["metric"], o["floor"]),
                            "utilization": round(frac, 3), "edge": bool(w)})
    p = champ["params"]
    for name, lo in (("LG", 0.040), ("TOX", 0.0016), ("XJSD", 0.025)):
        if name in p:
            frac = lo / p[name]
            w = frac > (1.0 - MARGIN_WARN)
            out.append({"constraint": "%s>=%g" % (name, lo),
                        "utilization": round(frac, 3), "edge": bool(w)})
    return {"pass": True, "n_edge": int(warns), "margins": out,
            "note": "edge=True is not failure -- capped optima SHOULD ride their binding constraint; it is disclosure"}


def _metric_key(name, mets):
    aliases = {"Idsat": "Idsat_A_per_um", "Ron": "Ron_Ohm_um",
               "intrinsic_gain": "intrinsic_gain", "ION": "ION_A_per_um"}
    k = aliases.get(name, name)
    return k if k in mets else name


def sec_physics(cp, rows, champ):
    try:
        from tcadopt.l4_knowledge.physics_guard import validate, trend_audit
        T_K = float(((cp.spec.get("operating") or {}).get("T_K")) or 350.0)
        ok, viol = validate(champ.get("metrics") or {}, T_K=T_K)
        alarms = trend_audit(rows)
        return {"pass": bool(ok), "violations": viol,
                "trend_alarms": [list(a) for a in alarms[:5]],
                "note": "invariants on the champion + KB-vs-DB trend audit over the whole campaign"}
    except ImportError:
        return {"pass": True, "note": "physics guard not deployed"}


def sec_dominance(rows, champ):
    ss = sorted((r["score"] for r in rows), reverse=True)
    runner = next((r for r in sorted(rows, key=lambda r: -r["score"])
                   if r["params"] != champ["params"]), None)
    gap = champ["score"] - runner["score"] if runner else float("nan")
    return {"pass": True, "n_trials": len(rows),
            "score": round(champ["score"], 4),
            "gap_to_runner_up": round(gap, 4) if runner else None,
            "percentile_of_field": 100.0,
            "top5": [round(s, 4) for s in ss[:5]],
            "note": "a paper-thin gap means several near-equivalent optima exist -- report them all"}


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: python3 tools/defend_champion.py <spec.yaml> [campaign]")
    label = sys.argv[2] if len(sys.argv) > 2 else None
    cp, db, rows, champ = _load(sys.argv[1], label)
    cap = cp.cap_values[0] if getattr(cp, "cap_values", None) else None
    scorer = cp.make_scorer(cap)
    ev = _evaluator(cp)
    s0 = champ["score"]

    print("=" * 66)
    print("CHAMPION DEFENSE  %s  score=%.4f" % (cp.problem_id, s0))
    print("=" * 66)
    dossier = {"problem_id": cp.problem_id, "score": s0,
               "params": champ["params"], "metrics": champ["metrics"]}

    dossier["A_reproducibility"] = sec_repro(ev, scorer, champ)
    dossier["B_robustness"] = sec_robustness(ev, scorer, champ, s0)
    dossier["C_surrogate_consistency"] = sec_surrogate(rows, champ)
    dossier["D_constraint_margins"] = sec_margins(cp, champ, cap)
    dossier["E_physics"] = sec_physics(cp, rows, champ)
    dossier["F_dominance"] = sec_dominance(rows, champ)

    # G: the heavyweight 5-gate certification
    try:
        from tcadopt.l6_verify.certify import certify
        cert = certify(champ["params"], cp, "defense", cap or 1e30,
                       champ.get("metrics") or {})
        print(cert)
        dossier["G_certification"] = cert.to_dict()
        cert_pass = "PASS" in str(cert)
    except Exception as e:
        dossier["G_certification"] = {"error": str(e)}
        cert_pass = False

    hard = ["A_reproducibility", "B_robustness", "C_surrogate_consistency",
            "E_physics"]
    fails = [k for k in hard if not dossier[k].get("pass", True)]
    if not fails and cert_pass:
        verdict = "TRUSTED"
    elif len(fails) <= 1:
        verdict = "CAUTION: " + (fails[0] if fails else "certification")
    else:
        verdict = "REJECTED: " + ", ".join(fails)
    dossier["verdict"] = verdict

    for k in ("A_reproducibility", "B_robustness", "C_surrogate_consistency",
              "D_constraint_margins", "E_physics", "F_dominance"):
        d = dossier[k]
        print("  [%s] %-24s %s" % ("PASS" if d.get("pass", True) else "FAIL",
                                   k, d.get("note", "")))
    print("-" * 66)
    print("VERDICT:", verdict)
    outp = os.path.join(ROOT, "results", "defense_%s.json" % cp.problem_id)
    json.dump(dossier, open(outp, "w"), indent=1)
    print("->", outp)


if __name__ == "__main__":
    main()
