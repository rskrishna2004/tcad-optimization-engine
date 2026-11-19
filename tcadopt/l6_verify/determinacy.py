"""l6_verify.determinacy -- is a fitted value MEASURED, or is it free?

v1.1.22.  THE GAP THIS CLOSES, AND THE RUN THAT FELL INTO IT
------------------------------------------------------------
Every check this engine had until now asks about ONE parameter at a time:

    scan_swing        move this parameter across its range, everything else
                      held fixed, and see how much the residual moves
    box_adequacy      did that scan's best land on the end of the box
    confirm_dead      is the movement real or is it numerical noise

Those answer "does this parameter do anything". They do NOT answer the
question an extraction actually has to answer, which is

    "when EVERY parameter is free at once, does the data pin THIS one down,
     or can it slide a long way and have the others quietly undo it?"

Step 13 of this project fell straight into that gap, and its own terminal
says so. The per-parameter scan reported u0, vsat and vsat1 all
`determinable`. Then the fit ran and all three slid to the bottom of their
boxes together. The boxes were widened. They slid further. The step ended
with u0 = 0.0018 m2/Vs against a default of 0.03, and vsat = 10508 m/s
against a default of 85000. Each parameter was `determinable` on its own and
the three of them together were not determined at all.

WHAT THIS MODULE MEASURES
-------------------------
Near a minimum the scorer total behaves as a quadratic form in the
parameters:

    S(p0 + d) = S0 + d' H d ,        H = J' J

from which two different questions have two different answers.

  ALONE   move parameter i by itself, every other parameter FROZEN.
          The move that costs dS is      d_alone = sqrt(dS / H_ii).

  JOINT   move parameter i, and let every other parameter re-optimise to
          hide it as well as it can. The move that costs dS is now
                                     d_joint = sqrt(dS * inv(H)_ii).

Their ratio is the number that matters:

    amplification_i = d_joint / d_alone = sqrt( H_ii * inv(H)_ii )

This is the square root of the VARIANCE INFLATION FACTOR, the standard
measure of multicollinearity in least squares. It is 1 exactly when
parameter i is orthogonal to every other, and it grows without bound as the
parameter becomes a slave of the others. A VIF above 100, that is an
amplification above 10, is "severe multicollinearity" by any textbook, and
it means the fitted value of that parameter is not a measurement.

d_joint is also the honest error bar. An extraction report that quotes
"U0 = 0.0395 m2/Vs" and does not say that U0 could be anywhere in
[0.021, 0.074] without the fit getting measurably worse is not reporting a
measurement, it is reporting a coordinate.

NOTHING HERE IS EXTRAPOLATED WITHOUT BEING CHECKED
--------------------------------------------------
The algebra above is a local quadratic approximation. `measured_interval`
goes back to the real simulator and walks the parameter out until the
scorer total actually rises by the stated amount, so the predicted interval
and the measured one can be printed side by side. Where they disagree the
measured one is the answer. That is the same rule `scan_vs_derivative` and
`confirm_dead` already apply elsewhere in this engine.
"""
import math

import numpy as np

# an amplification above this is "severe" by the usual VIF >= 100 rule
SEVERE = 10.0
# and below this the parameter is effectively its own measurement
CLEAN = 3.0
# relative rise in the scorer total that defines the interval
DEFAULT_TOL = 0.01


def _coord_of(name, value, kind):
    """A parameter's own coordinate: the value for lin, its log for log.

    A Jacobian column must be taken in the coordinate the parameter is
    actually searched in, or a quantity like VSAT at 3e4 and a quantity like
    EU at 0.7 cannot be compared at all.
    """
    if kind == "log" and value is not None and value > 0:
        return math.log(float(value))
    return float(value)


def _back(name, coord, kind):
    if kind == "log":
        return math.exp(float(coord))
    return float(coord)


def hessian(J, rcond=1.0e-8):
    """H = J'J, its pseudo-inverse, and WHICH DIRECTIONS WERE DROPPED.

    The pseudo-inverse is taken through the SVD rather than by inversion,
    because H is very often rank deficient here -- that is the whole point of
    the module -- and `numpy.linalg.inv` on a singular H returns noise rather
    than an error.

    THE TRAP THE FIRST DRAFT OF THIS FUNCTION FELL INTO. A pseudo-inverse
    does not return infinity on a dead direction; it silently drops that
    direction and returns the minimum-norm answer instead. Fed two exactly
    parallel columns, the first draft reported amplification 0.2 and 0.8 --
    that is, it said the two parameters were BETTER determined together than
    separately, which is impossible. For a true inverse the Cauchy-Schwarz
    inequality guarantees H_ii * inv(H)_ii >= 1 always.

    So the dropped directions are kept and returned. Any parameter with
    weight in them is free by construction, and `determinacy` says so
    instead of quoting a number from a subspace that was thrown away.

    `rcond` is applied to the SINGULAR VALUES of J, not to their squares, and
    is reported, so the cut can be seen and argued with.
    """
    J = np.asarray(J, float)
    u, s, vt = np.linalg.svd(J, full_matrices=False)
    del u
    s = np.asarray(s, float)
    smax = float(s[0]) if len(s) and s[0] > 0 else 0.0
    keep = s > (smax * float(rcond))
    s2 = s ** 2
    H = (vt.T * s2) @ vt
    if keep.any():
        Hinv = (vt[keep].T * (1.0 / s2[keep])) @ vt[keep]
    else:
        Hinv = np.zeros_like(H)
    # how much of each parameter's own axis lies in the DROPPED subspace
    if (~keep).any():
        null_w = np.sqrt((vt[~keep] ** 2).sum(axis=0))
    else:
        null_w = np.zeros(J.shape[1])
    return {"H": H, "Hinv": Hinv, "sv": s, "Vt": vt, "keep": keep,
            "null_weight": null_w,
            "n_dead_directions": int((~keep).sum()),
            "rcond": float(rcond),
            "condition": float(s[0] / s[-1]) if len(s) and s[-1] > 0
            else float("inf")}


