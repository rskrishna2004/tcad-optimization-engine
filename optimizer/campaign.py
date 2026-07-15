# $Id: campaign.py, v2.0 2026/06/12 [YOUR NAME] - Phase 4: warm-start from v1 data, per-campaign IOFF cap, ratio guard, named campaigns $
# Usage:
#   python3 campaign.py warmstart <oldmaster.csv>   # seed v2 GP from prior evals
#   python3 campaign.py init                        # cold LHS (only if no warmstart)
#   python3 campaign.py auto N                       # N BO rounds
#   python3 campaign.py best [n]
# Campaign name + IOFF cap come from env so you can run 3 caps in 3 terminals:
#   CAMP=hp   IOFF_CAP=1e-7 python3 campaign.py warmstart ../results/master.csv
#   CAMP=std  IOFF_CAP=1e-8 python3 campaign.py warmstart ../results/master.csv
#   CAMP=lp   IOFF_CAP=1e-9 python3 campaign.py warmstart ../results/master.csv
import os
import sys
import csv
import json
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from space import decode, encode, lhs, DIM, NAMES        # noqa: E402
from gp import GP, propose_batch                          # noqa: E402
from dispatch import run_batch                            # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, ".."))
CAMP = os.environ.get("CAMP", "hp")
STATE = os.path.join(ROOT, "results", "campaign_%s.json" % CAMP)

IOFF_CAP = float(os.environ.get("IOFF_CAP", "1e-7"))
W_GM = 0.30
BETA = 3.0
RATIO_MIN = 10.0     # ION/IOFF below this = non-functional; hard reject
N_INIT = 60
N_BATCH = 30
PARALLEL = 30


def score(metrics):
    if not metrics or metrics.get("ION_A_per_um", 0) <= 0:
        return -20.0
    ion = metrics["ION_A_per_um"]
    ioff = max(metrics["IOFF_A_per_um"], 1e-30)
    if ion / ioff < RATIO_MIN:          # punch-through / no gate control
        return -15.0
    s = np.log10(ion) + W_GM * np.log10(max(metrics["gm_peak_S_per_um"], 1e-12))
    if ioff > IOFF_CAP:
        s -= BETA * np.log10(ioff / IOFF_CAP)
    return float(s)


def _load():
    if os.path.exists(STATE):
        d = json.load(open(STATE))
        return np.array(d["X"]), np.array(d["y"]), d["round"], d["results"]
    return np.zeros((0, DIM)), np.zeros(0), 0, []


def _save(X, y, rnd, results):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump({"X": X.tolist(), "y": y.tolist(), "round": rnd,
               "results": results, "cap": IOFF_CAP, "camp": CAMP},
              open(STATE, "w"))


def _evaluate(U, tag):
    psets = [decode(u) for u in U]
    res = run_batch(psets, n_parallel=PARALLEL, tag="%s_%s" % (CAMP, tag))
    ys, keep = [], []
    for r in res:
        s = score(r.get("metrics"))
        if r["status"] == "partial":
            s -= 0.5
        ys.append(s)
        keep.append({"run_id": r["run_id"], "score": s,
                     "status": r["status"], "metrics": r.get("metrics"),
                     "params": r["params"]})
    return np.array(ys), keep


def cmd_warmstart(oldcsv):
    """Re-score every prior eval under THIS campaign's cap, encode into v2
    cube, and seed the GP. 240 free data points per campaign."""
    X, y, rnd, results = _load()
    if len(y):
        print("[%s] state exists; skip warmstart" % CAMP)
        return
    rows = list(csv.DictReader(open(oldcsv)))
    U, ys, keep = [], [], []
    for r in rows:
        try:
            params = {k: float(r[k]) for k in NAMES}
            params.update({"LSD": 0.15, "HPOLY": 0.1, "HSUB": 0.8})
            m = {"ION_A_per_um": float(r["ION_A_per_um"]),
                 "IOFF_A_per_um": float(r["IOFF_A_per_um"]),
                 "gm_peak_S_per_um": float(r["gm_peak_S_per_um"])}
        except (ValueError, KeyError):
            continue
        u = encode(params)
        if np.any(u < -0.02) or np.any(u > 1.02):   # outside v2 box
            continue
        U.append(np.clip(u, 0, 1))
        s = score(m)
        ys.append(s)
        keep.append({"run_id": "warm_" + r["run_id"], "score": s,
                     "status": "ok", "metrics": m, "params": params})
    U, ys = np.array(U), np.array(ys)
    _save(U, ys, 1, keep)
    print("[%s] warmstarted with %d prior evals (cap=%.0e). best=%.4f"
          % (CAMP, len(ys), IOFF_CAP, float(np.max(ys))))


def cmd_init():
    X, y, rnd, results = _load()
    if len(y):
        print("[%s] state exists; refusing re-init" % CAMP)
        return
    U = lhs(N_INIT, seed=42)
    ys, keep = _evaluate(U, "g00")
    _save(U, ys, 1, keep)
    print("[%s] init best %.4f" % (CAMP, float(np.max(ys))))


def cmd_step():
    X, y, rnd, results = _load()
    if not len(y):
        print("[%s] no state -- warmstart or init first" % CAMP)
        return
    ok = y > -14.0
    if ok.sum() < 5:
        ok = y > -16.0          # fall back if cap is very tight
    gpm = GP(X[ok], y[ok])
    anchors = X[ok][np.argsort(y[ok])[-5:]]
    U = propose_batch(gpm, float(np.max(y[ok])), N_BATCH, DIM,
                      seed=1000 + rnd, X_anchor=anchors)
    ys, keep = _evaluate(U, "g%02d" % rnd)
    X, y = np.vstack([X, U]), np.append(y, ys)
    _save(X, y, rnd + 1, results + keep)
    print("[%s] round %d: batch best %.4f | campaign best %.4f | %d evals"
          % (CAMP, rnd, float(np.max(ys)), float(np.max(y)), len(y)))


def cmd_best(n=5):
    X, y, rnd, results = _load()
    if not len(results):
        print("[%s] no results" % CAMP)
        return
    top = sorted(results, key=lambda r: r["score"], reverse=True)[:n]
    for i, r in enumerate(top):
        m = r["metrics"] or {}
        print("#%d score=%.4f run=%s ION=%.3e IOFF=%.3e gm=%.3e"
              % (i + 1, r["score"], r["run_id"], m.get("ION_A_per_um", 0),
                 m.get("IOFF_A_per_um", 0), m.get("gm_peak_S_per_um", 0)))
    print("\n[%s cap=%.0e] champion params:" % (CAMP, IOFF_CAP))
    print(json.dumps(top[0]["params"], indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "best"
    if cmd == "warmstart":
        cmd_warmstart(sys.argv[2])
    elif cmd == "init":
        cmd_init()
    elif cmd == "step":
        cmd_step()
    elif cmd == "auto":
        for _ in range(int(sys.argv[2]) if len(sys.argv) > 2 else 5):
            cmd_step()
    else:
        cmd_best(int(sys.argv[2]) if len(sys.argv) > 2 else 5)
