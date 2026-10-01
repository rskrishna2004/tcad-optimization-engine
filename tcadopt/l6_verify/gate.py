"""l6_verify.gate -- the no-regression gate, the scope rule, and greedy
seeding.  (TCADOpt v1.1.15)

WHY THIS FILE EXISTS
--------------------
An extraction is a sequence of stages. Each stage fits a few parameters
against a few curves, hands its card to the next one, and the card that
comes out of the last stage is the answer. That works only if every stage
leaves the WHOLE thing at least as good as it found it. Nothing in
TCADOpt measured that until now, and Step 14 of this project paid for it.

Step 14's own log, three lines, in order:

    six-sweep error: aligner 0.01644   after the search 0.01644   (PART 6)
    ...
    pclmcv       0.027522773      -> 0.001                        (PART 7B)
    qmfactorcv   0                -> 0.83334451
    C-V error at Vd = 0.6 V: 0.12265 -> 0.02042

The last stage improved the curve it was looking at by six times. It also
multiplied every drain current by about 0.47, because QMFACTORCV is not a
capacitance-only parameter -- the same run's own census had MEASURED it
moving the current by 66%:

    qmfactorcv = 1    acts    I-V change 6.617e-01   C-V change 1.995e-01

The stage was accepted because the only number anyone compared was the one
the stage was minimising. The card went from 0.04532 on all ten sweeps to
0.37448, and the run ended and called it the answer.

TWO RULES, AND THIS FILE IS BOTH OF THEM
----------------------------------------
  1. SCOPE.  A parameter may be fitted against a SUBSET of the sweeps only
     if a measurement says it does not move the sweeps outside that subset.
     No measurement is not permission: `scope_check` returns "not measured"
     and `enforce_scope` drops the parameter. The rule fails CLOSED.

  2. NO REGRESSION.  A stage is judged on the whole objective -- every
     sweep the final card will be judged on -- before and after. A stage
     that makes it worse is ROLLED BACK, and the run continues from the
     card that went in. `StageGate` is one HSPICE evaluation per stage and
     it cannot be argued with.

Neither rule needs to know any physics. Rule 1 asks the simulator what the
parameter touches; rule 2 asks the objective what the stage did. Both are
measurements, which is the only kind of statement this engine accepts.

$Id: gate.py, 2026/09/23 v1.1.12 $
"""
import numpy as np


# a relative change below this, on a sweep OUTSIDE the stage's own list,
# counts as "does not move it". 1e-3 is a tenth of the smallest on-state
# error this project has ever fitted to, and 6600x smaller than the change
# QMFACTORCV was measured to make.
SCOPE_TOL = 1.0e-3

# a stage that leaves the objective worse by less than this (in percent) did
# not damage anything -- it simply found nothing. The card that went in is
# still the one that is kept; only the wording differs, because "rolled back
# for making it worse" is not what happened.
NO_GAIN_PCT = 0.05


# ---------------------------------------------------------------------------
#  rule 1 -- scope
# ---------------------------------------------------------------------------
def census_from_probe(rep, mapping):
    """Turn connectivity.probe's output into {param: {sweep: |change|}}.

    rep     : probe()'s return, keyed by variant label
    mapping : {param_name: [variant labels that moved ONLY that parameter]}

    Several variants per parameter (for example one at each end of its fit
    box) are combined by taking the LARGEST change measured on each sweep,
    which is the worst case the fit could produce.
    """
    out = {}
    for name, labels in (mapping or {}).items():
        per = {}
        seen = False
        for lab in labels:
            r = (rep or {}).get(lab)
            if not r or r.get("verdict") == "evaluation failed":
                continue
            seen = True
            for sw, v in (r.get("per_sweep") or {}).items():
                if v is None or not np.isfinite(v):
                    continue
                per[sw] = max(per.get(sw, 0.0), float(v))
        if seen:
            out[name] = per
    return out


