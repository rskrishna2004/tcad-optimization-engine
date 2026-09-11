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
