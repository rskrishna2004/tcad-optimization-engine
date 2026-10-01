"""l5_opt.pair_solve -- two knobs at once, chosen by their DIRECTIONS.
(TCADOpt v1.1.15 -- new)

WHY THIS FILE EXISTS
--------------------
For three steps this project has been stuck on one number. The gate
capacitance of the model is 13.3% BELOW the device on the Vd = 50 mV sweep
and 9.4% ABOVE it on the Vd = 0.6 V sweep: a 22.7-point SPLIT. Every
parameter with real capacitance leverage moves both curves the same way --
DELTAWCV by 2.75 and 2.90, CFS and CGSO and CGDO by 1.51 each -- so each of
them slides the pair up or down and leaves the gap between them exactly
where it was.

A search cannot fix this by trying harder. It is a statement about
DIRECTIONS, and the fix is arithmetic that fits on a postcard.

Write the two readings we want to drive to zero as a vector y (here: the
signed plateau error of each capacitance sweep, in percent). Each parameter
p has a sensitivity column

    s_p = ( dy1/dp , dy2/dp )

measured, not assumed -- l6_verify/response.map_signed produces exactly
this. A single parameter can only move y ALONG its own column. Two
parameters p and q can reach anywhere in the plane, and the amount they can
reach depends on the ANGLE between their columns:

    two columns pointing the same way  -> one knob wearing two hats
    two columns at a right angle       -> full control of both readings

So: measure every candidate's column, then look at every PAIR, solve the
2x2 system

    [ s_p , s_q ] . (dp, dq) = -y

and keep the pairs whose answer (a) exists, (b) lands inside the boxes, and
(c) is not the numerical noise of two nearly-parallel columns. The
conditioning number to read is |sin(theta)|, the sine of the angle between
the columns: 1.0 is perpendicular and free, 0.01 means the pair is buying
its solution with two enormous and opposite parameter moves that will fall
apart the moment anything else changes.

This module does not fit anything. It proposes a starting point, with the
arithmetic shown, and the gate in l6_verify/gate.py decides whether the
measured result was worth keeping -- as always.

$Id: pair_solve.py, 2026/09/27 v1.1.15 $
"""
import itertools

import numpy as np


def columns(S, obs, names=None):
    """{param: column} -> (names, 2 x N matrix) in the order `obs` gives."""
    names = list(names if names is not None else sorted(S))
    keep, cols = [], []
    for n in names:
        row = S.get(n) or {}
        c = [row.get(o) for o in obs]
        if any(v is None or not np.isfinite(v) for v in c):
            continue
        c = np.asarray(c, float)
        if not np.any(np.abs(c) > 0):
            continue
        keep.append(n)
        cols.append(c)
    if not cols:
        return [], np.zeros((len(obs), 0))
    return keep, np.array(cols).T


def sin_angle(a, b):
    """|sin| of the angle between two 2-vectors: 1 = perpendicular."""
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na <= 0 or nb <= 0:
        return 0.0
    det = float(a[0] * b[1] - a[1] * b[0])
    return abs(det) / (na * nb)


def solve_single(name, col, y):
    """The least-squares step for ONE knob, and what it leaves behind."""
    col = np.asarray(col, float)
    d = -float(col.dot(y)) / float(col.dot(col))
    left = np.asarray(y, float) + d * col
    return {"kind": "single", "names": [name], "steps": [d],
            "residual": left, "norm": float(np.linalg.norm(left)),
            "sin": 1.0}


def solve_pair(na, ca, nb, cb, y):
    """The exact two-knob step, or None when the columns are parallel."""
    A = np.array([ca, cb], float).T
    det = float(np.linalg.det(A))
    if abs(det) <= 0.0:
        return None
    try:
        d = np.linalg.solve(A, -np.asarray(y, float))
    except np.linalg.LinAlgError:
        return None
    if not np.all(np.isfinite(d)):
        return None
    left = np.asarray(y, float) + A.dot(d)
    return {"kind": "pair", "names": [na, nb], "steps": [float(d[0]),
                                                         float(d[1])],
            "residual": left, "norm": float(np.linalg.norm(left)),
            "sin": sin_angle(ca, cb)}


def _clip(base, name, step, boxes):
    lo, hi = (boxes or {}).get(name, (None, None))
    v = float(base.get(name, 0.0)) + float(step)
    if lo is not None:
        v = max(v, float(lo))
    if hi is not None:
        v = min(v, float(hi))
    return v


