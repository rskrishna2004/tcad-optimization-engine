"""l6_verify.plausibility -- how far has the fit walked from the model?

WHY THIS FILE EXISTS
--------------------
Step 9 of the nanosheet extraction cut the whole-model error by 61%, which is
the largest single-step improvement the project has produced. Reading its own
output afterwards showed HOW:

    UA      model default 0.3        fitted 0.00153      196x smaller
    ETAMOB  model default 2.0        fitted 0.591        -70%
    EU      model default 2.5        fitted 5.82         +133%
    K0SI    model default 1.0        fitted 0.1056       9.5x smaller

and the identifiability pass at that card measured the column norm of UA, EU
and ETAMOB as EXACTLY 0.000e+00 on all ten sweeps. Equation 3.520 is

    D_mob = 1 + UA * (E_effa)^EU + (the UD term)

and the only way all three of those can be inert at once is if UA*(E_effa)^EU
has become negligible beside the 1. The fit had not extracted the mobility
degradation model; it had SWITCHED IT OFF, and then made the drive current up
elsewhere -- with K0SI, whose own manual text says it exists to "reclaim the
fit in the strong inversion region" and which at 0.1056 was instead amplifying
a correction by 2.19x.

Every number in that card was inside its declared box. Every residual went
down. Nothing in TCADOpt said a word.

WHAT THIS MODULE CHECKS, AND WHY EACH CHECK IS FAIR
---------------------------------------------------
(1) DISTANCE FROM THE MODEL'S OWN DEFAULT.

    A compact model's default value is not arbitrary. It is the model author's
    statement of what the parameter is typically worth in a device the model
    was built for. A fit that moves one by two orders of magnitude has either
    found something real about THIS device or has quietly absorbed somebody
    else's error -- and those two look identical in a residual.

    So this is a REPORT, not a veto. It says how far each parameter has moved
    and in which direction, in the parameter's own natural coordinate, and
    flags the ones past a threshold so that a human decides. A parameter that
    SHOULD move a long way (PHIG on a device with a different gate metal, say)
    gets flagged, the reader says "yes, obviously", and moves on. That costs a
    second. Not flagging it costs a wrong card.

(2) FITTED BUT INERT.

    A parameter that a stage was allowed to move, and which came back with a
    zero derivative at the answer, has been pushed into a region where it does
    nothing. That is strictly worse than not fitting it: the card now carries
    a specific, confident-looking number for a quantity the data cannot see,
    AND the model term it belongs to has been disabled. Freezing it at the
    model default would be more honest and would fit exactly as well.

    This check needs the identifiability column norms, so it runs after the
    Jacobian rather than inside the fit.

THE DEFAULTS BELOW ARE QUOTED, NOT REMEMBERED. Every one is the literal
declaration from the Verilog-A source that ships with BSIM-CMG 112.1.0, with
its line number, so a reader can check any of them in one grep. Where the
declared default is another PARAMETER rather than a number -- CFD, VSAT1,
PCLMCV, CGDO -- the entry records that instead, because "how far from its
default" for those means "how far from its partner", which the `tied:`
mechanism in l1_spec.paramspace already enforces.

$Id: plausibility.py, 2026/09/20 [YOUR NAME] $
"""
import math

