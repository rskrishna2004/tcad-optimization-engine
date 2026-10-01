"""l9_report.gaterow -- Cgg is three capacitances. Report the three.
(TCADOpt v1.1.16 -- new)

WHY THIS FILE EXISTS
--------------------
For five steps this project has been stuck on one number: the gate
capacitance is about 13% BELOW the reference at Vd = 50 mV and about 9% ABOVE
it at Vd = 0.6 V, a 22.7-point SPLIT that no parameter could close. Step 18
finished the search honestly: every capacitance parameter the model has was
censused with two controls, mapped with signed sensitivities, and put through
a two-knob solver, and the arithmetic's own verdict was that the best
available pair could move the two readings by 0.02 and 0.06 points. There is
no capacitance parameter that closes it.

The reason was in the reference data all along, in a column nobody read.

`targets/cv_targets.csv` does not hold one capacitance. It holds four:
Cgg_F, Cgd_F, Cgs_F, Cgb_F, with a closure column that reads 0.000002%.
Step 1 summed them and every step since has fitted the sum. Here is what the
parts say, at Vg = 0.6 V, from that file:

                 Vd = 50 mV      Vd = 0.60 V      change
    Cgg          59.441 aF       45.135 aF        -24.1%
    Cgd          28.570 aF       14.426 aF        -49.5%
    Cgs          29.465 aF       29.200 aF         -0.9%
    Cgb           1.406 aF        1.509 aF         +7.3%

Every bit of the 14.3 aF that Cgg loses between the two drain biases is lost
by Cgd. Cgs moves by a quarter of an attofarad and Cgb by a tenth.

And Cgd does not just fall -- it falls to its own OFF-STATE value. At Vg = 0
this device measures Cgd = 13.821 aF, which is overlap and fringe, no channel
at all. At Vg = 0.6 and Vd = 0.6 it measures 14.426 aF. So of the 14.749 aF
of channel charge the drain end holds in the linear region, 14.14 aF -- 96% of
it -- is gone in saturation. That is the drain end of the channel pinching
off, and it is the single most basic thing a compact model's charge
partition has to reproduce.

A model whose Cgg falls by only 4% across the same bias change is not
mis-parameterised. It is putting the channel charge in the wrong place. No
amount of fitting the SUM can find that, because the sum is the one quantity
in which the error partly cancels.

This module puts the four model curves beside the four reference curves and
says, per terminal, which one is wrong.

$Id: gaterow.py, 2026/09/28 v1.1.16 $
"""
import numpy as np

TERMS = ("cgg", "cgd", "cgs", "cgb")


def _at(v, y, x):
    """y interpolated at gate bias x."""
    v = np.asarray(v, float)
    y = np.asarray(y, float)
    o = np.argsort(v)
    return float(np.interp(float(x), v[o], y[o]))


def reference_row(targets_csv, device="nsfet_n", vd=0.05, usable_only=True):
    """The four reference curves for one drain bias, out of the targets CSV.

    Returns {"vg": [...], "cgg": [...], "cgd": [...], "cgs": [...],
             "cgb": [...]} in FARADS, all positive, or None.

    The CSV stores Cgd, Cgs and Cgb as negative numbers -- they are the
    off-diagonal entries of the capacitance matrix and that is the correct
    sign for them. The magnitude is what is compared here, and the sign
    convention is checked by the closure: |Cgd| + |Cgs| + |Cgb| must equal
    Cgg, which in this file it does to two parts in a hundred million.
    """
    import csv
    rows = []
    try:
        fh = open(targets_csv)
    except Exception:
        return None
    with fh:
        for r in csv.DictReader(fh):
            if (r.get("device") or "").strip() != device:
                continue
            try:
                if abs(float(r["vd"]) - float(vd)) > 1e-9:
                    continue
            except Exception:
                continue
            if usable_only and (r.get("usable") or "yes").strip().lower() \
                    not in ("yes", "1", "true"):
                continue
            rows.append(r)
    if not rows:
        return None
    need = ("Cgg_F", "Cgd_F", "Cgs_F", "Cgb_F")
    if not all(k in rows[0] for k in need):
        return None
    rows.sort(key=lambda r: float(r["vg"]))
    out = {"vg": np.asarray([float(r["vg"]) for r in rows], float)}
    for name, col in zip(TERMS, need):
        out[name] = np.abs(np.asarray([float(r[col]) for r in rows], float))
    tot = out["cgd"] + out["cgs"] + out["cgb"]
    out["closure_pct"] = 100.0 * (tot - out["cgg"]) \
        / np.maximum(np.abs(out["cgg"]), 1e-30)
    return out