def propose(S, obs, y, base, boxes=None, names=None, sin_min=0.05,
            max_pairs=8):
    """Rank every single knob and every pair by what it can do to y.

    S     : {param: {observable: d(observable)/d(param)}} -- MEASURED
    obs   : the observables, in order
    y     : their current signed values (the thing to drive to zero)
    base  : the card, for turning a step into a landing value
    boxes : {param: (lo, hi)} -- the declared range of each parameter
    sin_min : pairs flatter than this are reported but flagged, because
              their answer is two large opposite moves that cancel

    Returns a list of proposals, best first, each with the landing values
    already clipped to the boxes and the residual that clipping leaves.
    """
    y = np.asarray(y, float)
    keep, M = columns(S, obs, names)
    out = []
    for k, n in enumerate(keep):
        p = solve_single(n, M[:, k], y)
        out.append(p)
    for (ka, na), (kb, nb) in itertools.combinations(list(enumerate(keep)),
                                                     2):
        p = solve_pair(na, M[:, ka], nb, M[:, kb], y)
        if p is not None:
            out.append(p)
    for p in out:
        lands, clipped = {}, False
        for n, d in zip(p["names"], p["steps"]):
            v = _clip(base, n, d, boxes)
            lands[n] = v
            want = float(base.get(n, 0.0)) + float(d)
            if abs(v - want) > 1e-12 * max(abs(want), 1e-30):
                clipped = True
        p["lands"] = lands
        p["clipped"] = clipped
        # what the CLIPPED move actually predicts
        cols = []
        for n in p["names"]:
            row = S.get(n) or {}
            cols.append([row.get(o, 0.0) for o in obs])
        A = np.array(cols, float).T
        dd = np.array([lands[n] - float(base.get(n, 0.0))
                       for n in p["names"]], float)
        left = y + A.dot(dd)
        p["predicted"] = left
        p["predicted_norm"] = float(np.linalg.norm(left))
        p["weak"] = bool(p["kind"] == "pair" and p["sin"] < sin_min)
    out.sort(key=lambda p: (p["predicted_norm"], -p["sin"]))
    best_single = [p for p in out if p["kind"] == "single"][:3]
    pairs = [p for p in out if p["kind"] == "pair"][:max_pairs]
    return {"all": out, "singles": best_single, "pairs": pairs,
            "y": [float(v) for v in y], "obs": list(obs)}


def format_proposals(rep, units="%", title=None):
    obs = rep["obs"]
    L = ["  %s" % (title or "what one knob can do, and what two can do"),
         "",
         "  the two readings to drive to zero, as they stand:"]
    for o, v in zip(obs, rep["y"]):
        L.append("     %-24s %+12.6g%s" % (o, v, units))
    L.append("")
    L.append("  ONE KNOB AT A TIME -- the best each can do on its own")
    L.append("  %-14s %-14s %s" % ("param", "move to", "what is left"))
    L.append("  " + "-" * 62)
    for p in rep["singles"]:
        n = p["names"][0]
        L.append("  %-14s %-14.6g %s"
                 % (n, p["lands"][n],
                    "  ".join("%+.6g%s" % (v, units)
                              for v in p["predicted"])))
    L.append("")
    L.append("  TWO KNOBS TOGETHER -- ranked by what is left afterwards")
    L.append("  %-14s %-14s %-7s %-13s %-13s %s"
             % ("param A", "param B", "|sin|", "A -> ", "B -> ",
                "what is left"))
    L.append("  " + "-" * 90)
    for p in rep["pairs"]:
        a, b = p["names"]
        tail = "  ".join("%+.6g%s" % (v, units) for v in p["predicted"])
        if p["weak"]:
            tail += "   (nearly parallel: distrust)"
        if p["clipped"]:
            tail += "   (clipped to the box)"
        L.append("  %-14s %-14s %-7.3f %-13.6g %-13.6g %s"
                 % (a, b, p["sin"], p["lands"][a], p["lands"][b], tail))
    L.append("")
    L.append("  |sin| is the angle between the two parameters' effects:")
    L.append("  1.000 means they are independent and the answer is honest;")
    L.append("  a small value means the pair is buying its answer with two")
    L.append("  large opposite moves that will not survive the next stage.")
    L.append("  Every line here is a PREDICTION from measured slopes. The")
    L.append("  next stage runs it and the gate decides.")
    return "\n".join(L)
