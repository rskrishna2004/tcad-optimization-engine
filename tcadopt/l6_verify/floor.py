# -*- coding: utf-8 -*-
"""l6_verify.floor -- how much of a curve's error can actually be removed.

WHY THIS MODULE EXISTS
----------------------
An optimiser minimises what you give it. If part of what you give it cannot
be reduced by any setting of any parameter, the optimiser still spends its
effort there, and the number it reports still carries that part. You then look
at the number, see it barely moving, and conclude the fit is stuck.

This project spent months in exactly that position. The sixteen-curve
capacitance error on the frozen card is 0.048542. Of the sum of squares behind
it, 62 per cent is Cgb -- and the model's Cgb, on this card, is a CONSTANT:

    bsimcmg_body.include 3067   Qeg = cgbox * devsign * V(e, ge);
    bsimcmg_body.include 3069   if (bulkmod != 0) begin ... end

The bias dependent part of the gate to substrate charge lives inside that
`bulkmod != 0`, and this card is a silicon on insulator card with
`bulkmod = 0`, so the whole of the model's Cgb is `cgbox`, which contains no
bias term at all. Line 932 makes it

    cgbox = (cgbo * nf * ngcon + (cgbn + cgbw * WGAAeff) * NFINtotal) * Lg

and with our card that is 1.44825445e-10 * 1.2e-8 = 1.737905e-18 F. The
simulator returns 1.7379 aF at every one of the 182 bias points of both
sweeps, which is the arithmetic coming back exactly.

The device's Cgb is not constant. It falls from 1.9299 aF to 1.4061 aF across
the gate sweep. So the best any card can do is put one constant through a
sloping line, and the error that remains is not a fitting failure, it is the
shape of the model. For the relative metric this project uses, the best
constant has a closed form -- minimise sum((c - d_i)/d_i)^2 and

    c = sum(1/d_i) / sum(1/d_i^2)

which gives 1.7434 aF at the low drain bias. Our cgbo already sits at 1.7379.
So the Cgb term was ALREADY at its own optimum, and 100 per cent of its
residual is irreducible, and it was 62 per cent of the objective.

The largest Cgb error anywhere is 0.332 aF, against a gate capacitance of
59.4 aF. Half of one per cent of the quantity being modelled, carrying
two thirds of the score.

WHAT THIS MODULE DOES
---------------------
  * `flat` says, from the simulated curve, whether the model made this curve
    a constant.
  * `constant_floor` gives the best constant and the residual it leaves, in
    closed form, for a curve the model makes constant.
  * `split` takes the per curve residuals and the measured floors and reports
    the objective in two halves: the part a fit can still reach, and the part
    it cannot.

Nothing here throws a curve away. A curve at its floor is still measured,
still printed and still reported -- it just stops being allowed to drown out
the curves that can still be improved.
"""
from __future__ import print_function

VERSION = "1.1.31"

import numpy as np


def _xy(curve):
    x = np.asarray(curve[0], float)
    y = np.asarray(curve[1], float)
    o = np.argsort(x)
    return x[o], y[o]


def flat(curve, rel_tol=1.0e-9):
    """Did the model make this curve a constant?

    Returns (is_flat, value, relative_spread).
    """
    if curve is None:
        return False, None, None
    _x, y = _xy(curve)
    if y.size == 0:
        return False, None, None
    lo, hi = float(np.min(y)), float(np.max(y))
    scale = max(abs(lo), abs(hi), 1.0e-300)
    spread = (hi - lo) / scale
    return bool(spread <= rel_tol), float(np.mean(y)), float(spread)


def rel_ss(model_y, dev_y, floor_frac=1.0e-9):
    """Sum of squares of the relative error, the way this project scores."""
    m = np.asarray(model_y, float)
    d = np.asarray(dev_y, float)
    if m.shape != d.shape or d.size == 0:
        return None, 0
    scale = float(np.max(np.abs(d)))
    keep = np.abs(d) > max(scale * floor_frac, 1.0e-300)
    if keep.sum() == 0:
        return None, 0
    r = (m[keep] - d[keep]) / d[keep]
    return float(np.dot(r, r)), int(keep.sum())


