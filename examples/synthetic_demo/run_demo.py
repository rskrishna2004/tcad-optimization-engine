#!/usr/bin/env python3
"""
TCADOpt synthetic demo
======================

Runs the COMPLETE optimization pipeline with NO simulator required.

A real campaign spends minutes per design running a physics simulator. This
demo swaps the simulator for a fast synthetic function that behaves like a
transistor: it has an "on current" to maximize and a "leakage current" that
must stay under a cap, and the two are coupled through a threshold-like
quantity, exactly the trade-off a real device has.

Everything else is the real engine: the real parameter space, the real
Gaussian-process surrogate, the real trust-region Bayesian optimizer, the
real scorer. If this runs, your installation works.

Usage
-----
    python examples/synthetic_demo/run_demo.py
    python examples/synthetic_demo/run_demo.py --seed 1
    python examples/synthetic_demo/run_demo.py --seed 2 --rounds 8

Run it with several different seeds. If the champions agree, that agreement
is your practical evidence of a global optimum. This is exactly how you
should use the engine on a real device.
"""
import argparse
import math
import os
import sys

# --- make the engine importable no matter where this is run from ----------
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for p in (ROOT, os.path.join(ROOT, "optimizer")):
    if p not in sys.path:
        sys.path.insert(0, p)

from tcadopt.l1_spec.paramspace import ParamSpace      # noqa: E402
from tcadopt.l1_spec.scorer import build_scorer        # noqa: E402
from tcadopt.l5_opt.optimizer import Optimizer  # noqa: E402


# ==========================================================================
#  THE SYNTHETIC "SIMULATOR"
#
#  This stands in for a TCAD run. In a real campaign this function is
#  replaced by: render the design into a deck -> run the simulator ->
#  parse the electrical output. See docs/CONNECTING_A_SIMULATOR.md.
#
#  The physics being mimicked:
#    * A threshold-like quantity VT rises with the pocket dose and with the
#      source underlap (they raise the source barrier).
#    * ON current falls as VT rises (less overdrive) and rises as the
#      source/drain doping rises (less series resistance).
#    * OFF current falls exponentially with VT (the subthreshold slope).
#  So ON and OFF are chained through VT: you cannot independently maximize
#  one and minimize the other. That is the real trade-off.
# ==========================================================================
def synthetic_simulator(params):
    NSD = params["NSD"]          # source/drain doping [cm-3]
    LEXT = params["LEXT"]        # source underlap [um]
    NPOCKET = params["NPOCKET"]  # source pocket dose [cm-3]

    # --- threshold-like quantity: raised by underlap and by pocket dose ---
    vt = (0.05
          + 20.0 * LEXT
          + 0.050 * math.log10(NPOCKET / 1.0e15))

    # --- the two COSTS of raising vt (this is what makes the optimum
    #     interior rather than at a corner, exactly as in a real device) ---
    # 1. impurity scattering: a heavy pocket dose degrades channel mobility
    mobility = 1.0 / (1.0 + (NPOCKET / 1.5e19) ** 0.8)
    # 2. series resistance: a long underlap is an ungated resistor, and
    #    heavier source/drain doping reduces resistance
    r_series = (1.0 + 220.0 * LEXT) / (1.0 + 0.6 * math.log10(NSD / 1.0e19))

    overdrive = max(0.7 - vt, 0.02)          # supply 0.7 V

    ion = 5.5e-5 * overdrive * mobility / r_series

    # --- leakage: exponential in vt with a ~62 mV/decade slope ---
    ioff = 1.0e-8 * 10.0 ** (-vt / 0.062)

    gm = ion / max(overdrive, 0.05) * 0.9

    # NOTE: these key names must match what the scorer expects. The engine's
    # canonical names are ION_A_per_um / IOFF_A_per_um / gm_peak_S_per_um.
    # Mismatched metric names are the #1 integration bug: see
    # docs/CONNECTING_A_SIMULATOR.md, "Metric name matching".
    return {
        "ION_A_per_um": ion,
        "IOFF_A_per_um": ioff,
        "gm_peak_S_per_um": gm,
        "VT_V": vt,
    }


# ==========================================================================
#  THE DEMO PROBLEM (the same structure a real problem YAML has)
# ==========================================================================
PARAMETERS = {
    "NSD":     [1.0e19, 5.0e20, "log", "cm-3"],
    "LEXT":    [0.0,    0.010,  "lin", "um"],
    "NPOCKET": [1.0e15, 8.0e19, "log", "cm-3"],
}

