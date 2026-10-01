"""l6_verify.response -- the 1-D response map: what does ONE parameter do to
EACH curve, across its whole range?  (TCADOpt v1.1.15)

WHY THIS FILE EXISTS
--------------------
Step 16 ended with one error it could not touch: the gate capacitance is
13.1% BELOW the device at Vd = 50 mV and 9.7% ABOVE it at Vd = 0.6 V. No
parameter in the fit could close that split, and three separate
measurements said so.

The parameter that can was in the same run's census all along:

    pclmcv = 1     C-V at 50 mV  0.02117     C-V at 0.6 V  0.4675
                   the current                             0 (exact)

Twenty-one times more effect on one capacitance curve than on the other,
and not one bit of change in any current. That is precisely a knob for the
split -- and the fit never moved it, because a Levenberg-Marquardt step is
LOCAL: at PCLMCV = 0.0056 the slope it measures is almost exactly zero, so
the step it computes is almost exactly nothing. The parameter is not dead;
the fit is standing in a flat spot a long way from where the action is.

A gradient cannot see that. A MAP can: evaluate the parameter right across
its declared range, and report what EVERY curve does at every point --
separately, never summed. Then you can see three things a single error
number hides:

  * where each curve's own best value is;
  * whether the curves AGREE (one value suits them all: a free win) or
    CONFLICT (they want different values: a trade you must make on
    purpose, not by accident);
  * whether the current best is in a flat region a local fit cannot
    escape, which is the diagnosis for exactly the failure above.

It costs one batch of n evaluations and it is the cheapest honest thing in
this engine.

$Id: response.py, 2026/09/27 v1.1.15 $
"""
import numpy as np


def _grid(rng, n):
    lo, hi, mode = float(rng[0]), float(rng[1]), str(rng[2]).lower()
    n = max(int(n), 3)
    if mode == "log" and lo > 0 and hi > 0:
        return list(np.exp(np.linspace(np.log(lo), np.log(hi), n)))
    return list(np.linspace(lo, hi, n))


def map1d(evaluate, scorers, card, name, rng, n_points=13, tag="map",
          post=None, wrap=None, include_centre=True, blowup=1.0e3):
    """Sweep ONE parameter across its whole box and score every curve.

    evaluate : evaluate_batch(cards, tag) -> results
    scorers  : ordered list of (label, scorer) -- one per curve you want
               reported SEPARATELY. A scorer is the usual
               callable(curves) -> negative-is-worse score.
    card     : the card to vary (every other parameter held)
    rng      : (lo, hi, 'lin'|'log') -- the parameter's declared box
    post     : optional callable(card)->card for model ties (CFD = CFS)
    wrap     : optional callable(card)->card the evaluator wants
               (a step script's structure block)
    blowup   : an error bigger than this is not a score, it is the model
               coming apart. v1.1.15: Step 17 mapped CGSL, CGDL and CGBN
               and got errors of 2.6e+09, 1.3e+09 and 4.0e+08 -- the
               capacitance had gone to something like a nanofarad -- and
               the ranking then quietly treated those as ordinary numbers.
               Such a point is now recorded as BROKEN, not scored, and a
               parameter with any broken point gets the verdict BREAKS so
               that no later stage seeds a fit from it.

    Returns a dict: values, err {label: [...]}, best {label: value},
    best_err, centre, centre_err, n_broken, verdict.
    """
    xs = _grid(rng, n_points)
    p0 = float(card.get(name, xs[0]))
    if include_centre and not any(abs(x - p0) <= 1e-12 * max(abs(p0), 1e-30)
                                  for x in xs):
        xs.append(p0)
        xs.sort()
    cards = []
    for x in xs:
        c = dict(card)
        c[name] = float(x)
        if post is not None:
            c = post(c)
        cards.append(wrap(c) if wrap is not None else c)
    res = evaluate(cards, tag)
    out = {"name": name, "values": [float(x) for x in xs], "centre": p0,
           "err": {}, "best": {}, "best_err": {}, "centre_err": {},
           "n_points": len(xs), "n_broken": 0, "broken_at": []}
    for label, sc in scorers:
        col = []
        for k_, r in enumerate(res):
            e = None
            if r is not None and r.get("status") in ("ok", "partial"):
                try:
                    v = sc(r.get("curves"))
                    if v is not None and np.isfinite(v) and v > -1e8:
                        e = -float(v)
                except Exception:
                    e = None
            if e is not None and blowup is not None and e > float(blowup):
                out["n_broken"] += 1
                if xs[k_] not in out["broken_at"]:
                    out["broken_at"].append(float(xs[k_]))
                e = None
            col.append(e)
        out["err"][label] = col
        good = [(e, x) for e, x in zip(col, xs) if e is not None]
        if good:
            e_b, x_b = min(good)
            out["best"][label] = float(x_b)
            out["best_err"][label] = float(e_b)
        k0 = int(np.argmin([abs(x - p0) for x in xs]))
        out["centre_err"][label] = col[k0]
    bests = [out["best"][l] for l, _ in scorers if l in out["best"]]
    if out["n_broken"]:
        out["spread"] = None
        out["verdict"] = "BREAKS"
    elif len(bests) >= 2:
        lo_, hi_ = min(bests), max(bests)
        spread = (hi_ / lo_) if (lo_ > 0 and hi_ > 0) else abs(hi_ - lo_)
        out["spread"] = float(spread)
        same = all(abs(b - bests[0]) <= 1e-12 * max(abs(bests[0]), 1e-30)
                   for b in bests)
        out["verdict"] = "agree" if same else "CONFLICT"
    else:
        out["spread"] = None
        out["verdict"] = "one curve only"
    # is the centre in a flat spot? compare the local slope with the range
    lab0 = scorers[0][0] if scorers else None
    if lab0:
        col = [e for e in out["err"][lab0] if e is not None]
        if len(col) >= 3:
            out["range_err"] = float(max(col) - min(col))
    return out


