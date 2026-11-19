# -*- coding: utf-8 -*-
"""l1_spec.achievable -- weighting each curve by how much of it can be fixed.

WHY THIS MODULE EXISTS
----------------------
`CurveResidualScorer` already reads a `weight` from every target, and its
total is a weighted mean of the per sweep root mean squares. Nothing in this
project has ever set those weights to anything but one. Every curve has
counted the same, and one of them could not be improved at all.

`l6_verify.floor` measures, curve by curve, how much of the present error a
fit could still remove. This module turns that measurement into the weights,
by one rule written down before any fit runs:

    a curve's weight is the fraction of its own error that is still reachable

So a curve the model has made structurally incapable of following the device
-- Cgb on this card, which the model makes a constant while the device slopes
-- gets a weight of zero and stops competing. A curve with headroom keeps its
weight of one. Nothing in between needs a constant I chose.

WHAT IT CHANGES, IN NUMBERS
----------------------------
On the frozen card, the eight capacitance curves carry a sum of squares of
1.71538. Of that, 1.06673 is the two Cgb curves and all of it is irreducible:
their best possible constant leaves 0.70179 and 0.36495, against the 0.70268
and 0.36527 the card already has. So 62 per cent of the capacitance objective
was a term already at its own optimum.

That is not a small distortion. It is most of the score. For twelve steps the
optimiser has been marked mostly on something it cannot change, which is why
every capacitance stage has come back looking like it did nothing.

WHAT IT DOES NOT DO
-------------------
It does not hide the curve. A weight of zero removes a curve from the thing
being MINIMISED, not from the thing being REPORTED. Every run that uses this
prints the zero weighted curves, their error, and the line of the model
source that caps them, so the limit is on the page rather than behind it.
"""
from __future__ import print_function

VERSION = "1.1.30"


def apply_weights(targets, weights, default=1.0):
    """New target dicts with `weight` set from a {name: weight} mapping.

    The originals are not touched: a stage that wants the unweighted score
    for reporting keeps its own list.
    """
    out = []
    for t in targets:
        q = dict(t)
        q["weight"] = float(weights.get(t.get("name"), default))
        out.append(q)
    return out


def live(targets, weights, eps=1.0e-12):
    """The targets whose weight is not zero, in the order given."""
    return [t for t in targets
            if float(weights.get(t.get("name"), 1.0)) > eps]


def capped(targets, weights, eps=1.0e-12):
    """The targets a floor measurement has taken out of the objective."""
    return [t for t in targets
            if float(weights.get(t.get("name"), 1.0)) <= eps]


def format_weights(weights, rows=None, title=None):
    """One block saying what is being minimised and what is only reported."""
    byname = dict((r["name"], r) for r in (rows or []))
    keep = sorted([k for k, v in weights.items() if v > 1.0e-12])
    drop = sorted([k for k, v in weights.items() if v <= 1.0e-12])
    L = [title or "    what the fit is being marked on:", ""]
    L.append("      minimised (%d):" % len(keep))
    for k in keep:
        L.append("        %-26s weight %.3f" % (k, weights[k]))
    if drop:
        L.append("")
        L.append("      reported but not minimised (%d), because a fit cannot"
                 % len(drop))
        L.append("      reduce them:")
        for k in drop:
            r = byname.get(k) or {}
            ss, f = r.get("ss"), r.get("floor")
            if ss and f is not None:
                L.append("        %-26s error %.5f, of which %.5f is the "
                         "best any" % (k, ss, min(f, ss)))
                L.append("        %-26s card can do" % "")
            else:
                L.append("        %-26s" % k)
    return "\n".join(L)


def share_weights(rows, floor=0.02, cap=8.0):
    """Weight each curve by its SHARE of the error that is left.

    v1.1.33. THE MEASUREMENT THAT FORCED THIS
    ------------------------------------------
    Every objective in this project is the weighted MEAN of each curve's root
    mean square, with the weights all 1.0. That means eight curves each carry
    one eighth of the gradient, however big or small their own error is.

    On the card this was added for, the eight capacitance curves carried these
    sums of squares:

        Cgd at Vd = 0.05 V   0.364610     48.5 per cent of everything left
        Cgs at Vd = 0.05 V   0.121903     16.2
        Cgg at Vd = 0.05 V   0.099799     13.3
        Cgb at Vd = 0.05 V   0.085184     11.3
        Cgs at Vd = 0.60 V   0.046058      6.1
        Cgg at Vd = 0.60 V   0.019411      2.6
        Cgb at Vd = 0.60 V   0.014820      2.0
        Cgd at Vd = 0.60 V   0.000309      0.0

    One curve was half the problem and the objective gave it an eighth of the
    attention. A free fit with twenty three parameters ran on that objective
    and moved Cgd at the low drain bias from 6.32996 to 6.32985 per cent,
    which is nothing, while reporting a 0.35 per cent improvement in the
    total. The fit was not stuck. It was pointed at the wrong thing.

    THE RULE: a curve's weight is its share of the remaining sum of squares,
    normalised so the weights average 1.0 and the objective keeps its
    familiar size. `floor` stops an already good curve from falling out of
    the objective entirely and being free to drift; `cap` stops one bad curve
    from owning the whole gradient and starving the rest.

    The weights are computed ONCE, from the card the fit starts on, and held
    for the whole fit. Recomputing them as the fit moves would make the
    objective a moving target and nothing could be compared with anything.
    """
    live = [r for r in rows if r.get("ss") is not None and r.get("ss") > 0.0]
    if not live:
        return dict((r["name"], 1.0) for r in rows)
    tot = sum(r["ss"] for r in live)
    n = float(len(live))
    out = {}
    for r in rows:
        ss = r.get("ss")
        if ss is None or ss <= 0.0 or tot <= 0.0:
            out[r["name"]] = float(floor)
            continue
        w = n * ss / tot
        out[r["name"]] = float(min(max(w, float(floor)), float(cap)))
    return out


def format_share(wts, rows, title=None):
    tot = sum(r["ss"] for r in rows if r.get("ss")) or 1.0
    L = [title or "    what the fit is pointed at:", "",
         "      %-26s %10s %9s %8s" % ("curve", "sum sq", "share", "weight"),
         "      " + "-" * 58]
    for r in sorted(rows, key=lambda x: -(x.get("ss") or 0.0)):
        ss = r.get("ss")
        if ss is None:
            continue
        L.append("      %-26s %10.5f %8.1f %% %8.3f"
                 % (r["name"], ss, 100.0 * ss / tot,
                    (wts or {}).get(r["name"], 1.0)))
    return "\n".join(L)