def compare(model, ref, at_vg=0.60):
    """Model against reference, per terminal, at one gate bias.

    Returns [{"term", "model", "ref", "err_pct"}] in farads.
    """
    out = []
    for t in TERMS:
        if t not in model or t not in ref:
            continue
        m = abs(_at(model["vg"], model[t], at_vg))
        r = abs(_at(ref["vg"], ref[t], at_vg))
        out.append({"term": t, "model": m, "ref": r,
                    "err_pct": (100.0 * (m / r - 1.0)) if r > 0 else None})
    return out


def intrinsic(row, vg_off=None):
    """Each terminal's CHANNEL charge: its value minus its own off-state one.

    At a gate bias well below threshold there is no channel, so whatever
    capacitance is left is overlap, fringe and outer-fringe -- the parasitics.
    Subtracting it leaves the part the channel actually contributes, which is
    the part a charge-partition model is responsible for. Reporting the raw
    numbers instead hides a 50% channel error inside a 25% total.
    """
    out = {}
    v = np.asarray(row["vg"], float)
    k = int(np.argmin(v)) if vg_off is None else \
        int(np.argmin(np.abs(v - float(vg_off))))
    for t in TERMS:
        if t not in row:
            continue
        y = np.abs(np.asarray(row[t], float))
        out[t] = y - y[k]
        out[t + "_floor"] = float(y[k])
    out["vg"] = v
    out["vg_off"] = float(v[k])
    return out


def collapse(row_lo, row_hi, at_vg=0.60, vg_off=None):
    """How much of each terminal's CHANNEL charge survives at high drain bias.

    1.00 means the drain end is as full as it was in the linear region;
    0.00 means it is completely pinched off. This one number is what the
    split is made of, and the model and the device can be asked for it
    separately and compared.
    """
    a = intrinsic(row_lo, vg_off)
    b = intrinsic(row_hi, vg_off)
    out = []
    for t in TERMS:
        if t not in a or t not in b:
            continue
        lo = _at(a["vg"], a[t], at_vg)
        hi = _at(b["vg"], b[t], at_vg)
        out.append({"term": t, "lin": lo, "sat": hi,
                    "kept": (hi / lo) if abs(lo) > 1e-30 else None})
    return out


def format_compare(rows_lo, rows_hi, at_vg=0.60,
                   title="the gate row, model against your device"):
    L = ["  %s, at Vg = %.2f V" % (title, at_vg),
         "  (every number in aF = 1e-18 F)",
         "",
         "  %-6s %-24s %-24s"
         % ("", "Vd = 0.05 V", "Vd = 0.60 V"),
         "  %-6s %-11s %-12s %-11s %-12s %s"
         % ("term", "your device", "the model", "your device", "the model",
            "the model's error"),
         "  " + "-" * 78]
    byt = {}
    for r in rows_lo:
        byt.setdefault(r["term"], {})["lo"] = r
    for r in rows_hi:
        byt.setdefault(r["term"], {})["hi"] = r
    for t in TERMS:
        if t not in byt:
            continue
        a, b = byt[t].get("lo"), byt[t].get("hi")
        if a is None or b is None:
            continue
        L.append("  %-6s %-11.4f %-12.4f %-11.4f %-12.4f %+.1f%% / %+.1f%%"
                 % (t.upper(), a["ref"] * 1e18, a["model"] * 1e18,
                    b["ref"] * 1e18, b["model"] * 1e18,
                    a["err_pct"] or 0.0, b["err_pct"] or 0.0))
    return "\n".join(L)


def format_collapse(dev, mod, at_vg=0.60,
                    title="the CHANNEL charge each terminal keeps when the"
                          " drain goes to 0.6 V"):
    L = ["  %s" % title,
         "  (the parasitic floor of each terminal has been subtracted first,",
         "   so this is the part the charge model is responsible for)",
         "",
         "  %-6s %-13s %-13s %-9s %-13s %-13s %s"
         % ("term", "device lin", "device sat", "kept", "model lin",
            "model sat", "kept"),
         "  " + "-" * 82]
    md = dict((r["term"], r) for r in (mod or []))
    for r in (dev or []):
        t = r["term"]
        m = md.get(t)
        L.append("  %-6s %-13.4f %-13.4f %-9s %-13s %-13s %s"
                 % (t.upper(), r["lin"] * 1e18, r["sat"] * 1e18,
                    "-" if r["kept"] is None else "%.3f" % r["kept"],
                    "-" if m is None else "%.4f" % (m["lin"] * 1e18),
                    "-" if m is None else "%.4f" % (m["sat"] * 1e18),
                    "-" if (m is None or m["kept"] is None)
                    else "%.3f" % m["kept"]))
    L.append("")
    L.append("  'kept' is the fraction of the linear-region channel charge")
    L.append("  that is still there in saturation. For the DRAIN it should be")
    L.append("  close to zero -- that is what pinch-off means. A model that")
    L.append("  keeps most of it has its channel charge in the wrong place,")
    L.append("  and no capacitance parameter can move charge from one")
    L.append("  terminal to another.")
    return "\n".join(L)