def scope_check(names, fit_sweeps, all_sweeps, census, tol=SCOPE_TOL):
    """May each of `names` be fitted against `fit_sweeps` alone?

    names      : the parameters a stage wants to fit
    fit_sweeps : the sweeps the stage's residual is built from
    all_sweeps : every sweep the final card is judged on
    census     : {param: {sweep: |relative change| measured}} -- what the
                 simulator did when that parameter alone was moved, over
                 the range the fit may move it (see census_from_probe)
    tol        : a change this small on an outside sweep is not a move

    Returns {param: {verdict, worst_out, worst_sweep, worst_in, outside}}
    with verdict one of:
      "in scope"     -- measured, and it moves nothing outside the stage
      "OUT OF SCOPE" -- measured, and it DOES move a sweep outside it
      "not measured" -- no census entry: not allowed, because the rule
                        fails closed
    """
    fit = set(fit_sweeps or [])
    outside = [s for s in (all_sweeps or []) if s not in fit]
    out = {}
    for n in names:
        per = (census or {}).get(n)
        if per is None:
            out[n] = {"verdict": "not measured", "worst_out": float("nan"),
                      "worst_sweep": None, "worst_in": float("nan"),
                      "outside": outside}
            continue
        wo, ws, wi = 0.0, None, 0.0
        for sw in outside:
            v = per.get(sw)
            if v is None or not np.isfinite(v):
                continue
            if v > wo:
                wo, ws = float(v), sw
        for sw in fit:
            v = per.get(sw)
            if v is not None and np.isfinite(v) and v > wi:
                wi = float(v)
        out[n] = {"verdict": ("in scope" if wo <= float(tol)
                              else "OUT OF SCOPE"),
                  "worst_out": wo, "worst_sweep": ws, "worst_in": wi,
                  "outside": outside}
    return out


def enforce_scope(names, rep, log=None, allow_unmeasured=False):
    """The names that may be fitted, and the ones the rule refuses.

    Returns (allowed, refused) with refused a list of (name, why).
    """
    say = log if log is not None else (lambda *a, **k: None)
    allowed, refused = [], []
    for n in names:
        v = (rep or {}).get(n, {}).get("verdict", "not measured")
        if v == "in scope":
            allowed.append(n)
        elif v == "not measured" and allow_unmeasured:
            allowed.append(n)
            say("    SCOPE: %s has no measurement and is allowed only "
                "because this stage asked for that explicitly." % n)
        else:
            why = ("it moves %s by %.3e"
                   % ((rep or {}).get(n, {}).get("worst_sweep"),
                      (rep or {}).get(n, {}).get("worst_out", float("nan")))
                   ) if v == "OUT OF SCOPE" else \
                  "nothing has measured what it moves"
            refused.append((n, why))
    return allowed, refused


def format_scope_report(rep, fit_sweeps=(), tol=SCOPE_TOL,
                        title="scope: may this parameter be fitted on these"
                              " sweeps alone?"):
    L = ["    %s" % title,
         "    (the stage is looking at: %s)"
         % (", ".join(fit_sweeps) if fit_sweeps else "-"),
         "",
         "    %-13s %-13s %-13s %-22s %s"
         % ("param", "moves these", "moves others", "worst outside sweep",
            "verdict"),
         "    " + "-" * 78]
    for n in sorted(rep or {}):
        r = rep[n]
        wi = r.get("worst_in", float("nan"))
        wo = r.get("worst_out", float("nan"))
        L.append("    %-13s %-13s %-13s %-22s %s"
                 % (n[:13],
                    "-" if not np.isfinite(wi) else "%.3e" % wi,
                    "-" if not np.isfinite(wo) else "%.3e" % wo,
                    str(r.get("worst_sweep") or "-")[:22],
                    r.get("verdict", "?")))
    L.append("")
    L.append("    a change smaller than %.0e on a sweep this stage is not"
             " looking at" % tol)
    L.append("    counts as no change. Anything larger, and the stage is"
             " allowed to")
    L.append("    trade that sweep away for its own -- which is exactly how"
             " Step 14")
    L.append("    lost a card that was already right.")
    return "\n".join(L)


