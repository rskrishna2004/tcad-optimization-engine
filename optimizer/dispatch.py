# $Id: dispatch.py, v1.1 2026/07/06 [YOUR NAME] - DEVICE-AGNOSTIC ledger: append_master no longer device-agnostic results ledger: columns derived from each design's own parameters, so any parameter set is logged correctly. Logging is wrapped so it can never sink a batch whose simulations already succeeded. $
# Python 3.6 compatible. Evaluates many designs in parallel via multiprocessing.
import os
import sys
import csv
import json
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from runner import run_one  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, ".."))
RESULTS = os.path.join(ROOT, "results")
MASTER = os.path.join(RESULTS, "master.csv")

METRIC_COLS = ["ION_A_per_um", "IOFF_A_per_um", "ION_IOFF_ratio",
               "gm_peak_S_per_um", "SS_mV_per_dec",
               # IdVd output-characteristic driver (blank on IdVg runs)
               "Idsat_A_per_um", "gds_S_per_um", "intrinsic_gain",
               "Ron_Ohm_um", "Early_V", "DIBL_mV_per_V"]


def _eval(job):
    run_id, params, deck = job
    return run_one(params, run_id=run_id, deck=deck)


def _ledger_file_and_keys(params):
    """Device-agnostic ledger: columns are derived from the design's own
    parameters, so ANY parameter set is logged correctly. Designs that share
    the same parameter names share a results file; different schemas get
    their own file named by their parameter count."""
    keys = sorted(params.keys())
    return os.path.join(RESULTS, "master_%dp.csv" % len(keys)), keys


def append_master(results):
    """Ledger write. MUST NEVER raise: by the time this runs, every
    simulation in the batch has already completed -- a logging error must
    not destroy their results (FinFET KeyError:'TOX' lesson)."""
    try:
        os.makedirs(RESULTS, exist_ok=True)
        groups = {}
        for r in results:
            path, keys = _ledger_file_and_keys(r.get("params") or {})
            groups.setdefault((path, tuple(keys)), []).append(r)
        for (path, keys), rows in groups.items():
            new = not os.path.exists(path)
            with open(path, "a", newline="") as f:
                w = csv.writer(f)
                if new:
                    w.writerow(["run_id", "status", "wall_s"]
                               + list(keys) + METRIC_COLS)
                for r in rows:
                    m = r.get("metrics") or {}
                    p = r.get("params") or {}
                    w.writerow([r.get("run_id"), r.get("status"),
                                r.get("wall_s")]
                               + [p.get(k, "") for k in keys]
                               + [m.get(c, "") for c in METRIC_COLS])
    except Exception as e:            # ledger is best-effort, results are king
        print("[dispatch] master-ledger write skipped: %s: %s"
              % (type(e).__name__, e))


def run_batch(param_sets, n_parallel=8, tag="b", deck="nmos"):
    """param_sets: list of dicts. Returns list of result dicts."""
    jobs = [("%s%03d" % (tag, i), p, deck) for i, p in enumerate(param_sets)]
    with Pool(processes=n_parallel) as pool:
        results = pool.map(_eval, jobs)
    append_master(results)
    ok = sum(1 for r in results if r["status"] == "ok")
    print("batch done: %d/%d ok" % (ok, len(results)))
    return results


if __name__ == "__main__":
    # Usage: python3 dispatch.py batch.json [n_parallel] [tag]
    # batch.json = JSON list of parameter dicts (missing keys NOT allowed)
    sets = json.load(open(sys.argv[1]))
    npar = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    tag = sys.argv[3] if len(sys.argv) > 3 else "b"
    run_batch(sets, n_parallel=npar, tag=tag)