def format_row(row, name, at=(0.0, 0.2, 0.4, 0.5, 0.6)):
    L = ["    %s" % name,
         "    %-8s %-12s %-12s %-12s %-12s %s"
         % ("Vg", "Cgg[aF]", "Cgd[aF]", "Cgs[aF]", "Cgb[aF]", "Cgd/Cgg"),
         "    " + "-" * 68]
    for x in at:
        gg = abs(_at(row["vg"], row["cgg"], x))
        gd = abs(_at(row["vg"], row["cgd"], x))
        gs = abs(_at(row["vg"], row["cgs"], x))
        gb = abs(_at(row["vg"], row["cgb"], x))
        L.append("    %-8.3f %-12.4f %-12.4f %-12.4f %-12.4f %.4f"
                 % (x, gg * 1e18, gd * 1e18, gs * 1e18, gb * 1e18,
                    gd / max(gg, 1e-30)))
    if "closure_pct" in row:
        c = np.abs(np.asarray(row["closure_pct"], float))
        L.append("")
        L.append("    closure |Cgd+Cgs+Cgb - Cgg| / Cgg: worst %.6f%%"
                 % float(np.max(c)) if len(c) else "")
    return "\n".join(L)


# ==========================================================================
#  THE MODEL'S OWN ROW, AND THE SIDE-BY-SIDE TABLE   (TCADOpt v1.1.17)
# ==========================================================================
def model_row(curves, base):
    """Pull one model gate row out of an evaluation's `curves` dict.

    `curves` is what `HSpiceEvaluator` returns: {name: (v, y)}. A C-V sweep
    `nsfet_n_CV_0.05` carries its parts alongside it as `...#cgd`, `...#cgs`
    and `...#cgb`. Returns the same dict shape `reference_row` returns, so the
    two can be handed to `compare`, `intrinsic` and `collapse` without either
    knowing where it came from. None when the parts are absent.
    """
    got = curves.get(base)
    if got is None:
        return None
    v = np.asarray(got[0], float)
    out = {"vg": v, "cgg": np.asarray(got[1], float)}
    for t in ("cgd", "cgs", "cgb"):
        part = curves.get("%s#%s" % (base, t))
        if part is None:
            return None
        out[t] = np.interp(v, np.asarray(part[0], float),
                           np.asarray(part[1], float))
    o = np.argsort(out["vg"])
    for k in list(out):
        out[k] = out[k][o]
    den = np.maximum(np.abs(out["cgg"]), 1e-30)
    out["closure_pct"] = 100.0 * (out["cgd"] + out["cgs"] + out["cgb"]
                                  - out["cgg"]) / den
    return out


def row_table(mod, ref, at=(-0.2, 0.0, 0.2, 0.3, 0.4, 0.5, 0.6), scale=1e18):
    """Model against reference, term by term, at chosen gate biases.

    Returns a list of dicts -- one per bias -- each with the four reference
    values, the four model values and the four differences, all in aF.
    """
    rows = []
    for x in at:
        r = {"vg": float(x)}
        for t in TERMS:
            rv = _at(ref["vg"], ref[t], x)
            mv = _at(mod["vg"], mod[t], x)
            r["ref_" + t] = rv * scale
            r["mod_" + t] = mv * scale
            r["d_" + t] = (mv - rv) * scale
        rows.append(r)
    return rows


