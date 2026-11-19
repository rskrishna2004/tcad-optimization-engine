# -*- coding: utf-8 -*-
"""l1_spec.bias_pair -- can any knob move two drain biases in OPPOSITE
directions?

WHY THIS MODULE EXISTS
----------------------
Measured on the frozen card, the channel part of the gate capacitance -- the
value at the top of the gate sweep less the value at the bottom, so the fixed
overlap and fringe are gone -- is

    Vd = 0.05 V    the device  29.4915 aF    the card  23.3308 aF    79.1 %
    Vd = 0.60 V    the device  15.3326 aF    the card  17.4740 aF   114.0 %

The card is 21 per cent SHORT at the low drain bias and 14 per cent OVER at
the high one. To fix both at once a knob has to push the two biases in
opposite directions. A knob that scales the charge -- and most of the free
ones do, because they are a width, a length, or an oxide thickness -- moves
both the same way, so it can fix one bias only by making the other worse.
That is why twelve steps of capacitance fitting have traded one against the
other and never gained.

Every capacitance stage this project has run asked "how much did the error
drop". None of them asked "which way did each bias go". This module asks the
second question, which is the one that decides whether the parameter set on
the table can solve the problem at all.

WHAT IT RETURNS
---------------
For one probe it gives the pair (change at the low bias, change at the high
bias) and a one word verdict:

    opposite        raises one bias and lowers the other. This is the knob
                    the defect needs, and there may not be one
    gain            moves both the same way. Useful for size, useless for
                    shape
    low bias only   moves the low bias and leaves the high one alone
    high bias only  the mirror image. DvsatCV and MclmCV should land here,
                    because the terms they scale carry a factor of
                    (qis_cv - qid_cv) squared, which is nearly zero when the
                    drain bias is 50 mV
    dead            moves neither, so the parameter does nothing on this card

A run that finds no `opposite` knob in a free set has PROVED that the free set
cannot fix this defect, and can go and price a shared one instead of
spending another month inside the free zone. That is the point: a negative
answer here is worth as much as a positive one, and it arrives in minutes.
"""
from __future__ import print_function

VERSION = "1.1.30"


def channel_total(curves, vd_tag, terms=("cgd", "cgs", "cgb")):
    """The channel part of the gate capacitance at one drain bias, in farads.

    Each gate row capacitance is taken at the top of the gate sweep and its
    own value at the bottom is subtracted, which removes the overlap and the
    fringe because neither depends on the gate voltage. What is left is the
    charge the channel took. The three add to the channel part of Cgg.
    """
    import numpy as np
    tot, got = 0.0, 0
    for t in terms:
        c = (curves or {}).get("nsfet_n_CV_%s#%s" % (vd_tag, t))
        if c is None:
            continue
        x = np.asarray(c[0], float)
        y = np.asarray(c[1], float)
        if x.size < 2:
            continue
        o = np.argsort(x)
        y = y[o]
        tot += float(y[-1]) - float(y[0])
        got += 1
    return (tot, got)


def pair(curves, lo_tag="0.05", hi_tag="0.60"):
    """(channel total at the low bias, channel total at the high bias)."""
    a, na = channel_total(curves, lo_tag)
    b, nb = channel_total(curves, hi_tag)
    return (a if na else None), (b if nb else None)


def verdict(d_lo, d_hi, dead_frac=0.002):
    """One word for a pair of fractional changes.

    `dead_frac` is the size below which a change is called nothing. It is a
    fraction of the quantity, not an absolute capacitance, and it is set at
    two parts in a thousand, which is well above the simulator's own
    repeatability on these curves and well below the smallest change worth
    acting on.
    """
    if d_lo is None or d_hi is None:
        return "not measured"
    a_lo = abs(d_lo) >= dead_frac
    a_hi = abs(d_hi) >= dead_frac
    if not a_lo and not a_hi:
        return "dead"
    if a_lo and not a_hi:
        return "low bias only"
    if a_hi and not a_lo:
        return "high bias only"
    return "opposite" if (d_lo * d_hi) < 0.0 else "gain"


def need(model_lo, model_hi, dev_lo, dev_hi):
    """The fractional change the card needs at each bias, as a target."""
    out = {}
    if model_lo and dev_lo:
        out["lo"] = (dev_lo - model_lo) / model_lo
    if model_hi and dev_hi:
        out["hi"] = (dev_hi - model_hi) / model_hi
    return out