def constant_floor(dev_y, floor_frac=1.0e-9):
    """The best single constant against this device curve, and what it leaves.

    Minimising sum(((c - d_i) / d_i)^2) over c is one line of calculus:
    the derivative is 2 * sum((c - d_i) / d_i^2), which is zero at

        c = sum(1 / d_i) / sum(1 / d_i^2)

    There is no search and no tuning constant. Returns (c, ss, n).
    """
    d = np.asarray(dev_y, float)
    scale = float(np.max(np.abs(d))) if d.size else 0.0
    keep = np.abs(d) > max(scale * floor_frac, 1.0e-300)
    if keep.sum() == 0:
        return None, None, 0
    dd = d[keep]
    num = float(np.sum(1.0 / dd))
    den = float(np.sum(1.0 / (dd * dd)))
    if den == 0.0:
        return None, None, 0
    c = num / den
    r = (c - dd) / dd
    return float(c), float(np.dot(r, r)), int(keep.sum())


def survey(curves, targets, names, rel_tol=1.0e-9):
    """Per curve: present residual, floor if the model made it constant.

    `targets` is {name: {"v":..., "i":...}} as the rest of the engine uses it.
    Returns a list of dicts, one per name, in the order given.
    """
    rows = []
    for nm in names:
        t = targets.get(nm)
        g = (curves or {}).get(nm)
        row = {"name": nm, "ss": None, "n": 0, "floor": None,
               "flat": False, "best_const": None, "spread": None}
        if t is None or g is None:
            rows.append(row)
            continue
        ss, n = rel_ss(g[1], t["i"])
        row["ss"], row["n"] = ss, n
        isflat, _val, spread = flat(g, rel_tol=rel_tol)
        row["flat"], row["spread"] = isflat, spread
        if isflat:
            c, fs, _fn = constant_floor(t["i"])
            row["best_const"], row["floor"] = c, fs
        rows.append(row)
    return rows


def set_floor(rows, name, value):
    """Record a floor that was MEASURED by fitting rather than derived."""
    for r in rows:
        if r["name"] == name:
            r["floor"] = None if value is None else float(value)
            return True
    return False


def split(rows):
    """The objective in two halves: reachable, and capped."""
    tot = reach = cap = 0.0
    n = 0
    for r in rows:
        if r.get("ss") is None:
            continue
        tot += r["ss"]
        n += r.get("n") or 0
        f = r.get("floor")
        if f is None:
            reach += r["ss"]
        else:
            f = min(float(f), float(r["ss"]))
            cap += f
            reach += r["ss"] - f
    return {"total_ss": tot, "reachable_ss": reach, "capped_ss": cap,
            "n": n,
            "total_rms": (tot / n) ** 0.5 if n else None,
            "reachable_rms": (reach / n) ** 0.5 if n else None,
            "capped_frac": (cap / tot) if tot > 0 else None}


def weights(rows, min_reach=0.02):
    """One weight per curve: how much of its error is still reachable.

    The rule, stated before any fit runs and with no tuning constant beyond
    the cut off below: a curve's weight is the FRACTION of its own residual
    that a fit could still remove.

        w = max(0, 1 - floor / present)

    A curve already at its floor gets zero, so it stops competing for the
    optimiser's attention; a curve with no measured floor gets one. The cut
    off `min_reach` sends a curve whose reachable part is under two per cent
    of its own residual to zero as well, because at that level the weight is
    measuring noise in the floor rather than headroom.

    The weights are computed ONCE, from the frozen card, and held for the
    whole fit. Recomputing them as the fit moves would make the objective a
    moving target and nothing could be compared with anything.
    """
    out = {}
    for r in rows:
        ss, f = r.get("ss"), r.get("floor")
        if ss is None or ss <= 0.0:
            out[r["name"]] = 1.0
            continue
        if f is None:
            out[r["name"]] = 1.0
            continue
        w = 1.0 - min(float(f), float(ss)) / float(ss)
        out[r["name"]] = 0.0 if w < float(min_reach) else float(w)
    return out


