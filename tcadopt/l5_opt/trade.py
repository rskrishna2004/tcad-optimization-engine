"""l5_opt.trade -- price a parameter that two objectives disagree about.

WHY THIS EXISTS
---------------
Some parameters belong to one measurement. BSIM-CMG's CGBO only ever touches
the capacitance, so it can be fitted and kept and nothing else notices. Those
are easy, and `l4_knowledge.cv_scope` names them.

A few parameters belong to BOTH, and they are where a fit stops being
arithmetic and becomes a DECISION. On this device, KSATIV is the whole story:

    body.include 1901   T6 = KSATIV_a * (qis    + 2*Vtm)   -> the current's Vdsat
    body.include 2089   T6 = KSATIV_a * (qis_cv + 2*Vtm)   -> the charge's Vdsat

and Step 21 measured what it is worth on each side. On the charge, sweeping it
across its box moves the drain's share of the channel charge from 0.02% to
43.4%, with the device asking for 48.2%. On the current, it is the knee of
every Id-Vd curve.

A GATE CANNOT ANSWER THAT QUESTION. A no-regression gate asks "is the whole
objective no worse?" and the answer for a shared parameter is almost always
no, because the current half is already excellent and the capacitance half is
not. Step 21's PART 6 asked exactly that, twice, and got "+15.35%" and
"+18.53%" -- both true, both useless, because neither number says whether the
capacitance got enough in return.

So this module does not gate. It PRICES. It freezes the shared parameter at
each of a ladder of values, re-fits everything the other objective owns AT
THAT VALUE, and reports what each side ends up with. The output is a trade
curve, and a trade curve is something a person can look at and choose from --
which is what an extraction engineer actually has to do, and what no amount
of automatic gating can do for them.

THE ONE THING THAT MAKES IT HONEST
----------------------------------
At every rung the OTHER objective is re-fitted to convergence, on its own
sweeps alone. Without that, a ladder measures nothing but "the card was not
built for this value" -- the current would look terrible at every rung and
the curve would say raising the parameter is impossible when in fact the
current simply had not been given its chance to recover.
"""
import numpy as np


def trade_curve(values, refit, read, log=None, label="parameter"):
    """Freeze `label` at each value, re-fit, and read both sides.

    values : the ladder, in the parameter's own units
    refit  : callable(value) -> (card, info) -- freeze the parameter at
             `value`, re-fit whatever the other objective owns, and hand back
             the card it reached. `info` is anything worth keeping.
    read   : callable(card) -> {name: number} -- the readings to tabulate.
             Every rung must return the same keys.

    Returns [{value, card, info, read}] in ladder order, skipping rungs that
    could not be evaluated (and saying so).
    """
    rows = []
    for v in values:
        if log:
            log("      --- %s = %.6g ---" % (label, v))
        try:
            card, info = refit(float(v))
        except Exception as exc:
            if log:
                log("        could not re-fit here: %s: %s"
                    % (type(exc).__name__, exc))
            continue
        if card is None:
            if log:
                log("        could not re-fit here.")
            continue
        try:
            r = read(card)
        except Exception as exc:
            if log:
                log("        could not read here: %s: %s"
                    % (type(exc).__name__, exc))
            continue
        if r is None:
            continue
        rows.append({"value": float(v), "card": dict(card), "info": info,
                     "read": dict(r)})
        if log:
            log("        " + "  ".join("%s %.6g" % (k, r[k])
                                       for k in sorted(r)))
    return rows


def format_curve(rows, label="parameter", order=None, targets=None,
                 title=None):
    """The ladder as a table, with the target value under each column."""
    if not rows:
        return "    (the trade curve is empty)"
    keys = order or sorted(rows[0]["read"])
    L = ["    %s" % (title or ("what %s costs and what it buys" % label)),
         "    %-12s %s" % (label,
                           "".join("%-16s" % k[:15] for k in keys)),
         "    " + "-" * (13 + 16 * len(keys))]
    for r in rows:
        L.append("    %-12.6g %s"
                 % (r["value"],
                    "".join("%-16.5g" % r["read"].get(k, float("nan"))
                            for k in keys)))
    if targets:
        L.append("    %-12s %s"
                 % ("the device",
                    "".join("%-16s" % ("%.5g" % targets[k]
                                       if k in targets else "-")
                            for k in keys)))
    return "\n".join(L)


