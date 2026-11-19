# -*- coding: utf-8 -*-
"""l4_knowledge.census -- know every parameter a compact model has, and test
them all.

v1.1.26.  WHY THIS MODULE EXISTS
---------------------------------
Every extraction this project ran until Step 25 worked from a parameter list
that a human wrote down, taken from the manual's extraction chapter and from
reading the source. That list had 65 names on it. BSIM-CMG 112.1.0 declares
1867. The gap between those two numbers is not a detail: a capability the
model has and the list does not mention is invisible to the whole flow, and
no amount of fitting the 65 will ever find it.

So this module takes the model's own source as the authority. It carries:

  * the CENSUS, every parameter declaration with its macro, default, unit,
    declared bounds, description, and every place in the source its value is
    read, together with the mode switches guarding those places
  * the PROBE PLAN, for each parameter the exact values to try and the stated
    reason each value was chosen
  * CLASSIFY, which turns one measured probe into a verdict: does this
    parameter move the current, the capacitance, both, or nothing

THE THREE CLASSES, AND WHY ONLY ONE OF THEM NEEDS THE SIMULATOR
----------------------------------------------------------------
BINNING TERMS. The model builds a binned parameter with one macro:

    param_i = r_term + Inv_L*l_term + Inv_NFIN*n_term + Inv_LNFIN*p_term
                     + Inv_W*w_term + Inv_WL*wl_term

On a single fixed geometry the five Inv_ quantities are constants, so every
binning term adds a constant multiple of itself to the same number the base
parameter sets. It is an exact linear reparameterisation of the base. It can
move the curves; it cannot reach anything the base cannot reach.

TEMPERATURE TERMS. They all multiply delTemp, the simulation temperature
minus TNOM. When the two are equal, every one of them multiplies zero.

Both of those are proofs about the source, not assumptions, and both are
worth confirming on the simulator with a random sample, which is what
`control_sample` is for.

BASE PARAMETERS AND MODE SWITCHES get no shortcut. Every one is moved on its
own and measured.
"""
import json
import math
import os
import random

VERSION = "1.1.26"

CLASS_DEAD = "DEAD"
CLASS_IV = "CURRENT"
CLASS_CV = "CAPACITANCE"
CLASS_BOTH = "BOTH"
CLASS_REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
#  loading
# ---------------------------------------------------------------------------
def load_plan(path):
    """Read the probe plan produced from the model source.

    The plan is data, not code: it is a parse of the released parameter file
    and it is shipped beside the run so that what was tested can be checked
    line by line afterwards.
    """
    with open(path) as fh:
        d = json.load(fh)
    for key in ("plan", "switches", "counts"):
        if key not in d:
            raise ValueError("the probe plan has no %r section" % key)
    return d


def plan_order(plan, interleave=True):
    """The order probes are run in.

    With `interleave`, EVERY parameter gets its first probe before any
    parameter gets its second. If the run is cut short by its time budget,
    what survives is still complete coverage at one value per parameter
    rather than a thorough test of the alphabet up to the letter G.
    """
    names = sorted(plan)
    out = []
    if not interleave:
        for n in names:
            for i, p in enumerate(plan[n]["probes"]):
                out.append((n, i))
        return out
    depth = max([len(plan[n]["probes"]) for n in names] or [0])
    for i in range(depth):
        for n in names:
            if i < len(plan[n]["probes"]):
                out.append((n, i))
    return out


def probe_values(entry):
    """The values this parameter will be set to, with the reason for each."""
    return [(p["value"], p.get("why", "")) for p in entry.get("probes", [])]


# ---------------------------------------------------------------------------
#  measuring one probe
# ---------------------------------------------------------------------------
def curve_delta(base, trial, names, floor_frac=1.0e-9):
    """The largest relative change between two sets of curves.

    Points where the reference curve is at the numerical floor of its own
    sweep carry no relative change and are left out, for the same reason an
    IdVd sweep's first point carries no relative error: the value there is
    zero by construction.
    """
    worst, where = 0.0, None
    for n in names:
        a = base.get(n)
        b = trial.get(n)
        if a is None or b is None:
            continue
        ya = _as_y(a)
        yb = _as_y(b)
        if ya is None or yb is None or ya.shape != yb.shape:
            continue
        scale = float(max(abs(ya.max()), abs(ya.min()))) if ya.size else 0.0
        if scale <= 0.0:
            continue
        keep = abs(ya) > scale * floor_frac
        if not keep.any():
            continue
        rel = abs(yb[keep] - ya[keep]) / abs(ya[keep])
        m = float(rel.max())
        if m > worst:
            worst, where = m, n
    return worst, where


def _as_y(c):
    import numpy as np
    if c is None:
        return None
    if isinstance(c, (tuple, list)) and len(c) >= 2:
        return np.asarray(c[1], float)
    return np.asarray(c, float)