def joint_best(rep, labels=None, weights=None):
    """The grid point with the lowest SUM of the listed curves' errors --
    the best single value for all of them at once, which is not in general
    any one curve's own best."""
    labels = labels or list(rep["err"].keys())
    w = weights or dict((l, 1.0) for l in labels)
    tot = []
    for k, x in enumerate(rep["values"]):
        s, ok = 0.0, True
        for l in labels:
            e = rep["err"][l][k]
            if e is None:
                ok = False
                break
            s += w.get(l, 1.0) * e
        tot.append(s if ok else None)
    good = [(s, x) for s, x in zip(tot, rep["values"]) if s is not None]
    if not good:
        return None, None, tot
    s_b, x_b = min(good)
    return float(x_b), float(s_b), tot


def format_map(rep, labels=None, title=None):
    labels = labels or list(rep["err"].keys())
    L = ["    %s" % (title or ("the response of every curve to %s, right"
                              " across its range" % rep["name"]))]
    head = "    %-14s" % rep["name"] + "".join("%-13s" % l for l in labels)
    L.append(head)
    L.append("    " + "-" * max(len(head) - 4, 20))
    xb, _sb, tot = joint_best(rep, labels)
    for k, x in enumerate(rep["values"]):
        mark = ""
        if abs(x - rep["centre"]) <= 1e-12 * max(abs(rep["centre"]), 1e-30):
            mark += " <- where the card sits"
        if xb is not None and abs(x - xb) <= 1e-12 * max(abs(xb), 1e-30):
            mark += "  <- best for both"
        cells = []
        for l in labels:
            e = rep["err"][l][k]
            cells.append("%-13s" % ("-" if e is None else "%.5f" % e))
        L.append("    %-14.6g%s%s" % (x, "".join(cells), mark))
    L.append("")
    for l in labels:
        if l in rep["best"]:
            L.append("    %-22s wants %-14.6g (error %.5f)"
                     % (l, rep["best"][l], rep["best_err"][l]))
    if rep.get("verdict") == "CONFLICT":
        L.append("")
        L.append("    THESE CURVES WANT DIFFERENT VALUES. Whatever is chosen")
        L.append("    is a trade, and it should be made on the whole")
        L.append("    objective with the gate watching, not by whichever")
        L.append("    stage happens to run last.")
    elif rep.get("verdict") == "agree":
        L.append("")
        L.append("    every curve wants the same value: this one is free.")
    return "\n".join(L)