def format_row_table(mod, ref, at=(-0.2, 0.0, 0.2, 0.3, 0.4, 0.5, 0.6),
                     title="model vs reference, gate row [aF]"):
    rows = row_table(mod, ref, at=at)
    out = [title,
           "   Vg    |  ---------- TCAD ---------- | --------- MODEL --------- "
           "| -------- MODEL-TCAD -------",
           "         |   Cgg    Cgd    Cgs    Cgb  |   Cgg    Cgd    Cgs    Cgb"
           "  |   Cgg    Cgd    Cgs    Cgb"]
    for r in rows:
        out.append(
            "  %+0.3f  | %6.2f %6.2f %6.2f %6.2f | %6.2f %6.2f %6.2f %6.2f "
            "| %+6.2f %+6.2f %+6.2f %+6.2f" % (
                r["vg"],
                r["ref_cgg"], r["ref_cgd"], r["ref_cgs"], r["ref_cgb"],
                r["mod_cgg"], r["mod_cgd"], r["mod_cgs"], r["mod_cgb"],
                r["d_cgg"], r["d_cgd"], r["d_cgs"], r["d_cgb"]))
    return "\n".join(out)


def rms_by_term(mod, ref):
    """Relative RMS error per term, over the reference's own bias grid.

    Reported as a percentage. This is the number that says which part of the
    gate row is wrong, which the single Cgg error cannot.
    """
    out = {}
    v = np.asarray(ref["vg"], float)
    for t in TERMS:
        r = np.asarray(ref[t], float)
        m = np.interp(v, np.asarray(mod["vg"], float),
                      np.asarray(mod[t], float))
        good = np.isfinite(r) & np.isfinite(m) & (np.abs(r) > 1e-21)
        if good.sum() < 3:
            out[t] = None
            continue
        rel = (m[good] - r[good]) / np.abs(r[good])
        out[t] = {"rms_pct": float(np.sqrt(np.mean(rel ** 2)) * 100.0),
                  "mean_pct": float(np.mean(rel) * 100.0),
                  "max_pct": float(np.max(np.abs(rel)) * 100.0),
                  "n": int(good.sum())}
    return out


def format_rms_by_term(d, title="relative error by term"):
    out = [title, "   term |  RMS %   mean %   worst %   n"]
    for t in TERMS:
        r = d.get(t)
        if r is None:
            out.append("   %-4s |   (not enough usable reference points)" % t)
            continue
        out.append("   %-4s | %7.3f %8.3f %9.3f %4d"
                   % (t, r["rms_pct"], r["mean_pct"], r["max_pct"], r["n"]))
    return "\n".join(out)


def split(row, at_vg=0.60, vg_off=None):
    """How the INTRINSIC channel charge is shared between drain and source.

    Each terminal's own value at the off bias is its parasitic floor -- the
    overlap and fringe capacitors, which do not depend on the channel. Taking
    it off leaves the part that comes from the inversion charge, and the two
    remainders are what the drain and the source actually hold.

    At Vds -> 0 the split must be 50/50: the two ends of the channel are at
    the same potential, so a change in gate voltage adds the same charge to
    each end. In saturation the drain end is pinched off and the ROW's drain
    share collapses toward 0. That is the whole diagnostic: a model whose
    split is already lopsided at Vd = 50 mV has pinched off far too early.

    Returns {"cgd_int", "cgs_int", "frac_d", "frac_s", "total_int"} in farads.
    """
    if vg_off is None:
        vg_off = float(np.min(row["vg"]))
    d = _at(row["vg"], row["cgd"], at_vg) - _at(row["vg"], row["cgd"], vg_off)
    s = _at(row["vg"], row["cgs"], at_vg) - _at(row["vg"], row["cgs"], vg_off)
    tot = d + s
    f = (lambda x: float(x / tot) if abs(tot) > 1e-30 else float("nan"))
    return {"cgd_int": float(d), "cgs_int": float(s), "total_int": float(tot),
            "frac_d": f(d), "frac_s": f(s)}


def format_split(dev, mod, at_vg=0.60, vg_off=None, scale=1e18,
                 title=None):
    a = split(dev, at_vg=at_vg, vg_off=vg_off)
    b = split(mod, at_vg=at_vg, vg_off=vg_off)
    out = [title or ("drain/source share of the intrinsic charge at "
                     "Vg = %.2f V" % at_vg),
           "               Cgd_int   Cgs_int    total     drain share",
           "   TCAD      %8.3f  %8.3f  %8.3f      %6.1f %%"
           % (a["cgd_int"] * scale, a["cgs_int"] * scale,
              a["total_int"] * scale, 100.0 * a["frac_d"]),
           "   model     %8.3f  %8.3f  %8.3f      %6.1f %%"
           % (b["cgd_int"] * scale, b["cgs_int"] * scale,
              b["total_int"] * scale, 100.0 * b["frac_d"]),
           "   (aF)                                        50 % is a channel "
           "at Vds = 0; 0 % is fully pinched off)"]
    return "\n".join(out)