def classify(d_iv, d_cv, dead_tol, cv_min, iv_free, ok=True):
    """One probe, one verdict."""
    if not ok:
        return CLASS_REJECTED
    iv_live = d_iv is not None and d_iv > dead_tol
    cv_live = d_cv is not None and d_cv > dead_tol
    if not iv_live and not cv_live:
        return CLASS_DEAD
    if cv_live and d_cv >= cv_min and (d_iv is None or d_iv < iv_free):
        return CLASS_CV
    if iv_live and not cv_live:
        return CLASS_IV
    if cv_live and not iv_live:
        return CLASS_CV
    return CLASS_BOTH


def change_vector(base, trial, names, floor_frac=1.0e-9):
    """The change a card made, as one vector over every curve point.

    Each curve is divided by its own scale first, so a capacitance in
    attofarad and a current in amps per micron carry the same weight and the
    direction of the vector means something.
    """
    import numpy as np
    out = []
    for n in sorted(names):
        a = base.get(n)
        b = trial.get(n)
        if a is None or b is None:
            continue
        ya, yb = _as_y(a), _as_y(b)
        if ya is None or yb is None or ya.shape != yb.shape:
            continue
        scale = float(np.max(np.abs(ya))) if ya.size else 0.0
        if scale <= 0.0:
            continue
        out.append((yb - ya) / scale)
    if not out:
        return None
    return np.concatenate(out)


def parallel_change(base, a_curves, b_curves, names):
    """Did two different cards change the curves in the SAME direction?

    This is how a binning term is checked without having to know the model's
    internal Inv_L, Inv_NFIN and Inv_W constants. A binning term is claimed
    to be its base parameter under another name, which means the change it
    makes to the curves must point the same way as the change the base
    parameter makes, differing only in how far. The cosine of the angle
    between the two change vectors tests exactly that, and it needs no
    knowledge of the scale factor at all.

    Returns (cosine, magnitude_ratio) or (None, None) if either card did
    not move anything.
    """
    import numpy as np
    va = change_vector(base, a_curves, names)
    vb = change_vector(base, b_curves, names)
    if va is None or vb is None or va.shape != vb.shape:
        return None, None
    na, nb = float(np.linalg.norm(va)), float(np.linalg.norm(vb))
    if na <= 0.0 or nb <= 0.0:
        return None, None
    return float(np.dot(va, vb) / (na * nb)), float(na / nb)


#  The binning scale factors, read out of bsimcmg_body.include. The 1e-6
#  and 1e-12 factors are NOT decoration: they mean an l-term is in units of
#  the parameter times a MICRON, not times a metre.
#
#      Inv_L     = 1.0e-6  / Leff1
#      Inv_NFIN  = 1.0     / nfin
#      Inv_LNFIN = 1.0e-6  / (Leff1 * nfin)
#      Inv_W     = 1.0e-6  / WGAAeff1
#      Inv_WL    = 1.0e-12 / (WGAAeff1 * Leff1)
#
#  Step 26's control test for the binning family used 1/L instead of
#  1e-6/L, so the binning term it set was a MILLION times too small, the
#  curves barely moved, and the direction test was comparing a real change
#  against pure round off. Thirteen of thirty came back "a different
#  direction" and every one of them was this bug, which the magnitude
#  column showed at the time: the ratios were 1e-4 down to 1e-10.
def binning_scales(leff_m, nfin, w_m):
    """The five Inv_ constants for one geometry, exactly as the model
    computes them."""
    out = {"l": 1.0e-6 / float(leff_m), "n": 1.0 / float(nfin),
           "p": 1.0e-6 / (float(leff_m) * float(nfin))}
    if w_m and float(w_m) > 0.0:
        out["w"] = 1.0e-6 / float(w_m)
        out["p2"] = 1.0e-12 / (float(w_m) * float(leff_m))
    else:
        out["w"] = 0.0
        out["p2"] = 0.0
    return out


def binning_prefix(name, known):
    """Split a binning term into its prefix and its base parameter."""
    for pre in ("p2", "l", "n", "p", "w"):
        if name.startswith(pre) and name[len(pre):] in known:
            return pre, name[len(pre):]
    return None, None


def binning_equivalent_value(prefix, scales, base_value, fraction=0.10):
    """The value to give a binning term so that it shifts its base by
    `fraction` of the base's own size, and the matching shifted base value.

    Returns (term_value, shifted_base) or (None, None) when the prefix has
    no scale on this geometry, which is what Inv_W = 0 means for a device
    the model does not give a width to.
    """
    inv = (scales or {}).get(prefix)
    if not inv:
        return None, None
    shift = abs(float(base_value)) * float(fraction)
    if shift <= 0.0:
        return None, None
    return shift / inv, float(base_value) + shift


