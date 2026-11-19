# -*- coding: utf-8 -*-
"""l9_report.tradeoff -- when two things cannot both be best, show the price.

v1.1.28.  WHY THIS EXISTS
--------------------------
Step 27 added the drain share of the channel charge to the fit's objective
and it worked: the share gap went from 10.55 percentage points to 2.54, and
the drain current rose only 1.08 per cent, well inside its budget.

The gate refused it anyway, because the capacitance curve error rose by 36
per cent and the gate had been told the capacitance was not allowed to get
worse at all.

That rule was wrong, and wrong in a way worth naming. Adding a new term to
an objective ALWAYS makes the old term worse. That is what adding a term
means. A gate that demands zero rise in the old term can never accept the
new one, so the whole exercise is decided before it starts.

The honest thing is not to pick a threshold out of the air. It is to run the
fit at several weights, measure what each weight buys and what it costs, and
show the exchange rate. Then the choice is a judgement made on evidence
instead of a limit someone invented.

That is a Pareto front, and this module builds one, prints it, and finds its
knee.
"""
import math

VERSION = "1.1.28"


def dominates(a, b, keys):
    """a dominates b if it is at least as good on everything and strictly
    better on something. Lower is better on every key."""
    better = False
    for k in keys:
        if a.get(k) is None or b.get(k) is None:
            return False
        if a[k] > b[k] + 1e-15:
            return False
        if a[k] < b[k] - 1e-15:
            better = True
    return better


def pareto_front(rows, keys):
    """The rows nothing else beats on every count at once."""
    out = []
    for r in rows:
        if any(dominates(o, r, keys) for o in rows if o is not r):
            continue
        out.append(r)
    return out


def knee(rows, cost_key, gain_key):
    """The point of diminishing returns, found without a magic number.

    Sort by cost. Draw the straight line from the cheapest point to the
    dearest. The knee is the point furthest below that line: the one where
    you have already bought most of the gain and are starting to pay full
    price for the rest. This is the standard elbow construction and it has
    no tuning constant in it.
    """
    pts = [r for r in rows
           if r.get(cost_key) is not None and r.get(gain_key) is not None]
    if len(pts) < 3:
        return pts[0] if pts else None
    pts = sorted(pts, key=lambda r: r[cost_key])
    x0, y0 = pts[0][cost_key], pts[0][gain_key]
    x1, y1 = pts[-1][cost_key], pts[-1][gain_key]
    dx, dy = x1 - x0, y1 - y0
    n = math.hypot(dx, dy)
    if n <= 0.0:
        return pts[0]
    best, best_d = pts[0], -1.0
    for r in pts:
        #  perpendicular distance from the chord, signed so that only points
        #  on the good side of the line can win
        d = ((r[cost_key] - x0) * dy - (r[gain_key] - y0) * dx) / n
        if d > best_d:
            best, best_d = r, d
    return best


def format_front(rows, cols, title=None, front=None, chosen=None):
    """cols: list of (key, heading, format)."""
    L = [title or "    the exchange rate:"]
    head = "      " + "".join("%-15s" % h for _, h, _ in cols) + "  "
    L.append(head)
    L.append("      " + "-" * (len(head) - 6))
    fset = set(id(r) for r in (front or []))
    for r in rows:
        line = "      "
        for k, _, f in cols:
            v = r.get(k)
            line += ("%-15s" % (f % v)) if v is not None else "%-15s" % "-"
        mark = ""
        if id(r) in fset:
            mark += "  best available"
        if chosen is not None and r is chosen:
            mark += "  <- chosen"
        L.append(line + mark)
    return "\n".join(L)