# ==========================================================================
#  THE PARASITIC FLOOR, SOLVED EXACTLY AND ITERATED   (TCADOpt v1.1.18)
# ==========================================================================
def floor_of(row, vg_off, terms=("cgd", "cgs", "cgb"), scale=1e18):
    """Each terminal's value at the off bias, where there is no channel."""
    v = np.asarray(row["vg"], float)
    o = np.argsort(v)
    return tuple(float(np.interp(vg_off, v[o],
                                 np.asarray(row[t], float)[o]) * scale)
                 for t in terms)


def _independent(cols, names, cos_max=0.9995):
    """Keep one column per direction; report which were dropped and why.

    CGDO, CGSO, CFD and CFS all add farads-per-metre times the same width, so
    their columns point the same way. A least-squares solve is free to make
    one enormous and another enormously negative and still report a small
    residual -- a dry run of Step 20 drove all four to 1.2e-8 F/m and the
    floor to 1175 aF. One representative per direction removes the freedom
    without removing any reachable answer.
    """
    A = np.asarray(cols, float).T
    keep, dropped = [], []
    for j in range(A.shape[1]):
        c = A[:, j]
        nc = float(np.linalg.norm(c))
        if nc < 1e-12:
            dropped.append((names[j], "no measurable effect"))
            continue
        par = None
        for j2 in keep:
            c2 = A[:, j2]
            if abs(float(c.dot(c2)) / (nc * np.linalg.norm(c2))) > cos_max:
                par = names[j2]
                break
        if par is not None:
            dropped.append((names[j], "same direction as %s" % par))
        else:
            keep.append(j)
    return keep, dropped


