"""l3_exec.targets -- load the TCAD reference curves the model must reproduce.

The reference data are the CSVs exported from the validated Sentaurus DDDG
runs: `iv_targets.csv` (1292 rows, 12 sweeps) and `cv_targets.csv` (364 rows,
4 sweeps). Each row is one bias point.

WHAT THIS DOES THAT MATTERS
---------------------------
It groups rows into named sweeps, and it drops rows the reference data itself
marks as untrustworthy. The C-V export carries a `usable` column: 25 of its 364
rows are flagged `usable=NO` because the gate row of the measured capacitance
matrix does not close there. Fitting to a point the reference says is bad is
worse than having no point at all, because the optimizer will faithfully bend
the model to reproduce a measurement error. So flagged rows are excluded here,
at load time, and the count is reported rather than hidden.

No numpy-free fallback: numpy is already a hard requirement of the engine.
"""
import csv
import os

import numpy as np


def _f(x, default=float("nan")):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def load_iv_targets(path, devices=None, weight=1.0, per_um=True):
    """Group `iv_targets.csv` into sweeps.

    Columns used: device, sweep, bias, vg, vd, id_A (and id_uA_per_um).
    Sweep name is '<device>_<sweep>_<bias>', e.g. 'nsfet_n_IdVg_0.60'.
    For an IdVg sweep the swept axis is vg; for IdVd it is vd.

    Returns a list of target dicts ready for CurveResidualScorer.
    """
    if not os.path.exists(path):
        raise IOError("no such target file: %s" % path)
    groups = {}
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            dev = row.get("device", "dev")
            if devices and dev not in devices:
                continue
            kind = (row.get("sweep") or "IdVg").strip()
            bias = _f(row.get("bias"), 0.0)
            name = "%s_%s_%.2f" % (dev, kind, abs(bias))
            g = groups.setdefault(name, {"v": [], "i": [], "kind": kind,
                                         "device": dev, "bias": bias})
            g["v"].append(_f(row.get("vg" if kind.lower() == "idvg" else "vd")))
            if per_um and row.get("id_uA_per_um") not in (None, ""):
                g["i"].append(_f(row["id_uA_per_um"]) * 1e-6)   # uA/um -> A/um
            else:
                g["i"].append(_f(row.get("id_A")))
    out = []
    for name in sorted(groups):
        g = groups[name]
        v = np.asarray(g["v"], float)
        i = np.asarray(g["i"], float)
        ok = np.isfinite(v) & np.isfinite(i)
        v, i = v[ok], i[ok]
        o = np.argsort(v)
        out.append({"name": name, "v": v[o], "i": i[o], "weight": weight,
                    "kind": "iv", "sweep_kind": g["kind"],
                    "device": g["device"], "bias": g["bias"]})
    return out


def iv_width_from_csv(path, devices=None):
    """v1.1.10: the width the I-V targets were divided by, read from the data.

    `iv_targets.csv` carries both `id_A` (the whole device) and
    `id_uA_per_um` (per micron). Their ratio IS the normalisation width, so
    it is measured here rather than typed in anywhere. Rows whose current is
    at the numerical floor carry no usable ratio and are skipped.

    Returns {"width_um": median, "min": .., "max": .., "n": rows used}.
    The evaluator must divide the model's device current by exactly this
    number, or the fit compares amperes with amperes-per-micron.
    """
    if not os.path.exists(path):
        raise IOError("no such target file: %s" % path)
    w = []
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            if devices and row.get("device") not in devices:
                continue
            a = abs(_f(row.get("id_A")))
            b = abs(_f(row.get("id_uA_per_um"))) * 1e-6      # A/um
            if np.isfinite(a) and np.isfinite(b) and a > 1e-15 and b > 0:
                w.append(a / b)                                # um
    if not w:
        return {"width_um": float("nan"), "min": float("nan"),
                "max": float("nan"), "n": 0}
    w = np.asarray(w, float)
    return {"width_um": float(np.median(w)), "min": float(w.min()),
            "max": float(w.max()), "n": int(len(w))}


def load_cv_targets(path, devices=None, weight=1.0, require_usable=True):
    """Group `cv_targets.csv` into sweeps, honouring the `usable` flag.

    Returns (targets, n_dropped). `n_dropped` is printed by the campaign so the
    exclusion is visible in the run log rather than silent.
    """
    if not os.path.exists(path):
        raise IOError("no such target file: %s" % path)
    groups, dropped = {}, 0
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            dev = row.get("device", "dev")
            if devices and dev not in devices:
                continue
            if require_usable and str(row.get("usable", "yes")).strip().lower() \
                    not in ("yes", "y", "true", "1", ""):
                dropped += 1
                continue
            vd = _f(row.get("vd"), 0.0)
            name = "%s_CV_%.2f" % (dev, abs(vd))
            g = groups.setdefault(name, {"v": [], "c": [], "device": dev,
                                         "bias": vd})
            g["v"].append(_f(row.get("vg")))
            g["c"].append(_f(row.get("Cgg_F")))
    out = []
    for name in sorted(groups):
        g = groups[name]
        v = np.asarray(g["v"], float)
        c = np.asarray(g["c"], float)
        ok = np.isfinite(v) & np.isfinite(c) & (c > 0)
        v, c = v[ok], c[ok]
        o = np.argsort(v)
        out.append({"name": name, "v": v[o], "i": c[o], "weight": weight,
                    "kind": "cv", "sweep_kind": "CV",
                    "device": g["device"], "bias": g["bias"]})
    return out, dropped