# ---------------------------------------------------------------------------
#  rule 2 -- no regression
# ---------------------------------------------------------------------------
def no_regression(err_before, err_after, tol=0.0):
    """True if `err_after` is not worse than `err_before` by more than tol
    (a fraction of err_before). Fails closed on a missing number."""
    if err_after is None or not np.isfinite(err_after):
        return False
    if err_before is None or not np.isfinite(err_before):
        return True
    return float(err_after) <= float(err_before) * (1.0 + float(tol))


class StageGate(object):
    """Judge every stage on the WHOLE objective, and roll back what hurts.

    evaluate : callable(list_of_cards, tag) -> list of result dicts
               (an evaluator's `evaluate_batch`, built on EVERY sweep the
               final card is judged on)
    scorer   : callable(curves) -> score, NEGATIVE-is-worse, the convention
               l1_spec.CurveResidualScorer uses. The gate reports the error,
               which is -score.
    wrap     : optional callable(card) -> card run by the evaluator (this is
               where a step script adds its structure block)
    tol      : how much worse a stage may leave the whole objective, as a
               fraction. 0.0 -- the default and the only value this project
               uses -- means not at all.

    Usage:
        G = StageGate(EV_ALL.evaluate_batch, SC_ALL, wrap=card_of, log=print)
        G.open(card, "the card this step starts from")
        ...
        card, rec = G.close(candidate, "7B -- the capacitance at Vdd")

    `close` costs ONE evaluation. The card it returns is the one the run
    must continue from -- the candidate if it was accepted, the card that
    went in if it was not.
    """

    def __init__(self, evaluate, scorer, wrap=None, tol=0.0, log=None,
                 tag="gate", name="all ten sweeps"):
        self.evaluate = evaluate
        self.scorer = scorer
        self.wrap = wrap if wrap is not None else (lambda c: dict(c))
        self.tol = float(tol)
        self.log = log if log is not None else (lambda *a, **k: None)
        self.tag = tag
        self.name = name
        self.ledger = []
        self.n_evals = 0
        self.card = None
        self.err = None

    # -- measurement ------------------------------------------------------
    def measure(self, card, tag=None):
        """The whole objective at one card, or None if it cannot be had."""
        self.n_evals += 1
        try:
            res = self.evaluate([self.wrap(dict(card))], tag or self.tag)
        except Exception:
            return None
        if not res:
            return None
        r = res[0]
        if r is None or r.get("status") not in ("ok", "partial"):
            return None
        try:
            e = self.scorer(r.get("curves"))
        except Exception:
            return None
        if e is None or not np.isfinite(e) or e <= -1.0e8:
            return None
        return -float(e)

    # -- the baseline -----------------------------------------------------
    def open(self, card, label="the card this run starts from"):
        e = self.measure(card, "%s_open" % self.tag)
        self.card, self.err = dict(card), e
        self.ledger.append({"stage": label, "err_before": None,
                            "err_after": e, "accepted": True, "note": "",
                            "delta": None})
        self.log("    GATE opens on %s: the error of the card this run "
                 "starts from is %s"
                 % (self.name, "-" if e is None else "%.5f" % e))
        return e

    # -- the verdict ------------------------------------------------------
    def close(self, new_card, label, note="", tol=None):
        """Measure `new_card` on the whole objective and accept or roll back.

        Returns (card_to_continue_from, record).
        """
        t = self.tol if tol is None else float(tol)
        e_new = self.measure(new_card, "%s_%s" % (self.tag, _slug(label)))
        e_old = self.err
        rec = {"stage": label, "err_before": e_old, "err_after": e_new,
               "note": note, "tol": t}
        if e_new is None:
            rec["accepted"] = False
            rec["delta"] = None
            rec["why"] = "the card this stage produced could not be evaluated"
            self.ledger.append(rec)
            self.log("    GATE [%s]: the card this stage produced could not"
                     " be evaluated." % label)
            self.log("    REJECTED -- the run continues from the card that"
                     " went in.")
            return (dict(self.card) if self.card is not None
                    else dict(new_card)), rec
        d = (None if (e_old is None or not np.isfinite(e_old) or e_old == 0.0)
             else 100.0 * (e_new / e_old - 1.0))
        rec["delta"] = d
        acc = no_regression(e_old, e_new, t)
        rec["accepted"] = bool(acc)
        self.ledger.append(rec)
        self.log("    GATE [%s]" % str(label)[:60])
        self.log("      %s:  %s -> %s%s"
                 % (self.name, "-" if e_old is None else "%.5f" % e_old,
                    "%.5f" % e_new,
                    "" if d is None else "   (%+.2f%%)" % d))
        if acc:
            self.card, self.err = dict(new_card), e_new
            self.log("      ACCEPTED -- the run continues from this stage's"
                     " card.")
            return dict(new_card), rec
        if d is not None and d <= NO_GAIN_PCT:
            rec["no_gain"] = True
            self.log("      NOTHING TO KEEP -- this stage found no gain"
                     " (%+.4f%%), so the" % d)
            self.log("      card is left exactly as it was.")
        else:
            self.log("      REJECTED -- this stage made the whole thing"
                     " worse, so its card")
            self.log("      is thrown away and the run continues from the"
                     " card that went in.")
        return (dict(self.card) if self.card is not None
                else dict(new_card)), rec

    # -- a stage that reports its own number, without a second evaluation --
    def note(self, label, text):
        self.ledger.append({"stage": label, "err_before": None,
                            "err_after": None, "accepted": None,
                            "note": text, "delta": None})

    # -- the ledger -------------------------------------------------------
    def format_ledger(self, title="THE LEDGER: what every stage did to the"
                                  " whole objective"):
        L = ["  %s" % title,
             "  %-44s %-11s %-11s %-10s %s"
             % ("stage", "before", "after", "change", "verdict"),
             "  " + "-" * 92]
        for r in self.ledger:
            if r.get("err_after") is None and r.get("err_before") is None:
                L.append("  %-44s %s" % (str(r.get("stage"))[:44],
                                         r.get("note", "")))
                continue
            L.append("  %-44s %-11s %-11s %-10s %s"
                     % (str(r.get("stage"))[:44],
                        "-" if r.get("err_before") is None
                        else "%.5f" % r["err_before"],
                        "-" if r.get("err_after") is None
                        else "%.5f" % r["err_after"],
                        "-" if r.get("delta") is None
                        else "%+.2f%%" % r["delta"],
                        "start" if r.get("accepted") is None
                        else ("accepted" if r["accepted"]
                              else ("no gain" if r.get("no_gain")
                                    else "ROLLED BACK"))))
        n_bad = len([r for r in self.ledger if r.get("accepted") is False
                     and not r.get("no_gain")])
        n_nil = len([r for r in self.ledger if r.get("no_gain")])
        L.append("")
        L.append("  %d stage(s) were rolled back for making the whole thing"
                 " worse; %d found" % (n_bad, n_nil))
        L.append("  nothing to keep. The gate cost %d HSPICE evaluations."
                 % self.n_evals)
        return "\n".join(L)