OBJECTIVES = [
    {"metric": "ION", "sense": "max", "weight": 1.0},
    {"metric": "IOFF", "sense": "min", "weight": 0.4},
    {"metric": "IOFF", "cap": 1.0e-10},
]

CAP = 1.0e-10


def main():
    ap = argparse.ArgumentParser(description="TCADOpt synthetic demo")
    ap.add_argument("--seed", type=int, default=0,
                    help="random seed; run several and compare champions")
    ap.add_argument("--init", type=int, default=24,
                    help="number of initial designs")
    ap.add_argument("--batch", type=int, default=12,
                    help="designs proposed per round")
    ap.add_argument("--rounds", type=int, default=6,
                    help="number of optimization rounds")
    args = ap.parse_args()

    space = ParamSpace(PARAMETERS)
    scorer = build_scorer(OBJECTIVES, cap=CAP)
    opt = Optimizer(space)

    print("TCADOpt INSTALL SELF-CHECK   (NOT a device simulation)")
    print("This runs the optimizer loop against a stand-in MATH FUNCTION to")
    print("prove the engine installed correctly. No TCAD tool is called and")
    print("no device is simulated. For real device optimization see")
    print("docs/WORKFLOW.md.")
    print("=" * 66)
    print("  parameters : %s" % ", ".join(sorted(PARAMETERS)))
    print("  objective  : maximize ION, minimize IOFF, cap IOFF <= %.1e" % CAP)
    print("  seed=%d  init=%d  batch=%d  rounds=%d"
          % (args.seed, args.init, args.batch, args.rounds))
    print("-" * 66)

    X, y = [], []          # encoded designs and their scores
    archive = []           # everything we have seen

    def evaluate(U, tag):
        """Run the 'simulator' on a batch of encoded designs."""
        ok = 0
        for u in U:
            p = space.decode(u)
            m = synthetic_simulator(p)
            s = scorer(m)
            if s is None:
                continue
            X.append(list(u))
            y.append(s)
            archive.append({"params": p, "metrics": m, "score": s})
            ok += 1
        print("  %-10s %d/%d evaluated" % (tag, ok, len(U)))

    # ---- initial design ---------------------------------------------------
    U = opt.propose([], [], args.init, mode="lhs_init", seed=args.seed)
    evaluate(U, "init")
    best = max(y)
    print("    init best score = %.4f" % best)

    # ---- optimization rounds ---------------------------------------------
    hist = [best]
    for rd in range(args.rounds):
        U = opt.propose(X, y, args.batch, mode="bo_round",
                        seed=args.seed + rd + 1)
        evaluate(U, "round %d" % rd)
        best = max(y)
        hist.append(best)
        print("    round %d best = %.4f" % (rd, best))
        if Optimizer.floor_detected(hist, patience=2, eps=1e-3):
            if opt.exhausted(max_restarts=3):
                print("    floor + restarts exhausted -> stop")
                break
            opt.force_restart()
            print("    floor detected -> trust-region restart")

    # ---- champion + evidence ---------------------------------------------
    champ = max(archive, key=lambda r: r["score"])
    m, p = champ["metrics"], champ["params"]
    scores = sorted((r["score"] for r in archive), reverse=True)
    runner = next((s for s in scores[1:] if s < scores[0] - 1e-9), None)
    gap = (scores[0] - runner) if runner is not None else 0.0

    print("-" * 66)
    print("CHAMPION  score=%.4f" % champ["score"])
    print("  ION  = %.4e A      IOFF = %.4e A   (ratio %.2e)"
          % (m["ION_A_per_um"], m["IOFF_A_per_um"],
             m["ION_A_per_um"] / m["IOFF_A_per_um"]))
    print("  gm   = %.4e S      VT   = %.3f V" % (m["gm_peak_S_per_um"], m["VT_V"]))
    print("  design: NSD=%.3e  LEXT=%.5f um  NPOCKET=%.3e"
          % (p["NSD"], p["LEXT"], p["NPOCKET"]))
    print("")
    print("  ---- convergence evidence ----")
    print("  designs evaluated : %d" % len(archive))
    print("  gap to runner-up  : %.4f  (%s)" % (
        gap, "sharp, well-separated optimum" if gap > 0.05
        else "flat top: many near-equal optima"))
    print("  top-5 scores      : %s"
          % ", ".join("%.4f" % s for s in scores[:5]))
    print("")
    print("  Run this again with --seed 1 and --seed 2. If the champions")
    print("  agree, that agreement is your practical global-optimum evidence.")
    print("=" * 66)


if __name__ == "__main__":
    main()