# name -> (default, scale, source line in bsimcmg_parameters.include)
#   scale "log" : distance reported as a ratio      (x times bigger/smaller)
#   scale "lin" : distance reported as a percentage
#   scale "abs" : default is 0, so a ratio is meaningless; absolute only
MODEL_DEFAULT = {
    "phig":       (4.61,     "lin", 168),
    "cit":        (0.0,      "abs", 228),
    "cdsc":       (7.0e-3,   "log", 242),
    "cdscd":      (7.0e-3,   "log", 249),
    "dvt0":       (0.0,      "abs", 263),
    "dvt1":       (0.6,      "lin", 270),
    "phin":       (0.05,     "lin", 284),
    "eta0":       (0.6,      "lin", 291),
    "eta1":       (0.0,      "abs", 298),
    "dsub":       (1.06,     "lin", 319),
    "thetadibl":  (0.0,      "abs", 210),
    "dvtp0":      (0.0,      "abs", 214),
    "dvtp1":      (0.0,      "abs", 221),
    "dvtp2":      (0.0,      "abs", 208),
    "k0":         (0.0,      "abs", 355),
    "k0si":       (1.0,      "log", 369),
    "k0sisat":    (0.0,      "abs", 397),
    "qm0":        (1.0e-3,   "log", 478),
    "qmfactor":   (0.0,      "abs", 482),
    "qmtcencv":   (0.0,      "abs", 489),
    "pqm":        (0.66,     "lin", 503),
    "vsat":       (8.5e4,    "log", 541),
    "psat":       (2.0,      "lin", 576),
    "ksativ":     (1.0,      "lin", 584),
    "mexp":       (4.0,      "lin", 629),
    "ptwg":       (0.0,      "abs", 643),
    "u0":         (3.0e-2,   "log", 713),
    "etamob":     (2.0,      "lin", 734),
    "ua":         (0.3,      "log", 755),
    "eu":         (2.5,      "lin", 797),
    "ud":         (0.0,      "abs", 811),
    "rdswmin":    (0.0,      "abs", 1071),
    "rdsw":       (1.0e2,    "log", 1089),
    "pdibl1":     (1.3,      "lin", 1160),
    "pdibl2":     (2.0e-4,   "log", 1167),
    "drout":      (1.06,     "lin", 1188),
    "pvag":       (1.0,      "lin", 1195),
    "wr":         (1.0,      "lin", 1124),
    "pclm":       (1.3e-2,   "log", 1208),
    "pclmg":      (0.0,      "abs", 1223),
    "agidl":      (6.055e-12, "log", 1496),
    "cfs":        (2.5e-11,  "log", 1806),
    "cgso":       (0.0,      "abs", 1821),
    "cgbo":       (0.0,      "abs", 1823),
    "deltaw":     (0.0,      "abs", 117),
    "deltawcv":   (0.0,      "abs", 118),
    "qmfactorcv": (0.0,      "abs", 2131),
    "alpha_ufcm": (0.5556,   "lin", 2132),
}

# these are declared with ANOTHER PARAMETER as their default, so their
# "plausible value" is whatever their partner holds -- see l1_spec.paramspace
FOLLOWS = {"cfd": ("cfs", 1813), "vsat1": ("vsat", 555),
           "pclmcv": ("pclm", 1230), "cgdo": ("cgso", 1822)}

RATIO_WARN = 10.0        # a log-scaled parameter 10x from its default
PCT_WARN = 50.0          # a lin-scaled parameter 50% from its default

# Parameters whose own documentation says which SIDE of a value is meaningful.
# A distance check cannot catch these: K0SI came back 9.5x from its default,
# just inside the 10x threshold, while being on the wrong side of it entirely.
#   name -> (op, bound, why -- quoted or cited, never paraphrased loosely)
DIRECTIONAL = {
    "k0si": (">=", 1.0,
             "manual section 3.9: K0SI and K0SISAT 'helps RECLAIM the fit in "
             "the strong inversion region'. Its default is 1.0 and it sits in "
             "the DENOMINATOR of eq. 3.525, so K0SI > 1 shrinks the leftover "
             "strong-inversion lift, which is the stated job. K0SI < 1 "
             "AMPLIFIES it -- at 0.1056 the correction became a 2.19x drive-"
             "current multiplier, which is not what the parameter is for."),
    "psat": (">=", 2.0,
             "manual parameter table: PSAT min 2.0, and the Verilog-A comment "
             "says 'after binning should be from [2.0 : inf)'"),
    "mexp": (">=", 2.0,
             "manual parameter table: MEXP min 2"),
    "dvt1": (">", 0.0,
             "Verilog-A: 'After binning it should be within (0 : inf)'"),
}


def directional(name, value):
    """Is `value` on the side of its bound that the model's own text allows?"""
    if name not in DIRECTIONAL:
        return None
    op, bound, why = DIRECTIONAL[name]
    try:
        v = float(value)
    except Exception:
        return None
    ok = (v >= bound) if op == ">=" else (
        (v <= bound) if op == "<=" else (
            (v > bound) if op == ">" else (v < bound)))
    return {"ok": bool(ok), "op": op, "bound": bound, "why": why,
            "value": v}