def determinacy(J, names, S0, kinds=None, values=None, tol=DEFAULT_TOL,
                severe=SEVERE, clean=CLEAN, rcond=1.0e-8, null_cut=1.0e-6,
                inert_frac=1.0e-6):
    """Per parameter: alone, joint, amplification, and a verdict.

    J      the Jacobian of the SCORER RESIDUAL, columns in each parameter's
           own coordinate, so that ||r||^2 is the scorer total.
    S0     the scorer total at the centre, so `tol` can be relative.
    kinds  {name: "lin"|"log"}, the coordinate each column was taken in.
    values {name: value} at the centre, so the interval can be printed in
           the parameter's own units instead of in its coordinate.

    INERT COLUMNS ARE TAKEN OUT BEFORE ANYTHING ELSE HAPPENS. A parameter
    that does not move the residual at all has a column of zeros, give or
    take floating point. Left in, it makes the matrix singular, which drives
    the condition number to infinity and makes every OTHER parameter look
    free as well -- so one switched-off parameter would hide the real
    answer for all nineteen of its neighbours. A column shorter than
    `inert_frac` of the longest one is reported INERT and excluded, and the
    spectrum below is the spectrum of what is left.

    Returns {"per": {name: {...}}, "order": [...], ...}.
    """
    J = np.asarray(J, float)
    names = list(names)
    kinds = dict(kinds or {})
    values = dict(values or {})
    dS = float(tol) * float(S0)

    norms = np.linalg.norm(J, axis=0)
    big = float(np.nanmax(norms)) if norms.size else 0.0
    live_i = [i for i in range(len(names))
              if np.isfinite(norms[i]) and norms[i] > big * float(inert_frac)]
    inert = [names[i] for i in range(len(names)) if i not in set(live_i)]
    live = [names[i] for i in live_i]
    per = {}
    for n in inert:
        i = names.index(n)
        per[n] = {"name": n, "alone": float("inf"), "joint": float("inf"),
                  "amplification": float("nan"), "verdict": "INERT",
                  "note": "this parameter does not move the residual on this "
                          "data, so nothing can be said about its value",
                  "kind": kinds.get(n, "lin"), "value": values.get(n),
                  "lo": None, "hi": None, "null_weight": 0.0,
                  "column_norm": float(norms[i])}
    if not live_i:
        return {"per": per, "order": list(names), "tol": float(tol),
                "S0": float(S0), "dS": dS, "condition": float("inf"),
                "rcond": float(rcond), "n_dead_directions": 0,
                "singular_values": [], "inert": inert, "live": [],
                "severe": float(severe), "clean": float(clean)}

    h = hessian(J[:, live_i], rcond=rcond)
    H, Hinv, nullw = h["H"], h["Hinv"], h["null_weight"]
    for j, n in enumerate(live):
        i = names.index(n)
        hii = float(H[j, j])
        gii = float(Hinv[j, j])
        kind = kinds.get(n, "lin")
        v = values.get(n)
        alone = math.sqrt(dS / hii) if hii > 0 else float("inf")
        if float(nullw[j]) > float(null_cut) or not np.isfinite(gii) \
                or gii <= 0:
            joint, amp, verdict = float("inf"), float("inf"), "FREE"
        else:
            joint = math.sqrt(dS * gii)
            amp = joint / alone if alone > 0 else float("inf")
            # Cauchy-Schwarz: this can never be below 1 for a true inverse.
            # Below 1 means the pseudo-inverse dropped a direction this
            # parameter lives in, so the honest answer is FREE.
            if amp < 1.0 - 1e-9:
                joint, amp, verdict = float("inf"), float("inf"), "FREE"
            else:
                verdict = ("DETERMINED" if amp < clean else
                           "WEAK" if amp < severe else "FREE")
        lo = hi = None
        if v is not None and np.isfinite(joint):
            c = _coord_of(n, v, kind)
            try:
                lo, hi = _back(n, c - joint, kind), _back(n, c + joint, kind)
            except (OverflowError, ValueError):
                lo = hi = None
        per[n] = {"name": n, "alone": alone, "joint": joint,
                  "amplification": amp, "verdict": verdict, "kind": kind,
                  "value": v, "lo": lo, "hi": hi, "note": "",
                  "null_weight": float(nullw[j]),
                  "column_norm": float(norms[i])}

    def _key(n):
        a = per[n]["amplification"]
        if per[n]["verdict"] == "INERT":
            return -1e300           # inert last
        return -(a if np.isfinite(a) else 1e300)
    order = sorted(names, key=_key)
    return {"per": per, "order": order, "tol": float(tol), "S0": float(S0),
            "dS": dS, "condition": h["condition"], "rcond": h["rcond"],
            "n_dead_directions": h["n_dead_directions"],
            "singular_values": [float(x) for x in h["sv"]],
            "inert": inert, "live": live,
            "severe": float(severe), "clean": float(clean)}