def floor_solve(measure, card, knobs, steps, want, bounds=None, rounds=3,
                log=None, tol=0.02):
    """Fit the off-state row EXACTLY, by measurement, in a few rounds.

    `measure(card) -> (Cgd, Cgs, Cgb) at the off bias, in aF, or None`
    `knobs`   : the parameter names to use
    `steps`   : {name: the probe step, in the parameter's own unit}
    `want`    : the three numbers the reference asks for, in aF
    `bounds`  : {name: (lo, hi)}; None means [0, inf), which is what
                BSIM-CMG's `MPRcz` declares for every overlap and fringe
                parameter.

    WHY THIS IS A SOLVE AND NOT AN OPTIMIZATION
    -------------------------------------------
    Below threshold there is no channel, and BSIM-CMG's parasitics are each
    a parameter times a geometry -- a straight line through the origin:

        Cgd(off) = (CGDO + CGDL) * WeffCV0 + CFD * WeffCV0     (body 2516/2533)
        Cgs(off) = (CGSO + CGSL) * WeffCV0 + CFS * WeffCV0     (body 2512/2532)
        Cgb(off) = (CGBO*NF*NGCON + (CGBN + CGBW*WGAAeff)*NFINtotal) * Lg
                                                                (body 933)

    So three measured slopes and three wanted numbers give the answer in
    closed form. It is iterated anyway, three times by default, because a
    clip at zero or a bound makes one round land short -- and because an
    iteration that is already exact costs one evaluation and proves it.

    Returns {"card", "rounds": [...], "before", "after", "solved"}.
    """
    bounds = bounds or {}
    cur = dict(card)
    hist = []
    base = measure(cur)
    if base is None:
        return {"card": cur, "rounds": [], "before": None, "after": None,
                "solved": False, "why": "the starting card did not evaluate"}
    first = float(np.linalg.norm([base[i] - want[i] for i in range(3)]))
    for it in range(int(rounds)):
        cols, names = [], []
        for nm in knobs:
            trial = dict(cur)
            trial[nm] = float(cur.get(nm, 0.0)) + float(steps[nm])
            got = measure(trial)
            if got is None:
                continue
            col = [got[i] - base[i] for i in range(3)]
            if max(abs(c) for c in col) > 1.0e-5:
                cols.append(col)
                names.append(nm)
        if not cols:
            hist.append({"round": it, "why": "no live knob"})
            break
        keep, dropped = _independent(cols, names)
        b = np.asarray([want[i] - base[i] for i in range(3)], float)

        # SOLVE, CLIP, THEN SOLVE AGAIN WITHOUT WHAT CLIPPED.
        # A parameter that the arithmetic wants to drive negative is not
        # just capped -- its whole share of the move is lost, and the
        # parameters that remain were never asked to make it up. Step 20
        # produced exactly that: the solution needed CGBO negative, the clip
        # put it at zero, and the +1160 aF the other four had been given to
        # cancel it stayed. So the clipped names are removed and the rest
        # re-solved, until nothing clips.
        live = list(keep)
        for _pass in range(len(keep) + 1):
            A = np.asarray(cols, float).T[:, live]
            KN = [names[j] for j in live]
            coef, _r, rank, _s = np.linalg.lstsq(A, b, rcond=None)
            clipped = []
            for i2, nm in enumerate(KN):
                old_v = float(cur.get(nm, 0.0))
                new_v = old_v + float(coef[i2]) * float(steps[nm])
                lo, hi = bounds.get(nm, (0.0, float("inf")))
                if new_v < lo or new_v > hi:
                    clipped.append(live[i2])
            if not clipped or len(clipped) >= len(live):
                break
            live = [j for j in live if j not in clipped]
            for j in clipped:
                dropped.append((names[j], "its share of the move would take"
                                          " it outside its declared range"))
        A = np.asarray(cols, float).T[:, live]
        KN = [names[j] for j in live]
        coef, _r, rank, _s = np.linalg.lstsq(A, b, rcond=None)
        applied = np.zeros(len(KN))
        moves = []
        for i2, nm in enumerate(KN):
            old = float(cur.get(nm, 0.0))
            new = old + float(coef[i2]) * float(steps[nm])
            lo, hi = bounds.get(nm, (0.0, float("inf")))
            why = ""
            if new < lo:
                new, why = lo, "clipped at %g" % lo
            elif new > hi:
                new, why = hi, "clipped at %g" % hi
            applied[i2] = (new - old) / float(steps[nm])
            cur[nm] = new
            moves.append({"name": nm, "from": old, "to": new, "why": why})
        pred = A.dot(applied)
        got = measure(cur)
        rec = {"round": it, "kept": KN,
               "dropped": [list(d) for d in dropped], "rank": int(rank),
               "moves": moves,
               "predicted": [float(x) for x in pred],
               "wanted": [float(x) for x in b],
               "measured": None if got is None
               else [got[i] - base[i] for i in range(3)],
               "err_before": float(np.linalg.norm(b))}
        if got is None:
            rec["why"] = "the solved card did not evaluate; rolled back"
            for m in moves:
                cur[m["name"]] = m["from"]
            hist.append(rec)
            break
        rec["err_after"] = float(np.linalg.norm(
            [got[i] - want[i] for i in range(3)]))
        hist.append(rec)
        if log:
            log("      round %d: %d independent knob(s), floor error"
                " %.4f -> %.4f aF" % (it + 1, len(KN), rec["err_before"],
                                      rec["err_after"]))
            for m in moves:
                log("        %-9s %-14.6g -> %-14.6g %s"
                    % (m["name"], m["from"], m["to"], m["why"]))
        base = got
        if rec["err_after"] <= tol:
            break
    last = float(np.linalg.norm([base[i] - want[i] for i in range(3)]))
    return {"card": cur, "rounds": hist, "before": first, "after": last,
            "solved": bool(last < first)}


def best_constant(ref, term, scale=1e18):
    """The single value that minimises the RMS RELATIVE error of a term.

    BSIM-CMG's gate-to-substrate capacitance is bias-INDEPENDENT unless
    BULKMOD is on (body.include 3067 is a constant; 3074's bias-dependent
    part is inside `if (bulkmod != 0)`). This device's Cgb is not constant:
    it falls from 1.93 to 1.41 aF across the sweep. So the best a
    BULKMOD = 0 card can do is one number, and this is that number --
    the value c minimising mean((c/r - 1)^2), which is sum(1/r) / sum(1/r^2).
    """
    r = np.abs(np.asarray(ref[term], float))
    good = np.isfinite(r) & (r > 0)
    r = r[good]
    if not len(r):
        return None
    c = float(np.sum(1.0 / r) / np.sum(1.0 / (r * r)))
    rel = c / r - 1.0
    return {"value_aF": c * scale, "value": c,
            "rms_pct": float(np.sqrt(np.mean(rel ** 2)) * 100.0),
            "worst_pct": float(np.max(np.abs(rel)) * 100.0),
            "ref_min_aF": float(r.min() * scale),
            "ref_max_aF": float(r.max() * scale)}