def distance(name, value):
    """How far `value` is from the model's declared default for `name`.

    Returns a dict, or None when the parameter has no declared default here.
      kind     : "log" | "lin" | "abs" | "follows"
      default  : the declared default (or the partner's name)
      ratio    : value/default or default/value, whichever is >= 1   (log)
      pct      : 100*(value-default)/default                         (lin)
      far      : True when it is past the warning threshold
      line     : the source line the default was read from
    """
    if name in FOLLOWS:
        partner, line = FOLLOWS[name]
        return {"kind": "follows", "default": partner, "far": False,
                "line": line, "value": value}
    if name not in MODEL_DEFAULT:
        return None
    d, kind, line = MODEL_DEFAULT[name]
    out = {"kind": kind, "default": d, "line": line, "value": value,
           "far": False}
    try:
        v = float(value)
    except Exception:
        return out
    if kind == "abs":
        out["delta"] = v - d
        out["far"] = False          # a default of 0 gives no scale to compare
        return out
    if kind == "log":
        if v <= 0 or d <= 0:
            out["far"] = True
            out["note"] = "non-positive value on a log-scaled parameter"
            return out
        r = v / d if v >= d else d / v
        out["ratio"] = r
        out["bigger"] = (v >= d)
        out["far"] = r >= RATIO_WARN
        return out
    out["pct"] = 100.0 * (v - d) / d if d else float("nan")
    out["far"] = abs(out.get("pct", 0.0)) >= PCT_WARN
    return out


def audit(card, names=None):
    """Distance from default for every parameter in `card` (or in `names`)."""
    rep = {}
    for n in sorted(names if names is not None else card):
        if n not in card:
            continue
        d = distance(n, card[n])
        if d is not None:
            rep[n] = d
    return rep


def fitted_but_inert(fitted_names, column_norms, rel_floor=1.0e-12,
                     swing=None, cut=None, confirmed=None):
    """Parameters a stage was allowed to move that came back doing nothing.

    PREFERRED CALL (v1.1.11): pass `swing`, the identifiability pass's own
    {name: SWING} map at the fitted card, and a name is inert when its SWING
    is below `cut` -- the same comparable measure, in RMS residual, that
    `analyse` and `inert_scope` use.

    THE OLD CALL, AND WHY IT WAS WRONG. Before v1.1.11 this compared RAW
    column norms -- d(residual)/d(parameter) in the PARAMETER'S OWN UNIT --
    against a fraction of the largest column. Those units are not comparable:
    in Step 13's audit CFS's column was 2.7e+10 (per F/m) and RDSW's was
    1.1e-02 (per ohm.um), so the floor came out at 0.027 and RDSW was
    reported "fitted but inert" while the very same run's SWING table had it
    ALIVE at 0.43 -- a units mismatch inside a units audit. A column norm is
    only comparable after multiplying by the parameter's own range width,
    which is exactly what SWING is. The raw-column path is kept for callers
    that have no SWING, and it now says so in `note`.

    `confirmed` is identifiability.confirm_dead's output, {name: {...,
    "scan": SWING measured by an actual scan}}. A derivative can read zero
    where the parameter sits on a flat spot of its own term while a scan
    across the range still moves the residual -- Step 12 found five of nine
    "dead" parameters alive that way -- so when a scan is available the
    verdict uses the LARGER of the two. Without it this check would
    contradict the confirm_dead table printed a few lines above it.

    Returns the list of offending names (sorted).
    """
    if swing:
        c = SWING_CUT if cut is None else float(cut)
        out = []
        for n in sorted(fitted_names or []):
            if n not in swing or swing[n] is None:
                continue
            v = abs(float(swing[n]))
            sc = ((confirmed or {}).get(n) or {}).get("scan")
            if sc is not None:
                try:
                    v = max(v, abs(float(sc)))
                except Exception:
                    pass
            if v < c:
                out.append(n)
        return out
    if not column_norms:
        return []
    mx = max(abs(float(v)) for v in column_norms.values()) or 1.0
    out = []
    for n in sorted(fitted_names or []):
        if n not in column_norms:
            continue
        if abs(float(column_norms[n])) <= rel_floor * mx:
            out.append(n)
    return out


def _wrap(text, width):
    out, line = [], ""
    for w in text.split():
        if line and len(line) + 1 + len(w) > width:
            out.append(line)
            line = w
        else:
            line = (line + " " + w) if line else w
    if line:
        out.append(line)
    return out