def _fin(x):
    """True only for a real, finite number.

    A reading can come back as None (the rung did not evaluate) or as a NaN
    (the rung evaluated but the quantity is undefined -- a drain share needs
    a channel charge to divide, and a card that destroys the charge has no
    share). Neither is a value, and neither may be allowed to win a
    comparison: in Python every comparison against NaN is False, so a NaN
    sitting at the front of a `min` or a `max` is returned unchallenged.
    Everything below filters through here first.
    """
    if x is None:
        return False
    try:
        v = float(x)
    except (TypeError, ValueError):
        return False
    return v == v and v not in (float("inf"), float("-inf"))


def knee(rows, cost_key, gain_key, cost_cap=None, gain_target=None):
    """The rung that buys the most per unit paid, and the rung inside a cap.

    `cost_key` is the reading that must stay small (the drain-current error
    here); `gain_key` is the one that should approach `gain_target` (the
    drain's share of the channel charge).

    Returns {"best_ratio", "within_cap", "rows"} where each entry is the
    chosen row or None. "best_ratio" is the classic elbow: the largest
    (gain moved) / (cost added) measured from the first rung. "within_cap"
    is the plain engineering answer: the rung that gets closest to the target
    without the cost going past `cost_cap`.
    """
    if not rows:
        return {"best_ratio": None, "within_cap": None, "rows": []}
    c0 = rows[0]["read"].get(cost_key)
    g0 = rows[0]["read"].get(gain_key)
    out, best, bestv = [], None, None
    for r in rows:
        c = r["read"].get(cost_key)
        g = r["read"].get(gain_key)
        rec = {"value": r["value"], "cost": c, "gain": g,
               "d_cost": None, "d_gain": None, "ratio": None}
        if _fin(c) and _fin(g) and _fin(c0) and _fin(g0):
            dc, dg = c - c0, g - g0
            rec["d_cost"], rec["d_gain"] = dc, dg
            if dc > 1.0e-12:
                rec["ratio"] = dg / dc
                if best is None or rec["ratio"] > best:
                    best, bestv = rec["ratio"], r
        out.append(rec)
    cap = pick_under_cap(rows, cost_key, gain_key, cost_cap, gain_target)
    return {"best_ratio": bestv, "within_cap": cap, "rows": out}


def pick_under_cap(rows, cost_key, gain_key, cost_cap, gain_target=None):
    """The rung closest to `gain_target` whose cost stays at or under the cap.

    Separated out of `knee` so that the same rule can be applied to several
    caps at once -- see `cap_ladder`. Rungs whose cost or gain is not a finite
    number are not eligible, and if nothing qualifies the answer is None
    rather than an arbitrary row.
    """
    if cost_cap is None or not rows:
        return None
    ok = [r for r in rows
          if _fin(r["read"].get(cost_key))
          and float(r["read"][cost_key]) <= cost_cap]
    if not ok:
        return None
    if gain_target is None:
        return ok[-1]
    elig = [r for r in ok if _fin(r["read"].get(gain_key))]
    if not elig:
        return ok[-1]
    return min(elig,
               key=lambda r: abs(float(r["read"][gain_key]) - gain_target))


