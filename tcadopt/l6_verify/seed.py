"""l6_verify.seed -- a value derived from the structure is a CANDIDATE.

WHY THIS EXISTS
---------------
There are three different kinds of number that can go on a model card and
they are not interchangeable.

  the model's own DEFAULT      what bsimcmg_parameters.include declares. It
                               is always safe, because a parameter left off
                               the card takes it, and every earlier step of
                               the project was run with it

  a DERIVED value              worked out from the device's structure, its
                               geometry, its materials. It carries real
                               physics and it is usually the right order of
                               magnitude

  the FITTED value             what the measurement says

A derived value is not a fitted value. It is a hypothesis with a unit
attached. The structure gives bounds and shapes; the model equation decides
what the parameter means; the measurement decides the number.

WHAT IGNORING THAT COST
------------------------
A step derived cgbl from the plate capacitance of the 3 nm isolation plug
under the gate, 3.04 aF over a 10.8 nm channel, so 2.8e-10 F/m. The plug is
real and 3.04 aF is right for a plate of that size. But the plug sits in
series with the substrate depletion and is screened by the channel sheets,
so its plate value is an upper bound on the path and the measured Cgb is
half of it. The card went straight into the run with that value on it, the
capacitance error went from 0.0405 to roughly 0.19, a safety check refused
the card, and the run stopped at its first minute having burned nothing but
the person's afternoon.

One simulation would have caught it. That is what this module is: one
simulation, before the value is trusted.

THE RULE
---------
    A derived value enters a card only after being measured against the
    model's own default on the thing it is supposed to improve, and only if
    it wins. If it loses, the default goes on the card and the run CARRIES
    ON. A derived value that turns out to be wrong is a finding, not a
    reason to stop.

`choose` is that rule as three lines of caller code. `ladder` is the same
idea spread over several candidates, for when the derivation gives a range
rather than a number.
"""
from __future__ import division

VERSION = "1.1.32"


def choose(name, candidate, default, measure, lower_is_better=True,
           log=None, note=""):
    """Measure the candidate and the default, keep the winner.

    `measure(value) -> number or None` is the caller's own measurement of
    whatever the parameter is supposed to improve. None means the card did
    not evaluate, which loses.

    Returns a dict with the value to use, both scores, and why.
    """
    s_def = measure(default)
    s_can = measure(candidate)
    better = (s_can is not None
              and (s_def is None
                   or (s_can < s_def if lower_is_better else s_can > s_def)))
    out = {"name": name, "default": default, "candidate": candidate,
           "score_default": s_def, "score_candidate": s_can,
           "chosen": candidate if better else default,
           "took_candidate": bool(better), "note": note}
    if log:
        log("    %s: the model's default %.6g scores %s, the derived value"
            % (name, default, _f(s_def)))
        log("    %.6g scores %s, so the card takes %.6g."
            % (candidate, _f(s_can), out["chosen"]))
        if not better:
            log("    The derived value LOST. That is a measurement, not a")
            log("    failure, and the run carries on with the default.")
    return out


def ladder(name, values, measure, lower_is_better=True, stop=None, log=None):
    """One row per candidate value, each one measurement, best returned.

    Use when the derivation bounds the answer instead of naming it. The
    rows are the evidence; the pick is the smallest row. `stop()` returning
    True ends the ladder early so a time budget can be honoured without
    this module knowing about clocks.
    """
    rows = []
    for i, v in enumerate(values):
        if stop is not None and stop():
            if log:
                log("    (the ladder stopped early: %d of %d rows done)"
                    % (i, len(values)))
            break
        s = measure(v)
        rows.append({"value": v, "score": s, "ok": s is not None})
    good = [r for r in rows if r["ok"]]
    best = None
    if good:
        best = (min if lower_is_better else max)(good, key=lambda r: r["score"])
    return rows, best


def format_ladder(rows, best=None, title=None, value_fmt="%12.6g",
                  score_fmt="%12.4f", score_name="score", note=None):
    L = [title or "    the candidates, one simulation each:", "",
         "      %12s %12s %s" % ("value", score_name, "")]
    L.append("      " + "-" * 40)
    for r in rows:
        mark = ""
        if best is not None and r is best:
            mark = "   <- the best"
        if not r["ok"]:
            L.append(("      " + value_fmt + " %12s")
                     % (r["value"], "refused"))
            continue
        L.append(("      " + value_fmt + " " + score_fmt + "%s")
                 % (r["value"], r["score"], mark))
    if note:
        L.append("")
        L.append("      " + note)
    return "\n".join(L)


def _f(x):
    return "none" if x is None else "%.6f" % x