def curve_move(base_curves, probe_curves, names):
    """The largest relative change this probe made to any named curve.

    v1.1.30. THIS IS NOT THE SAME QUESTION AS THE TWO BIAS ONE, AND STEP 29
    CONFLATED THEM. `pair` measures the CHANNEL part of the gate
    capacitance, which is the top of the gate sweep minus the bottom. A
    parameter that lifts a whole curve by a constant -- cgso, cgdo, cgbo,
    cfs, the overlap and fringe family -- changes that difference by exactly
    nothing, because the constant cancels in the subtraction. Step 29 called
    those parameters dead and threw them out of its fit. They are the
    strongest capacitance parameters on this card: probing cgbo alone moved
    the capacitance error from 0.0405 to 0.1504.

    So a parameter is worth fitting if it moves a CURVE, and it is a
    candidate for the two bias defect if it moves the two biases in opposite
    directions. Two tests, two answers, and a parameter can pass one and
    fail the other.
    """
    import numpy as np
    worst = 0.0
    for n in names:
        a = (base_curves or {}).get(n)
        b = (probe_curves or {}).get(n)
        if a is None or b is None:
            continue
        ya = np.asarray(a[1], float)
        yb = np.asarray(b[1], float)
        if ya.shape != yb.shape or ya.size == 0:
            continue
        sc = float(np.max(np.abs(ya)))
        if sc <= 0.0:
            continue
        keep = np.abs(ya) > sc * 1.0e-9
        if not keep.any():
            continue
        rel = np.abs(yb[keep] - ya[keep]) / np.abs(ya[keep])
        worst = max(worst, float(rel.max()))
    return worst


def probe_row(name, base_curves, probe_curves, lo_tag="0.05", hi_tag="0.60",
              dead_frac=0.002, curve_names=None, curve_floor=0.002):
    """One row of the map: what this parameter did to each drain bias, and
    separately whether it moved any curve at all."""
    b_lo, b_hi = pair(base_curves, lo_tag, hi_tag)
    p_lo, p_hi = pair(probe_curves, lo_tag, hi_tag)
    d_lo = ((p_lo - b_lo) / b_lo) if (b_lo and p_lo is not None) else None
    d_hi = ((p_hi - b_hi) / b_hi) if (b_hi and p_hi is not None) else None
    row = {"name": name, "lo": p_lo, "hi": p_hi,
           "d_lo": d_lo, "d_hi": d_hi,
           "verdict": verdict(d_lo, d_hi, dead_frac=dead_frac)}
    if curve_names:
        cm = curve_move(base_curves, probe_curves, curve_names)
        row["curve_move"] = cm
        row["acts"] = bool(cm >= float(curve_floor))
    else:
        row["curve_move"] = None
        row["acts"] = row["verdict"] not in ("dead", "not measured")
    return row



def _wrapnames(names, indent, width=58):
    if not names:
        return [indent + "none"]
    out, line = [], ""
    for n in names:
        if not line:
            line = n
        elif len(line) + 2 + len(n) <= width:
            line += ", " + n
        else:
            out.append(indent + line + ",")
            line = n
    out.append(indent + line)
    return out


def format_map(rows, want=None, title=None):
    L = [title or "    what each knob does to the two drain biases:", ""]
    if want:
        L.append("      the card needs %+.1f per cent at Vd = 0.05 V and "
                 "%+.1f per cent" % (100.0 * want.get("lo", 0.0),
                                     100.0 * want.get("hi", 0.0)))
        L.append("      at Vd = 0.60 V, so the knob it needs is one whose two")
        L.append("      columns below have OPPOSITE signs.")
        L.append("")
    L.append("      %-13s %11s %11s %10s  %s"
             % ("parameter", "Vd=0.05 %", "Vd=0.60 %", "any curve",
                "the two bias test"))
    L.append("      " + "-" * 72)
    for r in rows:
        cm = r.get("curve_move")
        cms = "-" if cm is None else "%9.3f%%" % (100.0 * cm)
        if r.get("d_lo") is None or r.get("d_hi") is None:
            L.append("      %-13s %11s %11s %10s  %s"
                     % (r["name"], "-", "-", cms, r.get("verdict")))
            continue
        L.append("      %-13s %+11.3f %+11.3f %10s  %s"
                 % (r["name"], 100.0 * r["d_lo"], 100.0 * r["d_hi"], cms,
                    r["verdict"]))
    opp = [r["name"] for r in rows if r.get("verdict") == "opposite"]
    hi = [r["name"] for r in rows if r.get("verdict") == "high bias only"]
    lo = [r["name"] for r in rows if r.get("verdict") == "low bias only"]
    dead = [r["name"] for r in rows if r.get("verdict") == "dead"]
    L.append("")
    for lab, names in (("opposite signs", opp), ("high bias only", hi),
                       ("low bias only", lo), ("nothing at all", dead)):
        _lines = _wrapnames(names, " " * 23)
        L.append("      %-15s: %s" % (lab, _lines[0].strip()))
        for extra in _lines[1:]:
            L.append(extra)
    acts = [r["name"] for r in rows if r.get("acts")]
    noact = [r["name"] for r in rows
             if r.get("curve_move") is not None and not r.get("acts")]
    if acts or noact:
        L.append("")
        L.append("      and separately, the question that decides what goes")
        L.append("      into a fit, which is whether a CURVE moved at all:")
        for lab, names in (("moves a curve", acts),
                           ("moves nothing", noact)):
            _lines = _wrapnames(names, " " * 25)
            L.append("        %-13s: %s" % (lab, _lines[0].strip()))
            for extra in _lines[1:]:
                L.append(extra)
    return "\n".join(L)