def format_report(rep, inert=None, title="distance from the model's own"
                                         " declared defaults"):
    """A block fit for a run log."""
    lines = ["  %s:" % title,
             "  %-12s %-14s %-14s %-18s %s"
             % ("param", "default", "fitted", "distance", "source line")]
    lines.append("  " + "-" * 76)
    far = []
    for n in sorted(rep):
        d = rep[n]
        if d["kind"] == "follows":
            lines.append("  %-12s %-14s %-14.6g %-18s parameters:%d"
                         % (n, "= " + d["default"], d["value"],
                            "tied, see paramspace", d["line"]))
            continue
        if d["kind"] == "abs":
            lines.append("  %-12s %-14.6g %-14.6g %-18s parameters:%d"
                         % (n, d["default"], d["value"],
                            "%+.4g absolute" % d.get("delta", float("nan")),
                            d["line"]))
            continue
        if d["kind"] == "log":
            if "ratio" in d:
                txt = "%.1fx %s" % (d["ratio"],
                                    "LARGER" if d["bigger"] else "SMALLER")
            else:
                txt = d.get("note", "?")
        else:
            txt = "%+.0f%%" % d.get("pct", float("nan"))
        lines.append("  %-12s %-14.6g %-14.6g %-18s parameters:%d%s"
                     % (n, d["default"], d["value"], txt, d["line"],
                        "   <-- far" if d["far"] else ""))
        if d["far"]:
            far.append(n)
    if far:
        lines.append("")
        lines.append("  FAR FROM DEFAULT (%dx for a log parameter, %d%% for a "
                     "linear one): %s" % (int(RATIO_WARN), int(PCT_WARN),
                                          ", ".join(far)))
        lines.append("  That is not wrong by itself. It is a question: does")
        lines.append("  THIS device have a reason to be that different, or has")
        lines.append("  the parameter absorbed an error belonging somewhere")
        lines.append("  else? Answer it per parameter, in writing.")
    wrong_side = []
    for n in sorted(rep):
        d = directional(n, rep[n].get("value"))
        if d and not d["ok"]:
            wrong_side.append((n, d))
    if wrong_side:
        lines.append("")
        lines.append("  ON THE WRONG SIDE OF A BOUND THE MODEL'S OWN TEXT "
                     "GIVES:")
        for n, d in wrong_side:
            lines.append("     %-10s = %-14.6g  should be %s %g"
                         % (n, d["value"], d["op"], d["bound"]))
            for chunk in _wrap(d["why"], 66):
                lines.append("                %s" % chunk)
    if inert:
        lines.append("")
        lines.append("  FITTED BUT INERT: %s" % ", ".join(inert))
        lines.append("  These were free to move and came back at a value where")
        lines.append("  their derivative is zero -- the model term they belong")
        lines.append("  to is switched off. The card now carries a confident")
        lines.append("  number for something the data cannot see. Freezing")
        lines.append("  them at the model default would fit exactly as well")
        lines.append("  and would be honest.")
    return "\n".join(lines)


# ===========================================================================
#  v1.1.9 -- INERT, BUT INERT HOW?
# ===========================================================================
#  `fitted_but_inert` above answers one question: did this parameter come
#  back at a value where its derivative is zero?  Step 10 ran it and it
#  named four -- ETAMOB, EU, MEXP and UA -- and printed the same advice for
#  all four: freeze them at the model default.
#
#  That advice is right for three of them and wrong for the fourth, and the
#  difference matters enough to be worth a function.
#
#    ETAMOB, EU, UA were inert AT THE CARD THEY WERE FITTED AT.  Step 9's
#    identifiability measured their column norms as exactly zero at the very
#    card its own fit had just produced.  They never had any business being
#    free.  Fitting them produced three confident numbers for a model term
#    that was switched off, and freezing them at the default is exactly the
#    right repair.
#
#    MEXP was NOT.  Step 10's PART 4A scan measured MEXP's SWING at 0.0402
#    on the four output curves, comfortably above the 0.01 cut, and only
#    THEN fitted it.  It moved from 4 to 13.77 and the residual on those
#    curves fell.  By PART 6 its SWING had collapsed to 0.0067 -- because
#    MEXP is the exponent in
#
#        Vdseff = vds / (1 + (vds/Vdsat)^MEXP)^(1/MEXP)      (body:1916-1918)
#
#    and that expression SATURATES: once the knee is sharp, making it
#    sharper changes nothing.  MEXP did its job and then went quiet.  Its
#    value is not wrong.  It is also not DETERMINED -- any value on the
#    plateau fits equally well -- and the honest thing to report is the
#    plateau, not the single number the search stopped on.
#
#  Freezing MEXP back at 4 because a check could not tell those two cases
#  apart would have thrown away a real gain.  So the check is taught to tell
#  them apart, using measurements the run already makes:
#
#    the SWING at the final card, over the whole objective
#    the SWING at the final card, over the sweeps the parameter was fitted on
#    the SWING at the PRE-FIT scan that authorised the fit
#
#  and it returns one of four verdicts per parameter.  No new simulations.
# ===========================================================================