def format_determinacy(det, title="is each fitted value a measurement?",
                       top=None):
    """The printable table. Widest amplification first."""
    per, order = det["per"], det["order"]
    if top:
        order = order[:int(top)]
    L = ["  %s" % title,
         "    the scorer total at this card is %.6f, and an interval below"
         % det["S0"],
         "    is how far the parameter can move before that total rises by"
         "  %.3g %%." % (100.0 * det["tol"]),
         "",
         "  %-11s %-13s %-11s %-11s %-7s %s"
         % ("param", "value", "alone", "with help", "x", "verdict"),
         "  " + "-" * 74]
    for n in order:
        d = per[n]
        f = lambda x: ("%-11.4g" % x) if np.isfinite(x) else "%-11s" % "no limit"
        amp = d["amplification"]
        if d["verdict"] == "INERT":
            amp_s = "-"
        elif np.isfinite(amp):
            amp_s = "%.1f" % amp
        else:
            amp_s = "inf"
        L.append("  %-11s %-13.6g %s %s %-7s %s"
                 % (n, d["value"] if d["value"] is not None else float("nan"),
                    f(d["alone"]), f(d["joint"]), amp_s, d["verdict"]))
    L.append("  " + "-" * 74)
    L.append("    alone      how far it can move with every other parameter")
    L.append("               FROZEN, in its own coordinate (log for a log")
    L.append("               parameter, so 0.7 there means a factor of 2)")
    L.append("    with help  how far it can move when every other parameter")
    L.append("               is allowed to re-fit and hide it")
    L.append("    x          the ratio of the two. 1 means the data measures")
    L.append("               this parameter on its own. Its square is the")
    L.append("               variance inflation factor, and the usual rule")
    L.append("               calls VIF >= 100, so x >= 10, severe.")
    L.append("")
    L.append("    DETERMINED x < %.0f      the value is a measurement"
             % det["clean"])
    L.append("    WEAK       x < %.0f     the value is soft; quote the interval"
             % det["severe"])
    L.append("    FREE       x >= %.0f    the value is NOT a measurement. It"
             % det["severe"])
    L.append("               is wherever the fit happened to leave it.")
    L.append("    INERT      this parameter does not move the current at")
    L.append("               all on this data, so it is left out of the")
    L.append("               spectrum above and nothing is claimed about it.")
    bad = [n for n in det["order"] if per[n]["verdict"] == "FREE"]
    if bad:
        L.append("")
        L.append("    FREE here: %s" % ", ".join(bad))
    if det.get("inert"):
        L.append("    INERT here: %s" % ", ".join(det["inert"]))
    L.append("    condition number over the %d live parameters: %.4g"
             % (len(det.get("live") or []), det["condition"]))
    if det["n_dead_directions"]:
        L.append("    %d direction(s) in this parameter space move the model "
                 "by nothing at all." % det["n_dead_directions"])
    return "\n".join(L)


def intervals_in_units(det, names=None):
    """The reportable error bar, in the parameter's own units."""
    out = []
    for n in (names or det["order"]):
        d = det["per"].get(n)
        if not d or d["lo"] is None:
            continue
        out.append((n, d["value"], d["lo"], d["hi"], d["amplification"],
                    d["verdict"]))
    return out


def format_intervals(det, names=None,
                     title="the honest error bar on each value"):
    rows = intervals_in_units(det, names)
    L = ["  %s" % title,
         "  %-11s %-14s %-14s %-14s %s"
         % ("param", "fitted", "lower", "upper", "verdict"),
         "  " + "-" * 70]
    for n, v, lo, hi, amp, verdict in rows:
        L.append("  %-11s %-14.6g %-14.6g %-14.6g %s"
                 % (n, v, lo, hi, verdict))
    L.append("  " + "-" * 70)
    L.append("    Any value inside an interval fits this data as well as the")
    L.append("    fitted one, to within %.3g %% of the scorer total, once the"
             % (100.0 * det["tol"]))
    L.append("    other parameters are allowed to re-fit around it.")
    return "\n".join(L)


