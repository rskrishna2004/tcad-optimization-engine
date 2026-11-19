"""l5_opt.price -- what a parameter BUYS and what it COSTS, one row each.

WHY THIS EXISTS
---------------
Some parameters in a compact model are shared: the same number is read by
the current equations and by the charge equations. BSIM-CMG's KSATIV_a is
read on bsimcmg_body.include line 1901 for the drain current and on line
2089 for the charge, and MEXP_a on 1916 and 2103. A charge defect that only
a shared parameter can reach therefore cannot be fixed for free, and the
only honest thing to do is to find out what it costs.

Step 30 tried to find out with a single joint fit and a gate on the end. The
fit moved the pair, the drain current error rose 3.31 per cent, the gate
refused the card, and the step was left with one number and no idea what was
on either side of it. One measurement is not a trade; it is an anecdote.

A price list is the alternative, and it is both cheaper and more useful. One
parameter is set to one value, everything else is held, one simulation is
run, and the row records what the move bought and what it cost. Six rows
cost about a minute and they show the whole shape of the trade, including
the part where it stops being worth it.

WHAT A ROW MEANS, AND WHAT IT DOES NOT
---------------------------------------
A row is a measurement of ONE knob moved ALONE. It is not a prediction of
what the knob is worth inside a fit, because a fit lets everything else
re-balance around it. That is why `scan` is step one and the caller is
expected to follow the pick with a repair fit: the row says where to look,
the fit says what is actually there.

The pick rule is deliberately dull and is stated before the ladder runs:
take the row that leaves the tracked defect smallest, out of the rows that
did not break the caller's guard. A price list that quietly drops its worst
row is not a price list.
"""
from __future__ import division

VERSION = "1.1.31"


def ladder(value, factors=(1.5, 2.0, 2.6, 3.2, 4.0), box=None):
    """Multiples of a parameter's present value that lie inside its box."""
    out = []
    for f in factors:
        v = float(value) * float(f)
        if box is not None:
            lo, hi = float(box[0]), float(box[1])
            if v < lo or v > hi:
                continue
        if any(abs(v - u) <= abs(v) * 1.0e-12 for u in out):
            continue
        out.append(v)
    return out


def absolute(values, present, box=None):
    """Absolute values that lie inside the box and are not where we are."""
    out = []
    for v in values:
        v = float(v)
        if box is not None and (v < float(box[0]) or v > float(box[1])):
            continue
        if abs(v - float(present)) <= abs(float(present)) * 1.0e-12:
            continue
        out.append(v)
    return out


def scan(measure, card, plan, tag="price", stop=None, log=None):
    """One row per (knob, value), each one simulation.

    `measure(card, tag) -> dict or None` is the caller's own measurement, so
    this module never needs to know what a defect is. `plan` is a list of
    (knob, value). `stop()` returning True ends the scan early, which is how
    a time budget is enforced without this module knowing about clocks.
    """
    rows = []
    for i, (knob, value) in enumerate(plan):
        if stop is not None and stop():
            if log:
                log("    (the scan stopped early: %d of %d rows done)"
                    % (i, len(plan)))
            break
        c = dict(card)
        c[knob] = value
        m = measure(c, "%s%d" % (tag, i))
        if m is None:
            rows.append({"knob": knob, "value": value, "ok": False})
            continue
        row = {"knob": knob, "value": value, "ok": True}
        row.update(m)
        rows.append(row)
    return rows


def pick(rows, by="gap_sum", clean="guard", smallest=True, cap=None):
    """The best row by one key, out of the rows that are affordable.

    A row is affordable when it broke no guard and when its cost, if `cap`
    is given as (key, limit), is at or under the limit. Both halves matter.
    The guard catches a row that wrecked a curve; the cap catches a row
    whose cost is so far outside the budget that no repair fit inside the
    declared boxes is going to bring it back, and spending twenty minutes
    discovering that is twenty minutes not spent on a row that could work.

    Returns (row, reason). `reason` is an empty string when the preferred
    pool was used and a short sentence when it was empty and the pick had
    to come from the whole list anyway. A price list that quietly drops its
    worst row is not a price list, so the fall back still returns a row and
    still says what happened.
    """
    good = [r for r in rows if r.get("ok") and r.get(by) is not None]
    if not good:
        return None, ""
    pool = [r for r in good if not r.get(clean)]
    why = "" if pool else "every row broke the guard"
    if cap is not None:
        ck, lim = cap[0], float(cap[1])
        capped = [r for r in (pool or good)
                  if r.get(ck) is None or float(r[ck]) <= lim]
        if capped:
            pool = capped
        elif pool:
            why = "no row was inside the cost cap"
            pool = pool
        else:
            why = "every row broke the guard and the cost cap"
    pool = pool or good
    best = (min if smallest else max)(pool, key=lambda r: r[by])
    return best, why


def format_price(rows, base=None, cols=None, title=None):
    """The price list as a table. `cols` is a list of (header, key, fmt)."""
    cols = cols or [("knob", "knob", "%-8s"), ("value", "value", "%9.4f"),
                    ("defect", "gap_sum", "%9.4f"),
                    ("cost", "iv_rise", "%+8.2f%%")]
    L = [title or "    the price list:", ""]

    def _w(fmt):
        try:
            return len(fmt % ("x" if ("s" in fmt and "f" not in fmt) else 0.0))
        except Exception:
            return 9

    head = "    " + " ".join(
        (("%-" + str(_w(c[2])) + "s") if c[2].startswith("%-")
         else ("%" + str(_w(c[2])) + "s")) % c[0] for c in cols)
    L.append(head)
    L.append("    " + "-" * max(0, len(head) - 4))
    if base is not None:
        cells = []
        for name, key, fmt in cols:
            v = base.get(key)
            if v is None:
                cells.append("%-8s" % "start" if fmt.startswith("%-")
                             else "%9s" % "-")
            else:
                cells.append(fmt % v)
        L.append(("    " + " ".join(cells)).rstrip())
    for r in rows:
        if not r.get("ok"):
            L.append("    %-8s %9.4f   the simulator refused this card"
                     % (r.get("knob"), r.get("value") or 0.0))
            continue
        cells = []
        for name, key, fmt in cols:
            v = r.get(key)
            cells.append(("%9s" % "-") if v is None else (fmt % v))
        L.append("    " + " ".join(cells))
    return "\n".join(x.rstrip() for x in L)