SWING_CUT = 1.0e-2          # the same cut l6_verify.identifiability uses

SCOPE_TEXT = {
    "alive": "determinable on the whole objective -- nothing to do",
    "local": ("below the cut on the whole objective but ABOVE it on the "
              "sweeps it was fitted on. Real, just diluted by the other "
              "sweeps. Keep the value; say which data determines it."),
    "spent": ("above the cut when it was fitted, below it now. The fit moved "
              "it onto a PLATEAU of its own model term, so the gain was real "
              "and the final value is not determined. Keep the gain; report "
              "the plateau, not the single number."),
    "inert": ("below the cut at the card it was fitted at AND now. It never "
              "had any business being free. Freeze it at the model default "
              "-- the fit will be exactly as good and the card will be "
              "honest."),
}


def inert_scope(fitted_on, swing_now, per_sweep_now=None, swing_prefit=None,
                cut=SWING_CUT):
    """Classify every fitted parameter as alive / local / spent / inert.

    fitted_on     {param: [sweep names it was fitted on]}.  A parameter with
                  an empty or missing list is judged on the whole objective
                  alone.
    swing_now     {param: SWING at the final card, whole objective}
    per_sweep_now {param: {sweep: SWING at the final card}}  (optional)
    swing_prefit  {param: SWING measured by the scan that authorised the fit}
                  (optional)

    Returns {param: dict(verdict, swing, swing_own, swing_prefit, advice)}.
    Everything is read from numbers the run already produced; nothing here
    runs a simulation.
    """
    out = {}
    per_sweep_now = per_sweep_now or {}
    swing_prefit = swing_prefit or {}
    for name in sorted(fitted_on or {}):
        sw = swing_now.get(name) if swing_now else None
        own_sweeps = fitted_on.get(name) or []
        ps = per_sweep_now.get(name) or {}
        own = None
        vals = [ps[s] for s in own_sweeps if s in ps]
        if vals:
            own = max(float(v) for v in vals)
        pre = swing_prefit.get(name)
        rec = {"name": name, "swing": sw, "swing_own": own,
               "swing_prefit": pre, "fitted_on": list(own_sweeps)}
        if sw is None:
            rec["verdict"] = "unknown"
        elif float(sw) >= cut:
            rec["verdict"] = "alive"
        elif own is not None and own >= cut:
            rec["verdict"] = "local"
        elif pre is not None and float(pre) >= cut:
            rec["verdict"] = "spent"
        else:
            rec["verdict"] = "inert"
        rec["advice"] = SCOPE_TEXT.get(rec["verdict"])
        out[name] = rec
    return out


def format_scope_report(scope, cut=SWING_CUT,
                        title="what KIND of inert, per parameter"):
    """The printable block for `inert_scope`.  Only prints what is not fine."""
    order = {"inert": 0, "spent": 1, "local": 2, "alive": 3, "unknown": 4}
    names = sorted(scope, key=lambda n: (order.get(scope[n]["verdict"], 9), n))
    L = ["  %s (cut = %.3g):" % (title, cut),
         "  %-11s %-11s %-11s %-11s %s"
         % ("param", "SWING now", "on its own", "at the fit", "verdict"),
         "  " + "-" * 72]

    def _f(x):
        return "-" if x is None else ("%.4g" % float(x))

    for n in names:
        r = scope[n]
        L.append("  %-11s %-11s %-11s %-11s %s"
                 % (n, _f(r.get("swing")), _f(r.get("swing_own")),
                    _f(r.get("swing_prefit")), r["verdict"].upper()))
    for v in ("inert", "spent", "local"):
        hit = [n for n in names if scope[n]["verdict"] == v]
        if not hit:
            continue
        L.append("")
        L.append("  %s: %s" % (v.upper(), ", ".join(hit)))
        for line in _wrap(SCOPE_TEXT[v], 66):
            L.append("     " + line)
    if not [n for n in names if scope[n]["verdict"] in ("inert", "spent",
                                                        "local")]:
        L.append("")
        L.append("  every fitted parameter is determinable on the whole")
        L.append("  objective at the card being shipped.")
    return "\n".join(L)