# ---------------------------------------------------------------------------
#  the measured check on the algebra above
# ---------------------------------------------------------------------------
def measured_interval(err_of, card, name, kind, lo_hi=None, tol=DEFAULT_TOL,
                      n_coarse=3, n_refine=4, span=None, bounds=None,
                      log=None, gain_cut=0.1):
    """Walk ONE parameter out until the scorer total really does rise by tol.

    `err_of(card) -> float` is the caller's own evaluator, so this function
    knows nothing about HSPICE and can be unit-tested with arithmetic.
    `bounds` is (lo, hi) in the parameter's OWN UNITS -- its declared box.

    TWO PHASES, BECAUSE EVERY POINT IS AN HSPICE RUN. A coarse walk brackets
    the crossing, then bisections close on it. Interpolating linearly across
    one coarse step instead was wrong by 5 % on a quadratic test problem,
    which is the shape every residual has near a minimum.

    THE BOX IS NOT OPTIONAL. Without it the first dry run walked VSAT to
    1.3e196 m/s, because the error happened to keep falling in that
    direction and the reach kept doubling. A saturation velocity of 1e196 is
    not a measurement of anything. Every probe is clamped to `bounds`, and
    when the walk reaches a bound without the error ever rising, that is
    reported as reaching the bound rather than as an interval.

    AND IF THE ERROR GOES DOWN, THAT IS THE ANSWER, NOT A FAILURE. A card
    sitting at a minimum gets worse in both directions. A parameter that has
    never been fitted -- and this project has four of them -- may well get
    BETTER, which says the card is not at a minimum in that direction at
    all. `improved` records the best point found and by how much, so the run
    reports it instead of chasing it.

    Returns {"up", "down", "points", "S0", "target", "improved",
             "hit_bound": {...}}.
    """
    S0 = err_of(dict(card))
    if S0 is None or not np.isfinite(S0):
        return None
    target = S0 * (1.0 + float(tol))
    v0 = float(card[name])
    c0 = _coord_of(name, v0, kind)
    c_lo = c_hi = None
    if bounds:
        try:
            c_lo = _coord_of(name, float(bounds[0]), kind)
            c_hi = _coord_of(name, float(bounds[1]), kind)
        except (ValueError, TypeError):
            c_lo = c_hi = None
    if span is None:
        base = lo_hi if (lo_hi and np.isfinite(lo_hi)) else None
        if base is None and c_lo is not None:
            base = 0.25 * (c_hi - c_lo)
        span = 4.0 * (base if base else max(abs(c0) * 0.5, 1e-3))
    pts, edges, bound_hit = [], {}, {}
    best = {"value": v0, "err": S0}
    seen = {}      # clamping makes the walk ask for the same box end twice,
                   # and on this project every ask is an HSPICE run

    def clamp(c):
        if c_lo is not None and c < c_lo:
            return c_lo, True
        if c_hi is not None and c > c_hi:
            return c_hi, True
        return c, False

    def at(c):
        c, was_clamped = clamp(c)
        try:
            v = _back(name, c, kind)
        except (OverflowError, ValueError):
            return None, None, c, was_clamped
        if kind == "log" and v <= 0:
            return None, None, c, was_clamped
        key = "%.12g" % v
        if key in seen:
            return v, seen[key], c, was_clamped
        q = dict(card)
        q[name] = v
        e = err_of(q)
        if e is None or not np.isfinite(e):
            return v, None, c, was_clamped
        seen[key] = e
        pts.append((v, e))
        if e < best["err"]:
            best["value"], best["err"] = v, e
        if log:
            log("        %-10s %-14.6g  total %.6f  (%+.3f %%)%s"
                % (name, v, e, 100.0 * ((e / S0) - 1.0),
                   "   at the box end" if was_clamped else ""))
        return v, e, c, was_clamped

    for sgn, key in ((+1.0, "up"), (-1.0, "down")):
        reach = float(span)
        lo_c, lo_e, hi_c, hi_e = c0, S0, None, None
        stop = False
        # ---- ONE probe, then a quadratic rescale ------------------------
        for _ in range(2):
            a = reach / float(n_coarse)
            v, e, cc, cl = at(c0 + sgn * a)
            if e is None:
                stop = True
                break
            if cl:
                break               # the box is closer than the step
            rise = e - S0
            if rise <= 0:
                reach *= 8.0
                continue
            scale = math.sqrt(max((target - S0) / rise, 1e-12))
            scale = min(max(scale, 1.0e-6), 1.0e6)
            if 0.45 <= scale <= 2.2:
                break
            reach = a * scale * float(n_coarse)
        if stop:
            edges[key] = None
            continue
        for k in range(1, int(n_coarse) + 1):
            c = c0 + sgn * reach * (float(k) / n_coarse)
            v, e, cc, cl = at(c)
            if e is None:
                break
            if e >= target:
                hi_c, hi_e = cc, e
                break
            lo_c, lo_e = cc, e
            if cl:
                bound_hit[key] = {"value": v, "err": e,
                                  "pct": 100.0 * (e / S0 - 1.0)}
                break
        if hi_c is None:
            edges[key] = None
            continue
        for _ in range(int(n_refine)):
            mid = 0.5 * (lo_c + hi_c)
            v, e, cc, cl = at(mid)
            if e is None:
                break
            if e >= target:
                hi_c, hi_e = cc, e
            else:
                lo_c, lo_e = cc, e
        if hi_e is not None and hi_e > lo_e:
            f = (target - lo_e) / (hi_e - lo_e)
            hit = lo_c + f * (hi_c - lo_c)
        else:
            hit = hi_c
        edges[key] = _back(name, hit, kind)
    gain = 100.0 * (1.0 - best["err"] / S0) if S0 else 0.0
    improved = (dict(best, gain_pct=gain) if gain > float(gain_cut) else None)
    return {"up": edges.get("up"), "down": edges.get("down"),
            "points": pts, "S0": S0, "target": target, "value": v0,
            "n_eval": len(pts), "improved": improved,
            "hit_bound": bound_hit}


def format_measured(name, meas, predicted=None):
    if not meas:
        return "    %-10s the walk could not be made" % name
    lo, hi = meas["down"], meas["up"]
    s = ("    %-10s fitted %-13.6g  measured interval  [%s, %s]"
         % (name, meas["value"],
            ("%.6g" % lo) if lo is not None else "below the range looked at",
            ("%.6g" % hi) if hi is not None else "above the range looked at"))
    if predicted and predicted.get("lo") is not None:
        s += ("\n    %-10s                    predicted by the algebra  "
              "[%.6g, %.6g]" % ("", predicted["lo"], predicted["hi"]))
    return s


