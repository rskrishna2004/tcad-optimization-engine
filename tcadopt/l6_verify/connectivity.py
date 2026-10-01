"""l6_verify.connectivity -- does this simulator even USE this parameter?

WHY THIS FILE EXISTS
--------------------
Two separate things can make a fitted parameter meaningless, and a residual
cannot tell them apart:

  * the data cannot SEE it        -- identifiability.py measures that;
  * the simulator does not USE it -- nothing measured that until now.

Both were found the hard way in this project's BSIM-CMG extraction.

  ETA1. Step 12 fitted it, Step 13 set it to 10 -- a change the model's own
  equation says is worth about 26 mV of threshold -- and the current came
  back BIT-FOR-BIT IDENTICAL. The listing said why, in one line:

      **warning** (nch ) [Warning]Unsupported model parameter 'eta1' in
      BSIMCMG model card. Ignored.

  PrimeSim HSPICE's LEVEL 72 at VERSION 111.21 does not implement ETA1 at
  all. No amount of residual analysis would have said that; the simulator's
  own warning did, in the file the run had already written.

  UA, EU, ETAMOB. The mobility-degradation group came back with column norms
  of EXACTLY 0.000e+00 at three different cards, over ranges as wide as
  UA in [1e-4, 30]. That is not a data limitation: something inside the
  model's own configuration has switched the term off. The fit had spent
  three parameters on it anyway.

A CONNECTIVITY PROBE is the cheap, decisive test: take the card, change ONE
thing to a value that should matter, run it, and ask whether ANY bit of ANY
curve moved -- and read the listing for the simulator's own opinion. It
costs one evaluation per variant and it answers a question no optimiser can.

WHAT A VERDICT MEANS
--------------------
  ignored    the listing names the parameter as unsupported. The value in
             the card is decoration; the model runs without it.
  flat       every point identical to the base card. The parameter is
             accepted but its term contributes nothing AT THIS CARD -- which
             may be the card's doing (another parameter has zeroed the term)
             rather than the model's, so the probe reports the card it used.
  acts       the largest relative change it caused, per sweep and overall.

$Id: connectivity.py, 2026/09/22 v1.1.11 $
"""
import os
import re

import numpy as np


def _curve_change(base, other, floor=1.0e-30):
    """Largest |other/base - 1| per sweep, over points where base is usable."""
    out = {}
    cb = (base or {}).get("curves") or {}
    co = (other or {}).get("curves") or {}
    for name in sorted(cb):
        if name not in co:
            out[name] = float("nan")
            continue
        a = np.abs(np.asarray(cb[name][1], float))
        b = np.abs(np.asarray(co[name][1], float))
        n = min(len(a), len(b))
        if n < 1:
            out[name] = float("nan")
            continue
        a, b = a[:n], b[:n]
        m = np.isfinite(a) & np.isfinite(b) & (a > floor)
        out[name] = float(np.max(np.abs(b[m] / a[m] - 1.0))) if m.any() \
            else float("nan")
    return out


def listing_warnings(res, n_max=12):
    """Every distinct warning line in the listings this run wrote."""
    rdir = (res or {}).get("run_dir")
    if not rdir or not os.path.isdir(rdir):
        return []
    out = []
    for f in sorted(os.listdir(rdir)):
        if not f.endswith(".lis"):
            continue
        try:
            txt = open(os.path.join(rdir, f)).read()
        except Exception:
            continue
        for line in txt.split("\n"):
            if "warning" in line.lower():
                s = line.strip()
                if s and s not in out:
                    out.append(s)
            if len(out) >= n_max:
                return out
    return out


def unsupported_names(warnings):
    """The parameter names a listing calls unsupported, lower-cased."""
    out = []
    for w in warnings or []:
        for m in re.finditer(r"[Uu]nsupported model parameter\s*'?\"?"
                             r"([A-Za-z_][A-Za-z_0-9]*)", w):
            nm = m.group(1).lower()
            if nm not in out:
                out.append(nm)
    return out


