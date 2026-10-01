"""l9_report.where -- WHERE in a sweep does the error live?
(TCADOpt v1.1.13)

WHY THIS FILE EXISTS
--------------------
Every number this engine has printed so far answers "how big is the error".
None of them answers "where is it", and the two questions have completely
different consequences.

Step 15 ended with the capacitance as the biggest remaining error: 4.94% at
Vd = 50 mV and 4.52% at Vd = 0.6 V, against 1.4% on the currents. A single
number like 4.94% is compatible with three completely different faults:

  * the whole curve is 5% too high        -> a parasitic capacitance is
                                             wrong (a constant, in farads)
  * only the flat bottom is wrong          -> the overlap/fringe capacitance
  * only the flat top is wrong             -> the inversion charge, i.e. the
                                             effective width or the quantum
                                             correction
  * only the rise between them is wrong    -> the threshold, or the
                                             smoothing across it

You cannot tell which from 4.94%, and a fit cannot tell you either -- it
will happily trade one against another, which is exactly what Step 15's
PART 4 did (the 50 mV curve went from 2.46% to 4.95% while the 0.6 V curve
went from 12.29% to 4.53%).

So: split every sweep into the BANDS an engineer actually looks at, and
report the signed error in each one separately. A signed error that is the
same in every band is an offset. One that changes sign between bands is a
shape error. They are fixed by different parameters.

THE BANDS
---------
  Id-Vg   off          |Id_ref| < 1 nA/um        -- junction leakage floor
          sub          1 nA/um .. I_split        -- the sub-threshold slope
          knee         I_split .. half of Ion    -- the turn-on
          on           >= half of Ion            -- the drive current
  Id-Vd   linear       Vd < 20% of the sweep     -- the slope at the origin
          knee         20% .. 50%                -- where it bends over
          saturation   > 50%                     -- the plateau and its slope
  C-V     floor        C_ref < C0 + 15% of swing -- the parasitic floor
          rise         15% .. 85%                -- the threshold region
          plateau      >= 85%                    -- the inversion capacitance

$Id: where.py, 2026/09/27 v1.1.15 $
"""
import numpy as np

from ..l1_spec.curve_scorer import _interp_model


def _band_edges(t, ref):
    """(labels, index arrays) for one target, from the REFERENCE curve."""
    v = np.asarray(t["v"], float)
    a = np.abs(np.asarray(ref, float))
    kind = str(t.get("sweep_kind", "")).lower()
    if t.get("kind") == "cv":
        c0, c1 = float(np.min(a)), float(np.max(a))
        sw = max(c1 - c0, 1e-30)
        f = (a - c0) / sw
        return [("floor", f < 0.15), ("rise", (f >= 0.15) & (f < 0.85)),
                ("plateau", f >= 0.85)]
    if kind == "idvd":
        vmax = float(np.max(v)) if len(v) else 1.0
        f = v / max(vmax, 1e-30)
        return [("linear", f < 0.20), ("knee", (f >= 0.20) & (f < 0.50)),
                ("saturation", f >= 0.50)]
    ion = float(np.max(a)) if len(a) else 1.0
    return [("off", a < 1.0e-9),
            ("sub", (a >= 1.0e-9) & (a < 1.0e-7)),
            ("knee", (a >= 1.0e-7) & (a < 0.5 * ion)),
            ("on", a >= 0.5 * ion)]


def _usable(t, ref):
    """Points where a RATIO means something.

    An Id-Vd sweep starts at Vd = 0, where the reference current is a few
    times 1e-19 A/um -- numerical zero. The model is also near zero there,
    but the RATIO of two near-zeros is meaningless and, printed as a
    percentage, it swamps the table. So every point below a floor is left
    out of the bands: 1e-14 A/um (the scorer's own current noise floor) or
    a billionth of the sweep's own maximum, whichever is larger.
    """
    a = np.abs(np.asarray(ref, float))
    if t.get("kind") == "cv":
        return a > 0
    top = float(np.max(a)) if len(a) else 0.0
    return a > max(1.0e-14, 1.0e-9 * top)


def bands(targets, curves, i_split=1.0e-7):
    """{sweep: [{band, n, mean_pct, rms_pct, worst_pct, worst_v}]}.

    `mean_pct` is the SIGNED mean of (model/reference - 1) in percent, so a
    band that is uniformly high reads +x% and one that is uniformly low
    reads -x%. That sign is the whole point of the report.
    """
    del i_split                     # bands are fixed; see the module docstring
    out = {}
    for t in targets:
        mc = (curves or {}).get(t["name"])
        if mc is None:
            continue
        mod = _interp_model(t["v"], mc[0], mc[1])
        if mod is None:
            continue
        ref = np.abs(np.asarray(t["i"], float))
        mod = np.abs(np.asarray(mod, float))
        n = min(len(ref), len(mod))
        ref, mod = ref[:n], mod[:n]
        v = np.asarray(t["v"], float)[:n]
        rows = []
        use = _usable(t, ref)[:n]
        for label, m in _band_edges(t, ref):
            m = m[:n] & use & np.isfinite(ref) & np.isfinite(mod) & (ref > 0)
            if not m.any():
                continue
            rel = mod[m] / ref[m] - 1.0
            k = int(np.argmax(np.abs(rel)))
            rows.append({"band": label, "n": int(m.sum()),
                         "mean_pct": 100.0 * float(np.mean(rel)),
                         "rms_pct": 100.0 * float(np.sqrt(np.mean(rel * rel))),
                         "worst_pct": 100.0 * float(rel[k]),
                         "worst_v": float(v[m][k])})
        out[t["name"]] = rows
    return out