# ---------------------------------------------------------------------------
#  the Jacobian this module needs, including the one-sided columns
# ---------------------------------------------------------------------------
def coord_jacobian(err_resid, card, names, kinds, step=0.02, one_sided=(),
                   log=None):
    """Central-difference Jacobian of the residual, in each parameter's own
    coordinate, with one-sided columns where the MODEL clamps the parameter.

    `err_resid(card) -> 1-D array` must return the residual whose sum of
    squares is the scorer total, so that H = J'J is the curvature of the
    number the gates actually judge.

    WHY ONE-SIDED COLUMNS ARE NOT OPTIONAL HERE. bsimcmg_checking.include
    clamps several parameters:

        line 162   PSAT below 2.0 is silently reset to 2.0
        line 178   UA below 0 is reset to 0
        line 183   EU below 0 is reset to 0
        line 188   UD below 0 is reset to 0
        line 197   ETAMOB below 0 is reset to 0

    This project's card sits EXACTLY on two of those clamps: psat = 2.0 and
    ud = 0. A central difference there probes 1.96 and 2.04, the simulator
    quietly turns the 1.96 back into 2.0, and the returned derivative is half
    the true one-sided slope -- with no warning anywhere, because nothing
    failed. A halved column makes a parameter look twice as weakly determined
    as it is. Naming such a parameter in `one_sided` takes the forward
    difference only and records that it did.

    Returns {"J", "names", "kinds", "used", "skipped", "one_sided"}.
    """
    cols, used, skipped, oneside = [], [], {}, []
    base = np.asarray(err_resid(dict(card)), float)
    if base is None or base.size == 0:
        return {"J": None, "names": [], "kinds": {}, "used": [],
                "skipped": {n: "no residual at the centre" for n in names},
                "one_sided": []}
    for n in names:
        if n not in card:
            skipped[n] = "not on the card"
            continue
        kind = kinds.get(n, "lin")
        v = float(card[n])
        c = _coord_of(n, v, kind)
        h = abs(c) * float(step)
        if h <= 0 or not np.isfinite(h):
            h = float(step)
        sided = (n in one_sided)
        try:
            hi = dict(card)
            hi[n] = _back(n, c + h, kind)
            r_hi = np.asarray(err_resid(hi), float)
            if sided:
                r_lo, denom = base, h
            else:
                lo = dict(card)
                lo[n] = _back(n, c - h, kind)
                r_lo = np.asarray(err_resid(lo), float)
                denom = 2.0 * h
        except Exception as exc:
            skipped[n] = "%s: %s" % (type(exc).__name__, exc)
            continue
        if r_hi is None or r_lo is None or r_hi.shape != base.shape \
                or r_lo.shape != base.shape:
            skipped[n] = "the residual changed length when this parameter moved"
            continue
        col = (r_hi - r_lo) / denom
        if not np.isfinite(col).all():
            skipped[n] = "the column came back with a value that is not finite"
            continue
        cols.append(col)
        used.append(n)
        if sided:
            oneside.append(n)
        if log:
            log("      %-11s %-5s step %-11.4g column norm %.6g%s"
                % (n, kind, h, float(np.linalg.norm(col)),
                   "   one sided (the model clamps it here)" if sided else ""))
    if not cols:
        return {"J": None, "names": [], "kinds": kinds, "used": [],
                "skipped": skipped, "one_sided": []}
    return {"J": np.column_stack(cols), "names": used, "kinds": kinds,
            "used": used, "skipped": skipped, "one_sided": oneside,
            "r0": base}


