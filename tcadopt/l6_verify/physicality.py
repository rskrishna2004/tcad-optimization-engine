"""l6_verify.physicality -- is the fitted card still a transistor?

WHY THIS FILE EXISTS, IN THE MODEL'S OWN WORDS
----------------------------------------------
BSIM-CMG 112.1.0 Technical Manual, section 3.9, "Lateral Non-uniform Doping
Model", immediately after equation 3.525:

    "A word of CAUTION: The above Lateral non-uniform doping model or the Body
     Effect model are empirical and have their limits as to how much Vth shift
     can be achieved without distorting the I-V curve. OVER USAGE COULD LEAD TO
     NEGATIVE gm OR NEGATIVE gds."

That is the model's author warning that a particular parameter can produce a
card which fits the curve and is not a transistor. Nothing in TCADOpt checked.
An optimizer minimising an RMS residual has no reason not to walk into that
region: a curve with a dip in it can have a smaller RMS error than a smooth
curve that is slightly offset, and the fit will take the dip.

A negative transconductance is not a slightly worse fit. It is a device that
turns OFF when you turn the gate UP, it breaks every circuit simulation the
compact model exists to serve, and it is invisible in a residual number.

WHAT IS CHECKED, AND WHY THAT IS THE RIGHT CHECK
------------------------------------------------
For an n-channel device with the reference sweeps this project owns:

    Ids-Vgs at fixed Vds : Ids must be non-decreasing in Vgs   (gm  >= 0)
    Ids-Vds at fixed Vgs : Ids must be non-decreasing in Vds   (gds >= 0)

Both are statements about the SWEPT variable of the sweep in front of us, so
one function covers both and neither needs to know which is which. The test is
run on the MODEL curve, on the same bias grid the reference uses, so a
violation is reported at a bias the reference actually visits.

TOLERANCE. A simulator's printed current carries a finite number of digits --
PrimeSim HSPICE prints 7 -- so two adjacent points on a flat part of a curve
can differ in the last digit and produce a spurious tiny negative slope. The
check is therefore relative: a step is a violation when the current DROPS by
more than `rel_tol` of the larger of the two values. At the default 1e-6 that
is a hundred times the print quantum and far below any real non-monotonicity.

It is a hard veto, not a penalty term. A penalty has to be weighted against
the residual, which means choosing how many percent of current error one unit
of "not a transistor" is worth -- a question with no answer. A card that is not
monotone is simply not a candidate.

$Id: physicality.py, 2026/09/17 [YOUR NAME] $
"""
import numpy as np

REL_TOL = 1.0e-6


def monotonicity(v, i, rel_tol=REL_TOL):
    """Check that |i| never decreases as v increases.

    Returns a dict:
      ok          : True when the curve is monotone within tolerance
      n_bad       : how many adjacent steps go the wrong way
      worst_drop  : the largest relative drop found (0.0 when ok)
      worst_v     : the bias at which that drop ends
      frac_bad    : n_bad / (number of steps)
    """
    if v is None or i is None:
        return {"ok": False, "n_bad": -1, "worst_drop": float("nan"),
                "worst_v": float("nan"), "frac_bad": float("nan"),
                "reason": "no curve"}
    v = np.asarray(v, float)
    a = np.abs(np.asarray(i, float))
    if v.size < 3 or v.size != a.size:
        return {"ok": False, "n_bad": -1, "worst_drop": float("nan"),
                "worst_v": float("nan"), "frac_bad": float("nan"),
                "reason": "curve too short"}
    o = np.argsort(v)
    v, a = v[o], a[o]
    d = a[1:] - a[:-1]
    scale = np.maximum(np.maximum(a[1:], a[:-1]), 1e-30)
    rel = d / scale                       # negative where the current drops
    bad = rel < -rel_tol
    n_bad = int(bad.sum())
    if n_bad == 0:
        return {"ok": True, "n_bad": 0, "worst_drop": 0.0,
                "worst_v": float("nan"), "frac_bad": 0.0}
    k = int(np.argmin(rel))
    return {"ok": False, "n_bad": n_bad, "worst_drop": float(-rel[k]),
            "worst_v": float(v[k + 1]),
            "frac_bad": float(n_bad) / float(len(rel))}


def audit(curves, names=None, rel_tol=REL_TOL):
    """Run `monotonicity` over a {name: (v, i)} dict of model curves.

    C-V sweeps are skipped by name (anything containing '_CV_'): a gate
    capacitance is NOT required to be monotone in Vg -- a real Cgg-Vg curve can
    dip in weak inversion -- so applying a current test to it would veto
    perfectly good cards. Only the current sweeps are checked, which is what
    the manual's warning is about.

    Returns (ok, report) where report is {name: monotonicity_dict} for the
    sweeps that were checked.
    """
    rep = {}
    for name in sorted(curves or {}):
        if names is not None and name not in names:
            continue
        if "_CV_" in name:
            continue
        vi = curves[name]
        if not vi or len(vi) != 2:
            continue
        rep[name] = monotonicity(vi[0], vi[1], rel_tol=rel_tol)
    ok = all(r.get("ok") for r in rep.values()) if rep else True
    return ok, rep


def format_report(rep):
    """A few lines fit for a run log."""
    if not rep:
        return "  monotonicity: no current sweeps to check"
    out = ["  %-22s %-6s %-8s %-12s %s"
           % ("sweep", "ok", "n_bad", "worst drop", "at Vsweep")]
    out.append("  " + "-" * 62)
    for n in sorted(rep):
        r = rep[n]
        out.append("  %-22s %-6s %-8s %-12s %s"
                   % (n, "yes" if r.get("ok") else "NO",
                      r.get("n_bad"),
                      ("%.3e" % r["worst_drop"]) if np.isfinite(
                          r.get("worst_drop", float("nan"))) else "-",
                      ("%+.4f V" % r["worst_v"]) if np.isfinite(
                          r.get("worst_v", float("nan"))) else "-"))
    return "\n".join(out)