def verdict(rows, flat_pct=1.0):
    """One line saying what the SHAPE of a sweep's error is.

    offset  -- every band is wrong in the same direction by about the same
               amount: something constant is wrong (a parasitic, a width)
    tilt    -- the bands disagree in size but not in sign
    shape   -- the bands disagree in SIGN: no single constant can fix it
    """
    ms = [r["mean_pct"] for r in rows if r["n"] >= 3]
    if not ms:
        return "not enough points"
    lo, hi = min(ms), max(ms)
    if lo * hi < 0 and max(abs(lo), abs(hi)) > flat_pct:
        return "SHAPE -- the bands disagree in sign"
    if (hi - lo) <= flat_pct:
        return "OFFSET -- every band is off by about %+.1f%%" % np.mean(ms)
    return "TILT -- same sign, %+.1f%% to %+.1f%%" % (lo, hi)


def contrast(rep, a, b):
    """Band by band, how differently are two sweeps wrong? (v1.1.14)

    A model that is 13% LOW on one capacitance curve and 10% HIGH on
    another is not 11% wrong on average -- it has a 23-point SPLIT, and no
    parameter that moves both curves together can close it. This returns
    that split per band so it can be tracked as its own number.
    """
    ra = dict((r["band"], r) for r in (rep or {}).get(a, []))
    rb = dict((r["band"], r) for r in (rep or {}).get(b, []))
    out = []
    for band in [r["band"] for r in (rep or {}).get(a, [])]:
        if band not in rb:
            continue
        out.append({"band": band, "a": ra[band]["mean_pct"],
                    "b": rb[band]["mean_pct"],
                    "split": ra[band]["mean_pct"] - rb[band]["mean_pct"]})
    return out


def format_contrast(rows, a, b, title="the SPLIT between two sweeps"):
    L = ["    %s" % title,
         "    %-12s %-13s %-13s %s" % ("band", a[-12:], b[-12:],
                                       "split (a - b)"),
         "    " + "-" * 56]
    for r in rows:
        L.append("    %-12s %-+13.2f %-+13.2f %+.2f"
                 % (r["band"], r["a"], r["b"], r["split"]))
    if rows:
        w = max(rows, key=lambda r: abs(r["split"]))
        L.append("")
        L.append("    the widest split is %+.2f points, in the '%s' band."
                 % (w["split"], w["band"]))
        L.append("    A parameter that moves both sweeps the same way cannot")
        L.append("    close a split. Only one that moves them DIFFERENTLY")
        L.append("    can, and l6_verify/response.py is how you find it.")
    return "\n".join(L)


def format_report(rep, title="where the error lives, band by band"):
    L = ["  %s" % title,
         "  (mean = the signed average of model/reference - 1 in that band)",
         "",
         "  %-20s %-11s %-6s %-10s %-9s %-9s %s"
         % ("sweep", "band", "n", "mean", "rms", "worst", "at V"),
         "  " + "-" * 82]
    for name in sorted(rep):
        rows = rep[name]
        first = True
        for r in rows:
            L.append("  %-20s %-11s %-6d %-+10.2f %-9.2f %-+9.2f %.3f"
                     % ((name if first else ""), r["band"], r["n"],
                        r["mean_pct"], r["rms_pct"], r["worst_pct"],
                        r["worst_v"]))
            first = False
        L.append("  %-20s %s" % ("", verdict(rows)))
    return "\n".join(L)


def band_vector(rep, sweeps, band):
    """The signed mean error of ONE band, for a list of sweeps. (v1.1.15)

    This is the observable a two-knob solver drives to zero. `bands` already
    computes it; this just pulls the one row out of each sweep in a fixed
    order so the numbers can be treated as a vector.

    Returns [mean_pct or None, ...] in the order `sweeps` gives.
    """
    out = []
    for nm in sweeps:
        hit = None
        for r in (rep or {}).get(nm, []):
            if r["band"] == band:
                hit = float(r["mean_pct"])
                break
        out.append(hit)
    return out


def band_probe(targets, sweep, band, i_split=1.0e-7):
    """A callable(curves) -> the signed mean of one band, in percent.

    Handed to l6_verify/response.map_signed, this turns the response map
    from a distance into a direction.
    """
    tt = [t for t in targets if t["name"] == sweep]

    def probe(curves):
        rep = bands(tt, curves, i_split=i_split)
        v = band_vector(rep, [sweep], band)
        return v[0]
    return probe