# ---------------------------------------------------------------------------
#  where the OTHER parameters have to go when you pin one of them
# ---------------------------------------------------------------------------
def profile_step(J, names, kinds, card, moves, ridge=1.0e-10, ranges=None,
                 rcond=1.0e-8, max_passes=10):
    """The compensating move for every other parameter, computed not searched.

    v1.1.23, with the two guards v1.1.25 added after a dry run showed what
    happens without them.

    WHY THIS EXISTS, IN ONE MEASUREMENT
    -----------------------------------
    Step 24 pinned nine parameters one at a time and re-fitted the rest from
    the card it already had. Six of the nine refusals were the data speaking:
    the model's default sat outside the interval the data allows, by between
    3 and 55 intervals, so no re-fit could have rescued them.

    One refusal was not. UA was asked to move 3.022 in log units against an
    allowed 4.004 -- comfortably inside -- so it should have cost 0.57 per
    cent. It cost 8.48 per cent, fifteen times more. Nothing was wrong with
    the data or the gate. The valley UA lives in is 62 times longer than it
    is wide, and a trust-region optimiser starting at the bottom of it and
    told to walk 3 natural-log units along its length does not get there.

    The direction is not a mystery, though. It is in the Hessian that
    `determinacy` already built. Split the parameters into the ones being
    pinned, p, and the rest, o. Near the minimum

        S(p0 + d) = S0 + d' H d

    and minimising over the free block for a fixed move of the pinned block
    gives, exactly,

        d_o = - inv(H_oo) H_op d_p

    which is one linear solve. That is the point the optimiser was trying to
    walk to. Handing it to the optimiser as a STARTING card instead turns a
    long walk down a narrow valley into a short polish at the bottom of it.

    THE FIRST GUARD: inv() IS THE WRONG VERB.
    H is very often rank deficient here; that is the whole subject of this
    module. A true inverse of a nearly singular H_oo sends the compensating
    step off along a direction the data cannot see at all, and the dry run
    for Step 25 showed exactly that: ud asked to go to 576, deltavsat to
    -450, psat to -178, vsat1 to 1.7e-35. Every one of those is a move along
    a direction with no curvature, so the quadratic form is indifferent to
    it and the solver picks it freely.

    The fix is the MINIMUM-NORM solution: take the pseudo-inverse through
    the SVD with an explicit `rcond`, which simply does not move along the
    directions the data cannot resolve. `info["n_dropped"]` reports how many
    were dropped so the cut can be argued with.

    THE SECOND GUARD: A BOX IS A CONSTRAINT, NOT A SUGGESTION.
    Clipping the answer afterwards is not the constrained minimum, it is an
    arbitrary point. Pass `ranges` and the step is solved as the box
    constrained quadratic programme it really is, by active set: solve, find
    which free parameters want to leave their box, fix those at the bound
    they tried to cross, and solve again for the rest. A handful of passes
    and the answer is the exact minimiser inside the boxes.

    `moves` is {name: new value in the parameter's own units}. Returns
    (new_card, info).
    """
    J = np.asarray(J, float)
    names = list(names)
    kinds = dict(kinds or {})
    ranges = dict(ranges or {})
    idx = dict((n, i) for i, n in enumerate(names))
    pin = [n for n in moves if n in idx]
    if not pin:
        return dict(card), {}
    H = J.T @ J

    def _c(n, v):
        return _coord_of(n, float(v), kinds.get(n, "lin"))

    def _box(n):
        """this parameter's box, in its own coordinate"""
        if n not in ranges:
            return -np.inf, np.inf
        kind = kinds.get(n, "lin")
        lo_u, hi_u = float(ranges[n][0]), float(ranges[n][1])
        lo = (-np.inf if (kind == "log" and lo_u <= 0) else _coord_of(n, lo_u, kind))
        hi = _coord_of(n, hi_u, kind)
        return lo, hi

    #  the displacement of each PINNED parameter, in its own coordinate.
    #  These never move again.
    pin_d = dict((n, _c(n, moves[n]) - _c(n, card[n])) for n in pin)
    active = {}          # name -> (displacement at the bound, "lo" or "hi")
    n_dropped, d_o, free, n_pass = 0, None, [], 0
    for n_pass in range(1, int(max_passes) + 1):
        held = dict(pin_d)
        for n_ in active:
            held[n_] = active[n_][0]
        free = [n for n in names if n not in held]
        io_ = [idx[n] for n in free]
        ip_ = [idx[n] for n in names if n in held]
        order_p = [n for n in names if n in held]
        if io_:
            Hoo = H[np.ix_(io_, io_)]
            Hop = H[np.ix_(io_, ip_)]
            dp = np.array([held[n] for n in order_p], float)
            tr = float(np.trace(Hoo))
            lam = (float(ridge) * tr / max(len(io_), 1)) if tr > 0.0 else 0.0
            A = Hoo + lam * np.eye(len(io_))
            u_, sv, vt = np.linalg.svd(A)
            smax = float(sv[0]) if len(sv) and sv[0] > 0 else 0.0
            #  the cut is RELATIVE to the largest singular value, with an
            #  absolute floor as well. Without the floor a free block whose
            #  curvature is zero everywhere gives singular values near the
            #  smallest number a double can hold, 1/sv overflows to infinity
            #  and the step comes back as not-a-number -- which the dry run
            #  for this step duly produced.
            cut = max(smax * float(rcond), 1.0e-300)
            keep = sv > cut
            n_dropped = int((~keep).sum())
            inv_s = np.zeros_like(sv)
            if keep.any():
                inv_s[keep] = 1.0 / sv[keep]
                d_o = -(vt.T * inv_s) @ (u_.T @ (Hop @ dp))
            else:
                d_o = np.zeros(len(io_))
            if not np.isfinite(d_o).all():
                d_o = np.where(np.isfinite(d_o), d_o, 0.0)
        else:
            d_o = np.zeros(0)
        #  the full displacement vector as it stands
        d = np.zeros(len(names))
        for n_ in held:
            d[idx[n_]] = held[n_]
        for k, n_ in enumerate(free):
            d[idx[n_]] = float(d_o[k])
        #  1) does any FREE parameter want to leave its box?
        worst, worst_gap, worst_side = None, 0.0, None
        for k, n_ in enumerate(free):
            lo, hi = _box(n_)
            c_new = _c(n_, card[n_]) + float(d_o[k])
            if c_new < lo and (lo - c_new) > worst_gap:
                worst, worst_gap, worst_side = n_, lo - c_new, "lo"
            elif c_new > hi and (c_new - hi) > worst_gap:
                worst, worst_gap, worst_side = n_, c_new - hi, "hi"
        if worst is not None:
            lo, hi = _box(worst)
            bnd = lo if worst_side == "lo" else hi
            #  keep the bound in UNITS as well. exp(log(x)) is not always x,
            #  and a bound overshot by one part in 1e16 reads downstream as a
            #  parameter outside its box.
            exact = float(ranges[worst][0] if worst_side == "lo"
                          else ranges[worst][1])
            active[worst] = (bnd - _c(worst, card[worst]), worst_side, exact)
            continue
        #  2) does any ACTIVE parameter want to come back off its bound?
        #     cost(d) = d'Hd, so the gradient is 2*H*d. At an upper bound
        #     only a decrease is feasible, so optimality needs grad <= 0
        #     there, and grad >= 0 at a lower bound. Anything else is a
        #     parameter held at a fence it does not want to be at, and
        #     releasing it lowers the cost. Without this the answer is a
        #     feasible point, not the minimum.
        g = 2.0 * (H @ d)
        scale = float(np.max(np.abs(g))) if g.size else 0.0
        tolg = max(scale * 1.0e-9, 1.0e-300)
        rel, rel_mag = None, tolg
        for n_ in list(active):
            gi = float(g[idx[n_]])
            side = active[n_][1]
            bad = (gi > rel_mag) if side == "hi" else (-gi > rel_mag)
            if bad:
                rel, rel_mag = n_, abs(gi)
        if rel is None:
            break
        active.pop(rel, None)
    #  assemble
    out = dict(card)
    for n in pin:
        out[n] = float(moves[n])
    act_val = {}
    for n in active:
        v = active[n][2] if len(active[n]) > 2 else _back(
            n, _c(n, card[n]) + active[n][0], kinds.get(n, "lin"))
        out[n] = float(v)
        act_val[n] = float(v)
    pred = {}
    for k, n in enumerate(free):
        kind = kinds.get(n, "lin")
        c = _c(n, card[n]) + float(d_o[k])
        try:
            v = _back(n, c, kind)
        except (OverflowError, ValueError):
            continue
        if kind == "log" and not (v > 0):
            continue
        if not np.isfinite(v):
            continue
        out[n] = v
        pred[n] = {"from": float(card[n]), "to": float(v),
                   "move": float(d_o[k]), "kind": kind}
    d = np.zeros(len(names))
    for n in names:
        if n in out and n in card:
            try:
                d[idx[n]] = _c(n, out[n]) - _c(n, card[n])
            except (OverflowError, ValueError):
                d[idx[n]] = 0.0
    cost = float(d @ H @ d)
    return out, {"predicted": pred, "pinned": list(pin),
                 "quadratic_cost": cost, "n_dropped": n_dropped,
                 "active": act_val, "rcond": float(rcond),
                 "n_passes": int(n_pass)}