def _slug(s):
    out = []
    for ch in str(s).lower():
        out.append(ch if (ch.isalnum() or ch == "_") else "_")
    return ("".join(out).strip("_") or "stage")[:24]


def seed_greedy(evaluate, score, card, seeds, tag="seed", post=None,
                wrap=None, log=None):
    """Apply proposed seed values ONE AT A TIME, keeping only what helps.
    (v1.1.15)

    Step 17's PART 4 had a map of every capacitance knob and took each
    one's own best value -- all six of them, all at once. The two
    capacitance sweeps went from 0.04726 to 0.04808 BEFORE a single fit
    iteration had run, the Levenberg-Marquardt step then found no descent
    at any damping, and the gate threw the whole stage away.

    Nothing was wrong with the maps. What was wrong is that a 1-D map
    measures a parameter with everything else HELD, and six such answers
    are only valid together if the six parameters are independent -- and
    the identifiability report for this very card says four of them are
    degenerate to one part in 1e16. Applying them all at once is applying a
    sum of six answers to six different questions.

    So: sort the candidates by the gain their own map predicts, try them in
    that order, and keep each one only if the stage score MEASURED with it
    in place is better than without. Every candidate costs one evaluation
    and the result is a seed that is better than where you started by
    construction, not by hope.

    seeds : [(name, value, predicted_gain)] -- predicted_gain may be None
    score : callable(result) -> error, lower is better

    Returns (card, [{name, value, before, after, kept}]).
    """
    def _run(c):
        cc = post(c) if post is not None else dict(c)
        cc = wrap(cc) if wrap is not None else cc
        res = evaluate([cc], tag)
        return score(res[0] if res else None)

    cur = dict(card)
    base = _run(cur)
    rows = []
    order = sorted(seeds, key=lambda t: (-(t[2] if len(t) > 2
                                           and t[2] is not None else 0.0)))
    for item in order:
        name, val = item[0], item[1]
        if val is None:
            continue
        old = cur.get(name)
        if old is not None and abs(float(val) - float(old)) <= \
                1e-12 * max(abs(float(old)), 1e-30):
            rows.append({"name": name, "value": float(val),
                         "before": base, "after": base, "kept": False,
                         "why": "already there"})
            continue
        trial = dict(cur)
        trial[name] = float(val)
        got = _run(trial)
        keep = (got is not None and base is not None and got < base)
        rows.append({"name": name, "value": float(val), "before": base,
                     "after": got, "kept": bool(keep),
                     "why": "" if keep else "made this stage worse"})
        if keep:
            cur, base = trial, got
        if log:
            log("      seed %-12s %-14.6g %s -> %s   %s"
                % (name, float(val),
                   "-" if rows[-1]["before"] is None
                   else "%.5f" % rows[-1]["before"],
                   "-" if got is None else "%.5f" % got,
                   "KEPT" if keep else "dropped"))
    return cur, rows