def cap_ladder(rows, cost_key, gain_key, gain_target=None, caps=None,
               base=None):
    """The same decision taken again under each of several cost caps.

    A single cap hides the decision inside a number nobody chose. Showing the
    answer under a ladder of caps shows the shape of the trade instead: if the
    pick is the same at +10% and at +100%, the cap is not what decided it; if
    only the first rung ever qualifies, the honest statement is that the
    current cannot afford ANY of this, and that is worth saying out loud
    rather than discovering by seeing an unchanged card.

    `caps` is a list of (label, absolute cost cap). If `base` is given and
    `caps` is None, the default ladder is base x (1.1, 1.25, 1.5, 2.0, 3.0).
    Returns a list of {"label", "cap", "row", "value"}.
    """
    if caps is None:
        b = base
        if b is None and rows and _fin(rows[0]["read"].get(cost_key)):
            b = float(rows[0]["read"][cost_key])
        if not _fin(b) or b <= 0.0:
            return []
        caps = [("+10%", b * 1.10), ("+25%", b * 1.25), ("+50%", b * 1.50),
                ("+100%", b * 2.00), ("+200%", b * 3.00)]
    out = []
    for lab, cp in caps:
        r = pick_under_cap(rows, cost_key, gain_key, cp, gain_target)
        out.append({"label": lab, "cap": float(cp), "row": r,
                    "value": (None if r is None else r["value"])})
    return out


def format_cap_ladder(lad, label="parameter", cost_key="cost",
                      gain_key="gain", gain_target=None, first_value=None):
    L = ["    the same choice, taken again under a ladder of cost caps:",
         "    %-10s %-14s %-14s %-14s %s"
         % ("cap", "cost <=", label, gain_key[:12], "note")]
    for e in lad:
        r = e["row"]
        if r is None:
            L.append("    %-10s %-14.6g %-14s %-14s %s"
                     % (e["label"], e["cap"], "-", "-",
                        "no rung qualifies"))
            continue
        g = r["read"].get(gain_key)
        L.append("    %-10s %-14.6g %-14.6g %-14s %s"
                 % (e["label"], e["cap"], r["value"],
                    "-" if not _fin(g) else "%.4g" % g,
                    "" if gain_target is None or not _fin(g)
                    else "%+.4g from target" % (float(g) - gain_target)))
    vals = set(e["value"] for e in lad if e["value"] is not None)
    L.append("")
    if not vals:
        L.append("    NOT ONE cap admits any rung: on this device the drain"
                 " current cannot")
        L.append("    afford this trade at all, at any price tried.")
    elif len(vals) == 1 and first_value is not None \
            and abs(list(vals)[0] - first_value) <= 1.0e-12:
        L.append("    EVERY cap that admits anything admits ONLY the rung the"
                 " run started from.")
        L.append("    That is the honest answer and it is not a failure of"
                 " the method: on this")
        L.append("    device, at this accuracy, the drain current will not"
                 " pay for the charge.")
        L.append("    The trade curve above is still the result -- it is the"
                 " PRICE, measured.")
    elif len(vals) == 1:
        L.append("    every cap picks the same rung, so the cap is not what"
                 " decided this.")
    else:
        L.append("    the pick moves with the cap, so the cap IS the"
                 " decision -- choose it")
        L.append("    deliberately rather than taking the default.")
    return "\n".join(L)


def format_knee(k, label="parameter", cost_key="cost", gain_key="gain",
                cost_cap=None):
    L = ["    the exchange rate, measured from the first rung:",
         "    %-12s %-14s %-14s %s"
         % (label, "extra " + cost_key[:8], "extra " + gain_key[:8],
            "bought per unit paid")]
    for r in k.get("rows", []):
        L.append("    %-12.6g %-14s %-14s %s"
                 % (r["value"],
                    "-" if r["d_cost"] is None else "%+.5g" % r["d_cost"],
                    "-" if r["d_gain"] is None else "%+.5g" % r["d_gain"],
                    "-" if r["ratio"] is None else "%.4g" % r["ratio"]))
    b = k.get("best_ratio")
    c = k.get("within_cap")
    L.append("")
    if b is not None:
        L.append("    best exchange rate at %s = %.6g" % (label, b["value"]))
    if c is not None:
        L.append("    best result with the cost held under %s: %s = %.6g"
                 % ("%.6g" % cost_cap if cost_cap is not None else "the cap",
                    label, c["value"]))
    if b is None and c is None:
        L.append("    no rung improved anything.")
    return "\n".join(L)