def clip_to_boxes(card, ranges):
    """Pull every value back inside its declared box, and say which moved."""
    out, hit = dict(card), {}
    for n, rng in (ranges or {}).items():
        if n not in out:
            continue
        lo, hi = float(rng[0]), float(rng[1])
        v = float(out[n])
        if v < lo:
            out[n], hit[n] = lo, ("low", v)
        elif v > hi:
            out[n], hit[n] = hi, ("high", v)
    return out, hit


def format_profile(info, card_before, card_after, title=None, top=12):
    L = [title or "    the compensating move, computed from the Jacobian:"]
    pr = (info or {}).get("predicted") or {}
    act = (info or {}).get("active") or {}
    L.append("      %-11s %-15s %-15s %s" % ("parameter", "from", "to",
                                             "how far"))
    for n in (info or {}).get("pinned", []):
        L.append("      %-11s %-15.6g %-15.6g  PINNED"
                 % (n, card_before.get(n, float("nan")),
                    card_after.get(n, float("nan"))))
    for n in sorted(act):
        L.append("      %-11s %-15.6g %-15.6g  held at its box end"
                 % (n, card_before.get(n, float("nan")), act[n]))
    order = sorted(pr, key=lambda n: -abs(pr[n]["move"]))[:int(top)]
    for n in order:
        d = pr[n]
        L.append("      %-11s %-15.6g %-15.6g  %+.4f in %s"
                 % (n, d["from"], d["to"], d["move"], d["kind"]))
    if len(pr) > len(order):
        L.append("      ... and %d more, all moved by less than %+.4f"
                 % (len(pr) - len(order), abs(pr[order[-1]]["move"])
                    if order else 0.0))
    if info and info.get("n_dropped"):
        L.append("      %d direction(s) of the free block carried no "
                 "curvature at all," % info["n_dropped"])
        L.append("      so the step does not move along them. That is the "
                 "minimum norm")
        L.append("      answer, not a guess.")
    if act:
        L.append("      %d parameter(s) wanted to leave their declared box "
                 "and were" % len(act))
        L.append("      solved for again at the bound instead, so this IS "
                 "the lowest")
        L.append("      cost move available inside the boxes.")
    if info and "quadratic_cost" in info:
        L.append("      the quadratic form says this whole move costs %.6g"
                 % info["quadratic_cost"])
    return "\n".join(L)