ROW_COLUMN = {"cgd": "Cgd_F", "cgs": "Cgs_F", "cgb": "Cgb_F"}


def load_cv_row_targets(path, devices=None, weight=1.0, require_usable=True,
                        terms=("cgd", "cgs", "cgb")):
    """The GATE ROW of the reference capacitance matrix, as fit targets.

    WHY THIS IS A DIFFERENT FUNCTION AND NOT A FLAG
    -----------------------------------------------
    `load_cv_targets` reads one column, `Cgg_F`, and eighteen steps of this
    project fitted it. Cgg is a SUM: Cgg = Cgd + Cgs + Cgb. The sum cannot see
    how the charge is shared between the drain and the source, and on this
    device that share is where the model is wrong. At Vg = 0.6 V, Vd = 50 mV,
    on the Step-19 card:

        reference   Cgg 59.44   Cgd 28.57   Cgs 29.47   Cgb 1.41 aF
        model       Cgg 50.50   Cgd 16.36   Cgs 33.87   Cgb 0.27 aF
        error           -15%       -43%        +15%       -81%

    Cgg is 15% low. Its parts are 43% low, 15% high and 81% low, and two of
    those errors partly cancel inside the sum. Every parameter that moves
    charge from the drain end to the source end therefore looked INERT in the
    Step-18 census, because it barely moved the only number being scored.

    The reference stores the off-diagonal entries with the sign convention of
    a capacitance-matrix row -- Cgd_F, Cgs_F and Cgb_F are negative and sum to
    -Cgg_F, closing to 2e-6 % -- so the magnitude is taken here. The scorer
    compares magnitudes on both sides, so the convention cannot leak into the
    residual.

    The names carry `#` (`nsfet_n_CV_0.05#cgd`). `l3_exec.spice_exec` writes no
    deck for a name containing `#`: the row is read out of the SAME listing the
    parent C-V sweep already produced, so adding all six of these costs zero
    extra simulation time.
    """
    if not os.path.exists(path):
        raise IOError("no such target file: %s" % path)
    groups = {}
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            dev = row.get("device", "dev")
            if devices and dev not in devices:
                continue
            if require_usable and str(row.get("usable", "yes")).strip().lower() \
                    not in ("yes", "y", "true", "1", ""):
                continue
            vd = _f(row.get("vd"), 0.0)
            for t in terms:
                col = ROW_COLUMN[t]
                if col not in row:
                    continue
                name = "%s_CV_%.2f#%s" % (dev, abs(vd), t)
                g = groups.setdefault(name, {"v": [], "c": [], "device": dev,
                                             "bias": vd, "term": t})
                g["v"].append(_f(row.get("vg")))
                g["c"].append(abs(_f(row[col])))
    out = []
    for name in sorted(groups):
        g = groups[name]
        v = np.asarray(g["v"], float)
        c = np.asarray(g["c"], float)
        ok = np.isfinite(v) & np.isfinite(c) & (c > 0)
        v, c = v[ok], c[ok]
        if len(v) < 3:
            continue
        o = np.argsort(v)
        out.append({"name": name, "v": v[o], "i": c[o], "weight": weight,
                    "kind": "cv", "sweep_kind": "CVROW", "term": g["term"],
                    "device": g["device"], "bias": g["bias"]})
    return out


def load_targets(spec_fit, root="."):
    """Build the full target list from a spec's `fit:` block.

    fit:
      iv_targets: targets/iv_targets.csv
      cv_targets: targets/cv_targets.csv
      devices:    [nsfet_n]
      include:    [nsfet_n_IdVg_0.60, nsfet_n_IdVg_0.05]   # optional whitelist
      iv_weight:  1.0
      cv_weight:  0.5
    """
    devices = spec_fit.get("devices")
    targets, dropped = [], 0
    ivp = spec_fit.get("iv_targets")
    if ivp:
        targets += load_iv_targets(os.path.join(root, ivp), devices=devices,
                                   weight=float(spec_fit.get("iv_weight", 1.0)))
    cvp = spec_fit.get("cv_targets")
    if cvp:
        t, dropped = load_cv_targets(
            os.path.join(root, cvp), devices=devices,
            weight=float(spec_fit.get("cv_weight", 1.0)))
        targets += t
        # v1.1.17: `cv_row_weight: 0` (the default) reproduces every earlier
        # step exactly -- no row targets, no change to any score.
        rw = float(spec_fit.get("cv_row_weight", 0.0))
        if rw > 0:
            targets += load_cv_row_targets(
                os.path.join(root, cvp), devices=devices, weight=rw,
                terms=tuple(spec_fit.get("cv_row_terms",
                                         ("cgd", "cgs", "cgb"))))
    keep = spec_fit.get("include")
    if keep:
        keep = set(keep)
        targets = [t for t in targets if t["name"] in keep]
    return targets, dropped


def summarize(targets, dropped=0):
    lines = ["target curves: %d sweeps, %d bias points%s" % (
        len(targets), sum(len(t["v"]) for t in targets),
        ("; %d C-V rows excluded (reference flagged them unusable)" % dropped)
        if dropped else "")]
    for t in targets:
        i = np.abs(t["i"])
        lines.append("  %-26s %-3s n=%-5d %s %.3e .. %.3e" % (
            t["name"], t["kind"], len(t["v"]),
            "C[F]" if t["kind"] == "cv" else "|Id|[A/um]", i.min(), i.max()))
    return "\n".join(lines)
