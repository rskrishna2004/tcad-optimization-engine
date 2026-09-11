#!/usr/bin/env python3
"""
TCADOpt extraction self-check
=============================

Runs the COMPLETE parameter-extraction pipeline with NO circuit simulator
required.

A real extraction runs HSPICE once per target sweep per candidate. This
self-check swaps HSPICE for a fast analytic transistor whose parameters carry
the same names and the same physical roles as the BSIM-CMG ones being fitted.
Everything else is the real engine: the real parameter space, the real
Gaussian-process surrogate, the real trust-region optimizer, the real
curve-residual scorer, the real experiment database, and the real staged
freezing logic.

It has a KNOWN answer, so it does not merely prove the loop runs -- it proves
the loop recovers a value it was not given.

Usage
-----
    python examples/extraction_demo/run_demo.py
    python examples/extraction_demo/run_demo.py --seed 1
    python examples/extraction_demo/run_demo.py --stage 2

What to look for
----------------
1. The stage error falls round on round, in DECADES for sub-threshold and in
   PERCENT for the on state. Two numbers, not one, so a stall tells you which
   half stalled.
2. PHIG comes back within a few millivolts of the hidden value. PHIG is what
   stage 1 is designed to determine, and it is the parameter that sets the
   threshold voltage in a surface-potential model.
3. The identifiability report finds the degeneracies that were deliberately
   built into the stand-in model. Those parameters CANNOT be recovered
   individually by any method, and the report says so rather than reporting a
   confident wrong number.
"""
import argparse
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tcadopt.l1_spec.curve_scorer import CurveResidualScorer    # noqa: E402
from tcadopt.l6_verify.identifiability import (                 # noqa: E402
    analyse, jacobian, report)

# ==========================================================================
#  THE STAND-IN FOR HSPICE
#
#  In a real extraction this is replaced by: render the candidate into a
#  BSIM-CMG model card -> write an HSPICE deck per sweep -> run HSPICE ->
#  parse the listing.  See tcadopt/l3_exec/spice_exec.py.
#
#  TWO DEGENERACIES ARE BUILT IN ON PURPOSE:
#    * CIT, CDSC and NFACTOR enter only through one sum. Only that sum is
#      determined by the data; the three values individually are not.
#    * ETA0 and DSUB enter only through one product. Same situation.
#  A real compact model is full of relationships like these. The point of the
#  identifiability check is to FIND them instead of reporting three confident
#  numbers that happen to be one arbitrary point on a ridge.
# ==========================================================================
TRUE = {
    "phig": 4.503, "cit": 1.2e-3, "cdsc": 3.0e-3, "nfactor": 1.15,
    "eta0": 0.085, "dsub": 0.55,
    "u0": 0.0312, "ua": 8.0e-10, "vsat": 9.0e4, "rdswmin": 145.0,
}


def stand_in_simulator(p, vg, vd):
    """|Id| for one candidate at one drain bias. Physically shaped, not real."""
    g = lambda k: float(p.get(k, TRUE[k]))               # noqa: E731
    vt = 0.370 + (g("phig") - 4.503) - g("eta0") * math.exp(-g("dsub")) * 6.0 * vd
    n = 1.0 + 0.25 * g("nfactor") + 60.0 * g("cit") + 25.0 * g("cdsc")
    vth_t = 0.02585 * n
    ov = np.maximum(vg - vt, 0.0)
    u_eff = g("u0") / (1.0 + g("ua") * 1e9 * ov)
    i_lin = 2.4e-2 * u_eff * ov ** 2 / (1.0 + ov / (g("vsat") * 4.0e-5))
    i_lin = i_lin / (1.0 + g("rdswmin") * i_lin * 1e3)
    i_sub = 1.0e-11 * np.exp(np.clip((vg - vt) / vth_t, -60, 40))
    return i_sub + i_lin + 1.0e-13


class StandInEvaluator(object):
    """Same interface as l3_exec.spice_exec.HSpiceEvaluator."""

    name = "stand_in_analytic"

    def __init__(self, targets, scorer=None):
        self.targets, self.scorer = list(targets), scorer

    def evaluate_batch(self, param_dicts, tag="f"):
        out = []
        for i, p in enumerate(param_dicts):
            curves = {t["name"]: (t["v"], stand_in_simulator(
                p, np.asarray(t["v"], float), abs(float(t["bias"]))))
                for t in self.targets}
            r = {"run_id": "%s%03d" % (tag, i), "params": dict(p),
                 "status": "ok", "curves": curves, "wall_s": 0.0,
                 "failure_class": "ok"}
            if self.scorer:
                r["metrics"] = self.scorer.as_metrics(curves)
            out.append(r)
        return out


# ==========================================================================
#  THE DEMO PROBLEM (the same shape a real fit spec has)
# ==========================================================================
STAGES = [
    ("s1_electrostatics", [0.05], {
        "phig":    [4.35, 4.65, "lin", "eV"],
        "cit":     [0.0, 5.0e-3, "lin", "F/m2"],
        "cdsc":    [0.0, 1.0e-2, "lin", "F/m2"],
        "nfactor": [0.0, 3.0, "lin", "-"]}),
    ("s2_short_channel", [0.05, 0.60], {
        "eta0": [0.0, 0.5, "lin", "-"],
        "dsub": [0.1, 2.0, "lin", "-"]}),
    ("s3_transport", [0.05, 0.60], {
        "u0":      [0.005, 0.08, "log", "m2/Vs"],
        "ua":      [1.0e-11, 1.0e-8, "log", "m/V"],
        "vsat":    [4.0e4, 2.0e5, "log", "m/s"],
        "rdswmin": [1.0, 500.0, "log", "ohm*um"]}),
]