def stale_weights(wts, curves, targets, names, rel_tol=1.0e-9,
                  min_reach=0.02, tol=1.0e-9):
    """Were these weights measured on the card they are about to score?

    v1.1.31. THE BUG THIS EXISTS TO MAKE IMPOSSIBLE
    ------------------------------------------------
    The weights above are built from one question per curve: how much of
    this curve's error could a fit still remove? A curve the model is
    holding at a constant while the device slopes gets zero, because no
    value of any parameter can bend a constant.

    That answer belongs to ONE CARD. Step 30 measured the weights on a card
    with bulkmod = 0, where the model's gate to substrate capacitance is one
    fixed number, so both Cgb curves correctly scored zero. It then flipped
    bulkmod to 1, which makes that capacitance a curve, and ran every fit
    that followed with the OLD weights. The two Cgb curves were 62 per cent
    of the capacitance error and the objective never mentioned them. The
    step's whole purpose was to fit them.

    Nothing in the code was wrong on its own. The weights were right for the
    card they were measured on and wrong for the card they were used on, and
    there was no way to notice except by reading two tables side by side.
    This function is that comparison, as one call:

        re-survey the curves being scored, recompute the weights the same
        way, and return every curve whose weight has moved.

    An empty list means the weights belong to this card. A non empty one
    names the curves that changed and by how much, and the caller should
    either re-weight or say out loud why it is keeping the old numbers.
    """
    rows = survey(curves, targets, names, rel_tol=rel_tol)
    now = weights(rows, min_reach=min_reach)
    out = []
    for r in rows:
        nm = r["name"]
        if nm not in (wts or {}):
            continue
        a, b = float((wts or {}).get(nm, 1.0)), float(now.get(nm, 1.0))
        if abs(a - b) > float(tol):
            out.append({"name": nm, "was": a, "now": b,
                        "flat_now": bool(r.get("flat")),
                        "reason": ("the model can now bend this curve"
                                   if b > a else
                                   "the model can no longer bend this curve")})
    return out


def format_stale(stale, title=None):
    if not stale:
        return (title or "    the weights were measured on this card:") \
            + " every curve agrees."
    L = [title or "    *** THE WEIGHTS DO NOT BELONG TO THIS CARD:"]
    for r in stale:
        L.append("      %-26s weight %.3f -> %.3f, %s"
                 % (r["name"], r["was"], r["now"], r["reason"]))
    return "\n".join(L)


def format_survey(rows, wts=None, title=None):
    L = [title or "    what each curve's error is made of:", "",
         "      %-26s %10s %9s %9s %8s %7s"
         % ("curve", "sum sq", "floor", "reachable", "capped", "weight"),
         "      " + "-" * 76]
    for r in rows:
        ss = r.get("ss")
        f = r.get("floor")
        if ss is None:
            L.append("      %-26s %10s" % (r["name"], "not measured"))
            continue
        if f is None:
            L.append("      %-26s %10.5f %9s %9.5f %7s %7.2f"
                     % (r["name"], ss, "-", ss, "-",
                        (wts or {}).get(r["name"], 1.0)))
        else:
            f = min(float(f), float(ss))
            L.append("      %-26s %10.5f %9.5f %9.5f %7.0f%% %7.2f"
                     % (r["name"], ss, f, ss - f, 100.0 * f / ss,
                        (wts or {}).get(r["name"], 1.0)))
    s = split(rows)
    L += ["      " + "-" * 76,
          "      %-26s %10.5f %9.5f %9.5f %7.0f%%"
          % ("all of the above", s["total_ss"], s["capped_ss"],
             s["reachable_ss"],
             100.0 * (s["capped_frac"] or 0.0))]
    if s["total_rms"] is not None:
        L += ["",
              "      the error as reported so far        %.6f" % s["total_rms"],
              "      the part a fit can still reach      %.6f"
              % s["reachable_rms"]]
    return "\n".join(L)
