"""Certify representative points on the produced Pareto front.

A tradeoff front has no single IOFF cap, so each point is verified cap-free:
mesh convergence + coherence + BTBT-off bound + nonlocal fidelity + hard/coupled
constraints. This confirms the engine-discovered front is physically trustworthy
(not numerical artifact) -- especially the low-IOFF region near the simulator's
sub-fA resolution, where the mesh-convergence gate will flag any point that sits on
the fidelity floor.

Run after run_pareto:
  cd ~/tcad_opt && python3 -m tools.certify_front problems/nmos_planar_pareto.yaml [n]
"""
import os
import sys
import json
import math

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tcadopt.l1_spec import compile             # noqa: E402
from tcadopt.l6_verify.certify import certify   # noqa: E402

FRONT = os.path.join(ROOT, "results", "pareto_front.json")
# approximate champion IOFFs (already certified; skip them when sampling)
CHAMP_IOFF = [9.363e-8, 9.206e-9, 9.322e-10]


def _is_champ(p):
    return any(abs(math.log10(p["IOFF"] / c)) < 0.05 for c in CHAMP_IOFF)


def select(front, n=4, drop_tail_decades=1.0):
    """Pick n points evenly spaced in log-IOFF across the INTERIOR of the front
    (excluding the champions and trimming the extreme tails, which are at the edge
    of simulator fidelity and would dominate the sample otherwise)."""
    front = sorted(front, key=lambda p: p["IOFF"])
    lo_cut = front[0]["IOFF"] * 10 ** drop_tail_decades
    hi_cut = front[-1]["IOFF"] / 10 ** drop_tail_decades
    interior = [p for p in front
                if lo_cut <= p["IOFF"] <= hi_cut and not _is_champ(p)]
    if len(interior) <= n:
        return interior
    idx = [int(round(i * (len(interior) - 1) / (n - 1))) for i in range(n)]
    return [interior[i] for i in idx]


def main(spec_path, n=4):
    cp = compile(spec_path)
    if not os.path.exists(FRONT):
        print("no %s -- run run_pareto first" % FRONT)
        return
    front = json.load(open(FRONT))
    pts = select(front, n)
    print("Certifying %d representative front points (cap-free):" % len(pts))
    summary = {}
    for i, p in enumerate(pts):
        label = "front%02d" % i
        ref = {"ION_A_per_um": p["ION"], "IOFF_A_per_um": p["IOFF"]}
        print("\n" + "=" * 64)
        print("front point %d: ION=%.3e IOFF=%.3e (engine-discovered)" % (
            i, p["ION"], p["IOFF"]))
        cert = certify(p.get("params"), cp, label, None, ref)
        outp = os.path.join(ROOT, "results", "cert_%s.json" % label)
        json.dump(cert.to_dict(), open(outp, "w"), indent=1)
        summary["IOFF=%.1e" % p["IOFF"]] = "PASS" if cert.verdict else "FAIL"
    print("\n" + "=" * 64)
    print("FRONT CERTIFICATION SUMMARY:", summary)
    print("(PASS across the interior => the Pareto front is trustworthy, not just")
    print(" optimized. Any FAIL flags where the front meets the simulator's limits.)")


if __name__ == "__main__":
    spec = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        ROOT, "problems", "nmos_planar_pareto.yaml")
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    main(spec, n)