def make_targets(biases):
    """The 'measured' curves: the stand-in run at the hidden true parameters."""
    vg = np.linspace(0.0, 0.7, 71)
    return [{"name": "IdVg_%.2f" % b, "v": vg,
             "i": stand_in_simulator(TRUE, vg, b),
             "weight": 1.0, "kind": "iv", "bias": b} for b in biases]


def main():
    from tcadopt.l1_spec.paramspace import ParamSpace
    from tcadopt.l5_opt.optimizer import Optimizer

    ap = argparse.ArgumentParser(description="TCADOpt extraction self-check")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--init", type=int, default=30)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--rounds", type=int, default=6)
    ap.add_argument("--stage", type=int, default=None,
                    help="run only this stage (1-3); default runs all")
    args = ap.parse_args()

    print("TCADOpt EXTRACTION SELF-CHECK   (NOT a circuit simulation)")
    print("The circuit simulator is replaced by a STAND-IN MATH FUNCTION so the")
    print("extraction loop can be proved without a SPICE licence. No model card")
    print("is simulated. For real extraction see docs/PARAMETER_EXTRACTION.md.")
    print("=" * 70)

    frozen, log_ = {}, []
    todo = ([STAGES[args.stage - 1]] if args.stage else STAGES)
    for label, biases, params in todo:
        targets = make_targets(biases)
        scorer = CurveResidualScorer(targets, i_split=1.0e-7)
        space = ParamSpace(params)
        ev = StandInEvaluator(targets, scorer=scorer)
        opt = Optimizer(space)

        print("-" * 70)
        print("STAGE %-18s free=%d  frozen=%d  sweeps=%d  backend=%s"
              % (label, space.dim, len(frozen), len(targets), opt.backend_name))
        print("  free   : %s" % ", ".join(space.names))
        if frozen:
            print("  frozen : %s" % ", ".join("%s=%.4g" % kv
                                              for kv in sorted(frozen.items())))

        X, y, arch = [], [], []

        def run(U, tag):
            plists = []
            for u in U:
                p = dict(frozen)
                p.update(space.decode(u))
                plists.append(p)
            for u, p, r in zip(U, plists, ev.evaluate_batch(plists, tag=tag)):
                s = scorer(r["curves"])
                if s is None or s <= -1e8 or not np.isfinite(s):
                    continue
                X.append(list(u)); y.append(s)
                arch.append((s, p, r["curves"]))

        run(opt.propose([], [], args.init, mode="lhs_init", seed=args.seed),
            "%s_init" % label)
        if not y:
            print("  no usable evaluation -- stopping"); return 1
        best = max(y)
        print("  init        error = %.5f" % (-best))
        hist = [best]
        for rd in range(args.rounds):
            run(opt.propose(X, y, args.batch, mode="bo_round",
                            seed=args.seed + rd + 1), "%s_r%d" % (label, rd))
            best = max(y); hist.append(best)
            print("  round %-2d    error = %.5f" % (rd, -best))
            if Optimizer.floor_detected(hist, patience=2, eps=1e-4):
                if opt.exhausted(max_restarts=2):
                    print("  floor + trust region exhausted -> stage done")
                    break
                opt.force_restart()

        s_best, p_best, c_best = max(arch, key=lambda t: t[0])
        b = scorer.breakdown(c_best)["per_sweep"][0]
        print("  STAGE COMPLETE  error = %.5f" % (-s_best))
        print("     sub-threshold  %.4f decades  (%.1f %% in current)"
              % (b["e_sub"], 100.0 * (10.0 ** b["e_sub"] - 1.0)))
        print("     on state       %.4f          (%.2f %%)"
              % (b["e_on"], 100.0 * b["e_on"]))
        for k in space.names:
            t = TRUE[k]
            err = 100.0 * abs(p_best[k] - t) / max(abs(t), 1e-30)
            print("     %-9s = %-12.6g  true %-12.6g  err %7.2f %%"
                  % (k, p_best[k], t, err))
            frozen[k] = p_best[k]
            log_.append((k, p_best[k], t, err))

    # ---- what a fit error alone can never tell you ----------------------
    print("=" * 70)
    print("IDENTIFIABILITY  --  which of these numbers are actually measured")
    print("=" * 70)
    targets = make_targets([0.05, 0.60])
    scorer = CurveResidualScorer(targets, i_split=1.0e-7)
    ev = StandInEvaluator(targets, scorer=scorer)
    names = ["phig", "cit", "cdsc", "nfactor", "eta0", "dsub",
             "u0", "vsat", "rdswmin"]
    J, used = jacobian(ev, scorer, TRUE, names, rel_step=0.02,
                       log_names=("u0", "ua", "vsat", "rdswmin"))
    print(report(analyse(J, used)))
    print()
    print("The stand-in model was built so CIT, CDSC and NFACTOR enter only")
    print("through one sum, and ETA0 and DSUB only through one product. Those")
    print("are exactly the pairs above. Their individual values cannot be")
    print("recovered by ANY method from this data -- and the fit error does not")
    print("reveal that, because a degenerate fit fits perfectly. This is why the")
    print("check exists.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