def refine(rep, label, rng=None):
    """The minimum of a PARABOLA through the three points around the grid
    best -- not the grid point itself.  (v1.1.15)

    Step 17's PART 4 seeded every parameter at the best point of a
    thirteen-point grid, and the two capacitance sweeps went from 0.04726
    to 0.04808 before a single fit iteration had run. Part of that is the
    grid: DELTAWCV's own map said 6.875e-08 when the card sat at
    6.8615874e-08, and the difference is entirely the grid spacing. A
    parabola through the bracketing three points costs nothing and lands
    where the curve actually turns.

    Returns (x_refined, was_refined). Falls back to the grid best at an
    end point, on a flat triple, or when a point is missing.
    """
    xs = rep.get("values") or []
    col = (rep.get("err") or {}).get(label)
    if not xs or not col:
        return None, False
    good = [(e, k) for k, e in enumerate(col) if e is not None]
    if not good:
        return None, False
    _e, k = min(good)
    if k <= 0 or k >= len(xs) - 1:
        return float(xs[k]), False
    y0, y1, y2 = col[k - 1], col[k], col[k + 1]
    x0, x1, x2 = float(xs[k - 1]), float(xs[k]), float(xs[k + 1])
    if y0 is None or y2 is None:
        return float(x1), False
    d = (x0 - x1) * (x0 - x2) * (x1 - x2)
    if abs(d) < 1e-300:
        return float(x1), False
    a = (x2 * (y1 - y0) + x1 * (y0 - y2) + x0 * (y2 - y1)) / d
    b = (x2 * x2 * (y0 - y1) + x1 * x1 * (y2 - y0)
         + x0 * x0 * (y1 - y2)) / d
    if a <= 0 or not np.isfinite(a) or not np.isfinite(b):
        return float(x1), False
    xr = -b / (2.0 * a)
    lo, hi = min(x0, x2), max(x0, x2)
    if not (lo <= xr <= hi):
        return float(x1), False
    if rng is not None:
        xr = min(max(xr, float(rng[0])), float(rng[1]))
    return float(xr), True


def map_signed(evaluate, probes, card, name, rng, n_points=9, tag="sgn",
               post=None, wrap=None, include_centre=True):
    """The same sweep, but reporting a SIGNED physical number per point.

    An error is a distance: it says how far, never which way. Two knobs
    that both make the error on one curve go up can still be moving the
    curve in OPPOSITE directions, and only a signed quantity shows it. The
    split this project is stuck on -- the capacitance 13% LOW at 50 mV and
    9% HIGH at 0.6 V -- cannot be reasoned about with distances at all.

    `probes` is an ordered list of (label, callable(curves) -> float) where
    the float is a signed physical reading, e.g. the mean of
    model/reference - 1 in the plateau band of one sweep. The report adds a
    finite-difference SENSITIVITY at the card's own value, which is exactly
    the column a two-knob solver needs.

    Returns {name, values, sig {label: [...]}, centre, centre_sig,
             slope {label: d(sig)/d(param) at the centre}}.
    """
    xs = _grid(rng, n_points)
    p0 = float(card.get(name, xs[0]))
    if include_centre and not any(abs(x - p0) <= 1e-12 * max(abs(p0), 1e-30)
                                  for x in xs):
        xs.append(p0)
        xs.sort()
    cards = []
    for x in xs:
        c = dict(card)
        c[name] = float(x)
        if post is not None:
            c = post(c)
        cards.append(wrap(c) if wrap is not None else c)
    res = evaluate(cards, tag)
    out = {"name": name, "values": [float(x) for x in xs], "centre": p0,
           "sig": {}, "centre_sig": {}, "slope": {}, "n_points": len(xs)}
    k0 = int(np.argmin([abs(x - p0) for x in xs]))
    for label, pr in probes:
        col = []
        for r in res:
            v = None
            if r is not None and r.get("status") in ("ok", "partial"):
                try:
                    v = pr(r.get("curves"))
                    v = None if v is None or not np.isfinite(v) \
                        else float(v)
                except Exception:
                    v = None
            col.append(v)
        out["sig"][label] = col
        out["centre_sig"][label] = col[k0]
        ka = max(k0 - 1, 0)
        kb = min(k0 + 1, len(xs) - 1)
        if col[ka] is not None and col[kb] is not None and kb > ka:
            dx = float(xs[kb]) - float(xs[ka])
            out["slope"][label] = ((col[kb] - col[ka]) / dx) if dx else None
        else:
            out["slope"][label] = None
    return out