def probe(evaluate, base_card, variants, tag="conn", post=None, ok=None,
          n_warn=12):
    """Run one card per variant and report what each one changed.

    evaluate  : evaluate_batch(cards, tag) -> list of result dicts
    base_card : the card every variant starts from
    variants  : list of (label, overrides, note) or (label, overrides);
                `overrides` is {param: value} applied to the base card
    post      : optional callable(card) -> card, applied to every card
                (model ties such as CFD = CFS)
    ok        : optional callable(result) -> bool; default accepts
                status in ("ok", "partial")

    Returns {label: dict(changed, per_sweep, warnings, unsupported, verdict,
                         overrides, note)}
    """
    def _ok(r):
        if ok is not None:
            return ok(r)
        return r is not None and r.get("status") in ("ok", "partial")

    items = []
    for v in variants:
        if len(v) == 3:
            items.append((v[0], dict(v[1]), v[2]))
        else:
            items.append((v[0], dict(v[1]), ""))
    cards = [dict(base_card)]
    for _, ov, _n in items:
        c = dict(base_card)
        c.update(ov)
        cards.append(c)
    if post is not None:
        cards = [post(c) for c in cards]
    res = evaluate(cards, tag)
    base = res[0]
    out = {}
    for k, (label, ov, note) in enumerate(items):
        r = res[k + 1]
        rec = {"overrides": dict(ov), "note": note,
               "warnings": listing_warnings(r, n_warn)}
        rec["unsupported"] = unsupported_names(rec["warnings"])
        if not _ok(base) or not _ok(r):
            rec["verdict"] = "evaluation failed"
            rec["changed"] = float("nan")
            rec["per_sweep"] = {}
            out[label] = rec
            continue
        ps = _curve_change(base, r)
        rec["per_sweep"] = ps
        vals = [v for v in ps.values() if np.isfinite(v)]
        rec["changed"] = max(vals) if vals else float("nan")
        touched = [n.lower() for n in ov]
        if any(n in rec["unsupported"] for n in touched):
            rec["verdict"] = "ignored"
        elif rec["changed"] == 0.0:
            rec["verdict"] = "flat"
        else:
            rec["verdict"] = "acts"
        out[label] = rec
    return out


def format_report(rep, title="connectivity: what does this simulator "
                             "actually use?"):
    """A block fit for a run log."""
    L = ["  %s" % title,
         "  %-22s %-13s %-9s %s" % ("variant", "largest change",
                                    "verdict", "what it changed"),
         "  " + "-" * 76]
    for label in sorted(rep):
        r = rep[label]
        ch = r.get("changed")
        chs = "-" if ch is None or not np.isfinite(ch) else (
            "0 (exact)" if ch == 0.0 else "%.3e" % ch)
        L.append("  %-22s %-13s %-9s %s"
                 % (label[:22], chs, r.get("verdict", "?"),
                    ", ".join("%s=%g" % (k, v) for k, v in
                              sorted(r.get("overrides", {}).items()))[:34]))
    ign = sorted(l for l in rep if rep[l].get("verdict") == "ignored")
    flat = sorted(l for l in rep if rep[l].get("verdict") == "flat")
    if ign:
        L.append("")
        L.append("  THE SIMULATOR SAYS IT DOES NOT KNOW THESE: %s"
                 % ", ".join(ign))
        shown = []
        for l in ign:
            touched = [n.lower() for n in (rep[l].get("overrides") or {})]
            for w in rep[l]["warnings"]:
                wl = w.lower()
                if any(("'%s'" % n) in wl or ("\"%s\"" % n) in wl
                       or (" %s " % n) in wl for n in touched):
                    if w not in shown:
                        shown.append(w)
                        L.append("     %s" % w[:100])
                    break
    if flat:
        L.append("")
        L.append("  ACCEPTED BUT CHANGED NOTHING AT THIS CARD: %s"
                 % ", ".join(flat))
        L.append("     Every point identical. The parameter's term is")
        L.append("     switched off -- by the model in this configuration or")
        L.append("     by another parameter in this very card. Fitting it")
        L.append("     would put a confident number on nothing.")
    return "\n".join(L)
