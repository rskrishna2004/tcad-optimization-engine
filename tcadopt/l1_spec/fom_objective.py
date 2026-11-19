# -*- coding: utf-8 -*-
"""l1_spec.fom_objective -- fit to a derived number, not only to a curve.

v1.1.27.  THE GAP THIS CLOSES, AND HOW STEP 26 FOUND IT
--------------------------------------------------------
Every fit this project has run minimised the distance between two CURVES,
point by point. That is the right thing to minimise for most of what a
compact model has to do, and it is what every stage from Step 1 to Step 26
did.

It is not the only thing that matters, and Step 26 proved it by accident.

The drain share of the channel charge is not a point on a curve. It is a
number DERIVED from three curves: take Cgd, Cgs and Cgb at the top of the
gate sweep, subtract each one's own value at the bottom of the sweep to
remove the fixed overlap and fringe part, and divide the drain piece by the
total. On this device the model gives 38.5 per cent and the device gives
49.0 per cent.

Step 26 moved all 667 base parameters one at a time and found several that
move that number a long way:

    cgdl       at 1e-8   closes 546 per cent of the gap, no current cost
    qmtcencv   at 100    closes  96 per cent of the gap, no current cost
    cgsl       negative  closes  32 per cent of the gap, no current cost

and CGDL, CGSL and QMTCENCV were all already on the card and already in the
fit. They had been free the whole time.

So why did the fit never use them for this? Because the fit was never asked
to. Minimising curve error and matching a derived ratio are different
objectives, and a parameter move that fixes the ratio while making the curve
rms very slightly worse is a move the old objective rejects every time.

That is OUR gap, not the model's. This module closes it: a target can now be
a NUMBER computed from the curves, with its own weight, sitting in the same
objective as the point by point residuals. The optimiser then trades them
against each other instead of being blind to one of them.
"""
import math

VERSION = "1.1.27"


class FoMTarget(object):
    """One derived number the fit should match.

    `extract(curves) -> float` computes it from the simulated curves.
    `want` is the value the device gives.
    `weight` is how many curve points this one number is worth. A curve has
    about a hundred points, so a weight of 10 says this single number
    matters about a tenth as much as one whole curve, which is the right
    order for a figure of merit that summarises three curves at one bias.
    `scale` makes the residual dimensionless; it defaults to |want|.
    """

    def __init__(self, name, extract, want, weight=10.0, scale=None,
                 note=""):
        self.name = name
        self.extract = extract
        self.want = float(want)
        self.weight = float(weight)
        self.scale = float(scale) if scale else max(abs(float(want)),
                                                    1.0e-300)
        self.note = note

    def residual(self, curves):
        """The weighted, scaled residual entries this target contributes.

        It returns a LIST so that the sum of squares of the whole residual
        vector is still the number the optimiser minimises, exactly as it is
        for the curve points. Nothing about the optimiser has to change.
        """
        try:
            got = self.extract(curves)
        except Exception:
            return None
        if got is None or not _finite(got):
            return None
        r = (float(got) - self.want) / self.scale
        w = math.sqrt(max(self.weight, 0.0))
        return [w * r]

    def report(self, curves):
        try:
            got = self.extract(curves)
        except Exception:
            got = None
        if got is None or not _finite(got):
            return {"name": self.name, "model": None, "want": self.want,
                    "gap": None, "note": self.note}
        return {"name": self.name, "model": float(got), "want": self.want,
                "gap": self.want - float(got), "note": self.note}


def _finite(x):
    try:
        return x == x and abs(x) != float("inf")
    except Exception:
        return False


class CompositeResidual(object):
    """Curve residuals and figure of merit residuals, in one vector.

    The optimiser is handed one function that returns one vector, and the
    sum of its squares is the thing being minimised. That is exactly the
    contract the aligner already had, so adding a derived target does not
    change a single line of the optimiser.

    `curve_residual(curves) -> list or array` is the existing point by point
    residual. `foms` is a list of FoMTarget.
    """

    def __init__(self, curve_residual, foms=None, log=None):
        self.curve_residual = curve_residual
        self.foms = list(foms or [])
        self.log = log
        self.n_curve = None
        self.n_fom = len(self.foms)

    def __call__(self, result):
        import numpy as np
        curves = (result or {}).get("curves") if isinstance(result, dict) \
            else result
        base = self.curve_residual(result)
        if base is None:
            return None
        base = np.asarray(base, float)
        self.n_curve = int(base.size)
        if not self.foms:
            return base
        extra = []
        for f in self.foms:
            r = f.residual(curves or {})
            if r is None:
                #  a target that cannot be computed on this card must not
                #  silently change the length of the residual vector, which
                #  would make the optimiser compare vectors of different
                #  sizes. It contributes a zero of the right length instead,
                #  and the caller can see it in `report`.
                r = [0.0]
            extra.extend(r)
        return np.concatenate([base, np.asarray(extra, float)])

    def report(self, curves):
        return [f.report(curves or {}) for f in self.foms]

    def describe(self):
        L = ["    the objective being minimised has two parts:"]
        L.append("      %-34s %s" % ("point by point curve residuals",
                                     self.n_curve if self.n_curve
                                     else "counted at the first call"))
        for f in self.foms:
            L.append("      %-34s want %-12.6g weight %g"
                     % (f.name, f.want, f.weight))
            if f.note:
                L.append("        %s" % f.note)
        return "\n".join(L)


def format_fom_report(rows, title=None):
    L = [title or "    the derived targets:"]
    L.append("      %-16s %-14s %-14s %-14s" % ("target", "model", "device",
                                                "gap"))
    for r in rows:
        L.append("      %-16s %-14s %-14.6g %-14s"
                 % (r["name"],
                    ("%.6g" % r["model"]) if r["model"] is not None
                    else "could not compute",
                    r["want"],
                    ("%.6g" % r["gap"]) if r["gap"] is not None else "-"))
    return "\n".join(L)