def format_signed(rep, labels=None, units="%", title=None):
    labels = labels or list(rep["sig"].keys())
    w = max([20] + [len(str(l)) + 2 for l in labels])
    L = ["    %s" % (title or ("what %s does to each reading, SIGNED, right"
                              " across its range" % rep["name"]))]
    head = "    %-14s" % rep["name"] + "".join(("%-" + str(w) + "s") % l
                                               for l in labels)
    L.append(head)
    L.append("    " + "-" * max(len(head) - 4, 20))
    for k, x in enumerate(rep["values"]):
        mark = ""
        if abs(x - rep["centre"]) <= 1e-12 * max(abs(rep["centre"]), 1e-30):
            mark = " <- where the card sits"
        cells = []
        for l in labels:
            v = rep["sig"][l][k]
            cells.append(("%-" + str(w) + "s")
                         % ("-" if v is None
                            else ("%+.6g%s" % (v, units))))
        L.append("    %-14.6g%s%s" % (x, "".join(cells), mark))
    L.append("")
    L.append("    the SENSITIVITY at the card's own value"
             " (change in the reading per unit of %s):" % rep["name"])
    for l in labels:
        sl = rep["slope"].get(l)
        L.append("      %-22s %s" % (l, "-" if sl is None
                                     else "%+.6g %s per unit" % (sl, units)))
    return "\n".join(L)


def switch_compare(rep_by_mode, knobs, reading, min_ratio=5.0,
                   min_abs=0.05):
    """Is a parameter alive at one switch setting and dead at another?

    STEP 20 ASKED THIS AND GOT THE ANSWER WRONG, BY SUMMING
    -------------------------------------------------------
    Step 20's PART 4A measured the swing of four parameters at CVMOD = 0 and
    at CVMOD = 1 and compared the TOTALS. One of the four, PCLMCV, swings 47
    points at both settings; the other three swing hundredths. The totals
    were 47.03 and 53.58, the run concluded "the family already acts", and
    the one real result in the table was buried: VSATCV went from 0.0319
    points to 6.4542 -- a factor of 202 -- which is the whole question that
    experiment existed to answer.

    A verdict about a PARAMETER has to be computed per parameter. This does
    that, and returns one row each.

    `rep_by_mode` : {mode_value: {knob: swing}} -- the swing of `reading`
                    over each knob's own box, at that switch setting.
    Returns [{name, by_mode, best_mode, ratio, verdict}] sorted by ratio.
    """
    modes = sorted(rep_by_mode)
    out = []
    for k in knobs:
        vals = dict((m, float(abs(rep_by_mode[m].get(k, 0.0))))
                    for m in modes)
        best = max(modes, key=lambda m: vals[m])
        worst = min(modes, key=lambda m: vals[m])
        lo, hi = vals[worst], vals[best]
        ratio = (hi / lo) if lo > 1e-12 else (float("inf") if hi > 1e-12
                                              else 1.0)
        if hi < min_abs:
            verdict = "dead at every setting"
        elif ratio >= min_ratio:
            verdict = "ALIVE only at %s (x%.0f)" % (best, min(ratio, 9.9e4))
        else:
            verdict = "acts at every setting"
        out.append({"name": k, "by_mode": vals, "best_mode": best,
                    "ratio": float(ratio), "verdict": verdict})
    out.sort(key=lambda z: -(z["ratio"] if np.isfinite(z["ratio"]) else 1e9))
    return out


def format_switch_compare(rows, switch="cvmod", units=""):
    if not rows:
        return "    (nothing to compare)"
    modes = sorted(rows[0]["by_mode"])
    L = ["    what each knob can do, at each setting of %s" % switch,
         "    %-14s %s %s"
         % ("knob", "".join("%-16s" % ("%s = %s" % (switch, m))
                            for m in modes), "verdict"),
         "    " + "-" * (16 + 16 * len(modes) + 28)]
    for z in rows:
        L.append("    %-14s %s %s"
                 % (z["name"],
                    "".join("%-16.4f" % z["by_mode"][m] for m in modes),
                    z["verdict"]))
    return "\n".join(L)