def format_seed_greedy(rows, title="seeding one at a time, keeping only"
                                   " what measures better"):
    L = ["    %s" % title,
         "    %-14s %-14s %-10s %-10s %s"
         % ("param", "tried", "before", "after", "verdict"),
         "    " + "-" * 64]
    for r in rows:
        L.append("    %-14s %-14.6g %-10s %-10s %s"
                 % (r["name"], r["value"],
                    "-" if r["before"] is None else "%.5f" % r["before"],
                    "-" if r["after"] is None else "%.5f" % r["after"],
                    "KEPT" if r["kept"] else ("no change" if
                                              r.get("why") == "already there"
                                              else "dropped")))
    k = [r for r in rows if r["kept"]]
    L.append("")
    L.append("    %d of %d seeds improved this stage and were kept."
             % (len(k), len(rows)))
    return "\n".join(L)


# ==========================================================================
#  THE FROZEN GATE -- for a stage that CANNOT move the current  (v1.1.18)
# ==========================================================================
class FrozenGate(object):
    """Judge a stage on the capacitance, and prove the current never moved.

    WHY THIS IS A DIFFERENT GATE
    ----------------------------
    `StageGate` asks "is the whole objective no worse?". That is the right
    question for a stage that touches the current. It is the WRONG question
    for a stage that provably cannot: there the answer is decided entirely
    by the capacitance, and mixing the current into the score only lets a
    tiny numerical wobble in a quantity the stage cannot influence veto a
    real improvement. Step 20 lost its parasitic-floor solve exactly that
    way -- the floor error fell from 2.18 to 0.94 aF and Cgb's error from
    85% to 38%, and the stage was rolled back because the ten-sweep total,
    which contains Cgg but not Cgd, Cgs or Cgb, rose by 0.0008.

    So this gate scores the stage on the C-V objective it is actually
    fitting, and treats the current as an ASSERTION to be checked rather
    than a number to be traded against: every current sweep must come back
    bit-identical, to `rel_tol`. If one moves, the stage is rejected AND the
    run is told that the free-zone claim was wrong for that parameter --
    which is a finding about the model, not a fit result to discard quietly.

    evaluate : callable(list_of_cards, tag) -> results
    scorer   : the C-V scorer (negative-is-worse, as everywhere else)
    iv_names : the current sweeps that must not move
    """

    def __init__(self, evaluate, scorer, iv_names, wrap=None, log=None,
                 tag="frozen", rel_tol=1.0e-9):
        self.evaluate = evaluate
        self.scorer = scorer
        self.iv_names = list(iv_names)
        self.wrap = wrap if wrap is not None else (lambda c: dict(c))
        self.log = log if log is not None else (lambda *a, **k: None)
        self.tag = tag
        self.rel_tol = float(rel_tol)
        self.ledger = []
        self.n_evals = 0
        self.card = None
        self.err = None
        self.curves = None

    def _run(self, card, tag=None):
        self.n_evals += 1
        try:
            res = self.evaluate([self.wrap(dict(card))], tag or self.tag)
        except Exception:
            return None
        if not res:
            return None
        r = res[0]
        if r is None or r.get("status") not in ("ok", "partial"):
            return None
        return r

    def open(self, card, label="the card this stage starts from"):
        r = self._run(card, "%s_open" % self.tag)
        if r is None:
            self.card, self.err, self.curves = dict(card), None, None
            self.log("    FROZEN GATE could not evaluate the starting card.")
            return None
        try:
            e = self.scorer(r.get("curves"))
            e = None if (e is None or e <= -1.0e8) else -float(e)
        except Exception:
            e = None
        self.card, self.err, self.curves = dict(card), e, r.get("curves")
        self.ledger.append({"stage": label, "err_before": None,
                            "err_after": e, "accepted": True, "moved": None})
        self.log("    FROZEN GATE opens: the capacitance error of the card"
                 " this stage starts from is %s"
                 % ("-" if e is None else "%.6f" % e))
        return e

    def close(self, new_card, label, note=""):
        """Returns (card_to_continue_from, record)."""
        from ..l4_knowledge.cv_scope import verify_scope
        r = self._run(new_card, "%s_close" % self.tag)
        rec = {"stage": label, "err_before": self.err, "note": note}
        if r is None:
            rec.update({"accepted": False, "err_after": None,
                        "why": "the stage's card could not be evaluated"})
            self.ledger.append(rec)
            self.log("    FROZEN GATE [%s]: the card did not evaluate."
                     " Rolled back." % label)
            return dict(self.card), rec
        try:
            e = self.scorer(r.get("curves"))
            e = None if (e is None or e <= -1.0e8) else -float(e)
        except Exception:
            e = None
        chk = verify_scope(self.curves, r.get("curves"), self.iv_names,
                           rel_tol=self.rel_tol)
        rec["err_after"] = e
        rec["current_moved"] = None if chk.get("missing") else \
            float(chk["worst_rel"])
        rec["current_where"] = chk.get("where")
        ok_cur = bool(chk.get("free"))
        better = (e is not None and (self.err is None or e < self.err))
        rec["accepted"] = bool(ok_cur and better)
        if not ok_cur:
            rec["why"] = ("a current sweep MOVED (%s by %.3e). This stage"
                          " was supposed to be unable to touch the current,"
                          " so the free-zone list is wrong about one of its"
                          " parameters." % (chk.get("where"),
                                            chk.get("worst_rel", -1.0)))
        elif not better:
            rec["why"] = "the capacitance did not improve"
        self.ledger.append(rec)
        self.log("    FROZEN GATE [%s]" % label)
        self.log("      capacitance error : %s -> %s"
                 % ("-" if self.err is None else "%.6f" % self.err,
                    "-" if e is None else "%.6f" % e))
        self.log("      largest move in any current sweep: %.3e  (%s)"
                 % (chk.get("worst_rel", float("nan")),
                    "as the source says: none" if ok_cur
                    else "*** THE CURRENT MOVED ***"))
        if rec["accepted"]:
            self.card, self.err, self.curves = dict(new_card), e, \
                r.get("curves")
            self.log("      ACCEPTED.")
        else:
            self.log("      ROLLED BACK -- %s" % rec.get("why", ""))
        return dict(self.card), rec