def control_sample(names, n, seed=0):
    """A reproducible random sample, for confirming a proof on the simulator."""
    rnd = random.Random(seed)
    names = sorted(names)
    if n >= len(names):
        return list(names)
    return sorted(rnd.sample(names, int(n)))


# ---------------------------------------------------------------------------
#  the defects this hunt is aimed at
# ---------------------------------------------------------------------------
def channel_parts(curves, vd_tag, terms=("cgd", "cgs", "cgb")):
    """Split each gate row capacitance into its fixed part and its channel
    part, using the curve alone.

    The capacitance measured at the top of the gate sweep has two pieces: a
    piece from the gate overlapping the source and drain and from the
    fringing field, which does not change with gate voltage, and a piece from
    charge in the channel. Taking the value at the bottom of the sweep, where
    the channel is empty, and subtracting it leaves the channel piece.

    Returns {term: (value_at_top, channel_part)} and the drain share.
    """
    import numpy as np
    out = {}
    tot = 0.0
    for t in terms:
        c = curves.get("nsfet_n_CV_%s#%s" % (vd_tag, t))
        if c is None:
            continue
        x = np.asarray(c[0], float)
        y = np.asarray(c[1], float)
        if x.size < 2:
            continue
        o = np.argsort(x)
        x, y = x[o], y[o]
        top, bot = float(y[-1]), float(y[0])
        out[t] = (top, top - bot)
        tot += top - bot
    share = None
    if "cgd" in out and abs(tot) > 0.0:
        share = 100.0 * out["cgd"][1] / tot
    return out, share


def defect_metrics(curves):
    """The four numbers this step is hunting, all computed from the curves."""
    m = {}
    for tag, key in (("0.05", "05"), ("0.60", "60")):
        parts, share = channel_parts(curves, tag)
        if share is not None:
            m["share" + key] = share
        if "cgd" in parts:
            m["cgd_ch" + key] = parts["cgd"][1]
        if "cgb" in parts:
            m["cgb_slope" + key] = parts["cgb"][1]
        if "cgs" in parts:
            m["cgs_ch" + key] = parts["cgs"][1]
    return m


def defect_gain(before, after, target, min_gap_frac=1.0e-3):
    """How much closer to the device did this probe get, as a fraction of the
    gap. 1.0 means it closed the gap exactly, 0 means it did nothing, a
    negative number means it went the wrong way.

    A defect whose gap is already a rounding error has no meaningful
    fraction: dividing by it turns noise into a headline. So a gap smaller
    than `min_gap_frac` of the quantity itself is reported as closed rather
    than inflated.
    """
    out = {}
    for k, want in (target or {}).items():
        if k not in before or k not in after:
            continue
        gap = want - before[k]
        scale = max(abs(want), abs(before[k]), 1.0e-300)
        if abs(gap) <= abs(scale) * float(min_gap_frac):
            continue
        out[k] = (after[k] - before[k]) / gap
    return out


# ---------------------------------------------------------------------------
#  reporting
# ---------------------------------------------------------------------------
def format_census(counts, title=None):
    L = [title or "    the complete parameter census of this model:"]
    L.append("      %-44s %6d" % ("all parameter declarations", counts["all"]))
    L.append("      %-44s %6d" % ("  binning terms, the l n p w p2 family",
                                  counts["binning"]))
    L.append("      %-44s %6d" % ("  temperature coefficients",
                                  counts["temp"]))
    L.append("      %-44s %6d" % ("  mode switches", counts["switch"]))
    L.append("      %-44s %6d" % ("  base parameters, everything else",
                                  counts["base"]))
    L.append("      %-44s %6d" % ("of the base parameters, on our card",
                                  counts["on_card"]))
    L.append("      %-44s %6d" % ("of the base parameters, never tried",
                                  counts["base"] - counts["on_card"]))
    return "\n".join(L)


def format_hits(rows, title=None, top=40):
    """rows: list of dicts with name, value, why, d_iv, d_cv, verdict, gains"""
    L = [title or "    parameters that moved a capacitance:"]
    L.append("      %-16s %-12s %-10s %-10s %-12s %s"
             % ("parameter", "tried at", "current", "capacitance", "verdict",
                "closes the gap by"))
    for r in rows[:top]:
        g = r.get("gains") or {}
        best = ""
        if g:
            k = max(g, key=lambda z: abs(g[z]))
            best = "%s %+.1f %%" % (k, 100.0 * g[k])
        L.append("      %-16s %-12.4g %-10s %-10s %-12s %s"
                 % (r["name"], r["value"],
                    ("%.2e" % r["d_iv"]) if r["d_iv"] is not None else "-",
                    ("%.2e" % r["d_cv"]) if r["d_cv"] is not None else "-",
                    r["verdict"], best))
    if len(rows) > top:
        L.append("      ... and %d more, all in the results file"
                 % (len(rows) - top))
    return "\n".join(L)