# ---------------------------------------------------------------------------
#  v1.1.24  the model's own clamps decide which columns are one-sided
# ---------------------------------------------------------------------------
#  bsimcmg_checking.include silently resets several parameters when they go
#  below a floor. A central difference that probes below one of those floors
#  gets the SAME card back on the low side, so the returned slope is halved
#  and nothing anywhere reports a problem.
#
#  Step 24 handled this with a hand-written list, ONE_SIDED = ("psat", "ud"),
#  which was right for the card Step 24 started from and became WRONG the
#  moment that step fitted psat to 2.1498 and ud to 0.0341 and moved both off
#  their floors. A hand-written list is a fact about one card, pretending to
#  be a fact about the model.
#
#  This function decides it from the card in front of it instead: for every
#  parameter it works out the point the central difference would actually
#  probe, compares that against the floor the model declares, and takes the
#  column one-sided only where the probe would really be clamped.
BSIMCMG_FLOORS = {
    #  Every entry below was read out of bsimcmg_checking.include and kept
    #  ONLY where the model actually CHANGES the value. CDSC and CDSCD print
    #  a warning when they go negative (lines 110 and 114) and then leave the
    #  value alone, so they are not clamps and are not listed: a warning that
    #  does not alter the card cannot halve a derivative.
    #
    #  name:        (floor, strict, the line the test is on, what it becomes)
    "vsat":         (0.0,  True,   85, "FATAL, reset to 8.5e4"),
    "vsat1":        (0.0,  True,   90, "FATAL, reset to 8.5e4"),
    "psat":         (2.0,  False, 162, "reset to 2.0"),
    "psatcv":       (2.0,  False, 167, "reset to 2.0"),
    "u0":           (0.0,  False, 172, "reset to the default 0.03"),
    "ua":           (0.0,  False, 177, "reset to 0"),
    "eu":           (0.0,  False, 182, "reset to 0"),
    "ud":           (0.0,  False, 187, "reset to 0"),
    "etamob":       (0.0,  False, 197, "reset to 0"),
    "rdsw":         (0.0,  False, 202, "reset to 0"),
    "mexp":         (2.0,  False, 269, "reset to 2.0"),
    #  not a checking.include clamp: bsimcmg_body.include 2340 takes
    #  ln(DELTAVSAT + T0), so the argument has to stay positive
    "deltavsat":    (0.0,  True, 2340, "ln() would be undefined"),
}


def clamp_aware_one_sided(card, names, kinds, step=0.02, floors=None,
                          guard=1.0e-12):
    """Which Jacobian columns MUST be one-sided, decided from this card.

    v1.1.24.  Returns (tuple_of_names, rows) where each row is
    (name, low_probe, floor, sided, line) so the decision can be printed and
    argued with rather than taken on trust.

    `step` must be the same step `coord_jacobian` will use, or the probe
    point this function checks is not the probe point that gets taken.
    """
    floors = dict(BSIMCMG_FLOORS if floors is None else floors)
    out, rows = [], []
    for n in list(names):
        if n not in card:
            continue
        kind = (kinds or {}).get(n, "lin")
        v = float(card[n])
        c = _coord_of(n, v, kind)
        h = abs(c) * float(step)
        if h <= 0 or not np.isfinite(h):
            h = float(step)
        try:
            lo = _back(n, c - h, kind)
        except (OverflowError, ValueError):
            lo = float("nan")
        if n not in floors:
            rows.append((n, lo, None, False, None))
            continue
        fl, strict, line = floors[n][0], floors[n][1], floors[n][2]
        sided = (lo <= fl + guard) if strict else (lo < fl - guard)
        #  a log parameter can never reach a floor of zero by stepping in log
        if kind == "log" and fl <= 0.0:
            sided = False
        if sided:
            out.append(n)
        rows.append((n, lo, fl, bool(sided), line))
    return tuple(out), rows


def format_clamps(rows, title=None):
    L = [title or "    the model's floors against the probe point each "
                  "column would take:"]
    L.append("      %-11s %-15s %-10s %-6s %s"
             % ("parameter", "low probe", "floor", "line", "column"))
    for n, lo, fl, sided, line in rows:
        if fl is None:
            continue
        L.append("      %-11s %-15.6g %-10.6g %-6s %s"
                 % (n, lo, fl, ("%d" % line) if line else "-",
                    "ONE SIDED -- the model would clamp it" if sided
                    else "two sided, clear of the floor"))
    return "\n".join(L)


def scale_to_budget(J, names, kinds, card, targets, budget, ridge=1.0e-10,
                    ranges=None, rcond=1.0e-8):
    """Move toward `targets` exactly as far as the error budget allows.

    v1.1.24.  `profile_step` answers "pin these values and the rest follows".
    This answers the question that matters when the pinned values are OUTSIDE
    what the data permits: how far toward them can the card go before the
    error rises by `budget`?

    The compensating step is linear in the displacement, so the whole move
    scales as d(t) = t * d(1) and its quadratic cost is exactly

        cost(t) = t^2 * cost(1)

    which gives t = sqrt(budget / cost(1)) in closed form. No search, no
    guessing, and the predicted cost is the budget by construction.

    Returns (new_card, info) with info["t"] the scale that was used and
    info["targets_scaled"] the values actually pinned. t is capped at 1, so a
    target already inside the budget is taken whole.
    """
    _, info1 = profile_step(J, names, kinds, card, targets, ridge=ridge,
                            ranges=ranges, rcond=rcond)
    c1 = float(info1.get("quadratic_cost", 0.0) or 0.0)
    if c1 <= 0.0:
        t = 1.0
    else:
        t = min(1.0, math.sqrt(max(float(budget), 0.0) / c1))
    scaled = {}
    for n in targets:
        if n not in card:
            continue
        kind = (kinds or {}).get(n, "lin")
        c0 = _coord_of(n, float(card[n]), kind)
        ct = _coord_of(n, float(targets[n]), kind)
        scaled[n] = _back(n, c0 + t * (ct - c0), kind)
    out, info = profile_step(J, names, kinds, card, scaled, ridge=ridge,
                             ranges=ranges, rcond=rcond)
    info["t"] = float(t)
    info["targets_full"] = dict(targets)
    info["targets_scaled"] = dict(scaled)
    info["cost_full"] = c1
    info["budget"] = float(budget)
    return out, info
