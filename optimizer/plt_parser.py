# $Id: plt_parser.py, v1.2 2026/07/04 [YOUR NAME] - + extract_idvd (gds/Ron/gm/gain/Early/Idsat from two output curves), self-contained. v1.1: extract_multibias (DIBL). v1.0: DF-ISE parser + ION/IOFF/gm. $
# Python 3.6 compatible. Only stdlib + numpy.
import re
import json
import sys
import numpy as np


def parse_plt(path):
    """Parse a DF-ISE xyplot .plt file -> dict of {dataset_name: np.array}."""
    text = open(path, "r").read()
    m = re.search(r'datasets\s*=\s*\[(.*?)\]', text, re.S)
    names = re.findall(r'"([^"]+)"', m.group(1))
    dm = re.search(r'Data\s*\{(.*)\}', text, re.S)
    data_txt = dm.group(1) if dm else text.split("Data {", 1)[1]
    vals = np.array([float(x) for x in
                     re.findall(r'[-+]?\d+\.?\d*[eE][-+]?\d+|[-+]?\d+\.\d+', data_txt)])
    ncol = len(names)
    vals = vals[: (len(vals) // ncol) * ncol].reshape(-1, ncol)
    return {n: vals[:, i] for i, n in enumerate(names)}


def extract_metrics(path, vdd=1.0):
    """Return ION [A/um], IOFF [A/um], peak gm [S/um], SS [mV/dec] from IdVg plt.
    Sign-agnostic: uses |Vg| and |Id| so it works for NMOS (Vg,Id>0) and PMOS
    (Vg,Id<0) alike; pass vdd of either sign (its magnitude is used)."""
    d = parse_plt(path)
    vg = np.abs(d["gate OuterVoltage"])
    idr = np.abs(d["drain TotalCurrent"])  # 2D Sdevice: A/um by default
    order = np.argsort(vg)
    vg, idr = vg[order], idr[order]

    ioff = float(np.interp(0.0, vg, idr))
    ion = float(np.interp(abs(vdd), vg, idr))
    vg, idr = _dedupe_x(vg, idr)
    gm = np.gradient(idr, vg)
    gm_pk = float(np.max(gm))
    vg_pk = float(vg[int(np.argmax(gm))])

    # Subthreshold swing: best-fit decade slope in the steepest log(Id) region
    with np.errstate(divide="ignore"):
        logi = np.log10(np.clip(idr, 1e-30, None))
    vg, logi = _dedupe_x(vg, logi)
    dlog = np.gradient(logi, vg)
    ss = float(1000.0 / np.max(dlog))      # mV/dec

    return {"ION_A_per_um": ion, "IOFF_A_per_um": ioff,
            "ION_IOFF_ratio": ion / ioff if ioff > 0 else float("inf"),
            "gm_peak_S_per_um": gm_pk, "Vg_at_gm_peak_V": vg_pk,
            "SS_mV_per_dec": ss, "n_bias_points": int(len(vg))}


def _dedupe_x(x, y):
    """Keep strictly-increasing x (drops DoZero/ramp duplicate bias points that
    made np.gradient divide by zero -> inf/nan gm warnings)."""
    import numpy as _np
    x=_np.asarray(x,float); y=_np.asarray(y,float)
    o=_np.argsort(x); x,y=x[o],y[o]
    keep=_np.concatenate(([True], _np.diff(x)>1e-12))
    return x[keep], y[keep]


def _cc_vt(vg, idd, icrit):
    """Constant-current threshold: |Vg| where |Id| crosses icrit. Sign-agnostic."""
    vg = np.abs(np.asarray(vg, float)); idd = np.abs(np.asarray(idd, float))
    o = np.argsort(vg); vg, idd = vg[o], idd[o]
    if idd.max() < icrit or idd.min() > icrit:
        return float("nan")
    return float(np.interp(icrit, idd, vg))


def extract_multibias(plt_sat, plt_lin, vdd=1.0, vd_lin=0.05, vt_icrit=1.0e-7):
    """Two-IdVg-sweep FoMs from the 2vd decks. Sign-agnostic (NMOS & PMOS).
    Returns Vt at each drain bias plus DIBL = |Vt_lin - Vt_sat|/|Vd_sat - Vd_lin|
    in mV/V. Self-contained: no imports outside this module (layer rule)."""
    ds, dl = parse_plt(plt_sat), parse_plt(plt_lin)
    vt_sat = _cc_vt(ds["gate OuterVoltage"], ds["drain TotalCurrent"], vt_icrit)
    vt_lin = _cc_vt(dl["gate OuterVoltage"], dl["drain TotalCurrent"], vt_icrit)
    dv = abs(abs(vdd) - abs(vd_lin))
    dibl = abs(vt_lin - vt_sat) / dv * 1000.0 if dv > 0 else float("nan")
    return {"Vt_lin_V": vt_lin, "Vt_sat_V": vt_sat, "DIBL_mV_per_V": dibl}


def _vd_id(d):
    """Drain-voltage sweep vector + drain current, |.| and sorted by |Vd|.
    Accepts the usual DF-ISE names; falls back across Outer/Inner voltage."""
    vkey = None
    for k in ("drain OuterVoltage", "drain InnerVoltage", "drain Voltage"):
        if k in d:
            vkey = k
            break
    if vkey is None:
        raise KeyError("no drain voltage dataset in plt (%s)" % list(d.keys()))
    vd = np.abs(np.asarray(d[vkey], float))
    idd = np.abs(np.asarray(d["drain TotalCurrent"], float))
    o = np.argsort(vd)
    return vd[o], idd[o]


def _slope(x, y):
    """Least-squares dY/dX (robust to >=2 points)."""
    if len(x) < 2:
        return float("nan")
    return float(np.polyfit(x, y, 1)[0])


def extract_idvd(plt_main, plt_lo, vdd=1.0, dvg=0.05,
                 sat_frac=0.80, tri_frac=0.15):
    """Output-characteristic FoMs from two IdVd curves 'dvg' apart in Vg.
    Sign-agnostic (NMOS & PMOS). Self-contained (numpy only -> layer rule).
      gds   = dId/dVd over |Vd| in [sat_frac,1]*VDD   (saturation) [S/um]
      Ron   = 1/(dId/dVd) over |Vd| in [0,tri_frac]*VDD (triode)   [Ohm.um]
      gm_op = (Id_main - Id_lo)/dvg at |Vd|=VDD                     [S/um]
      Av    = gm_op/gds ;  Early_V = Idsat/gds                       """
    vm, im = _vd_id(parse_plt(plt_main))
    vl, il = _vd_id(parse_plt(plt_lo))
    v = abs(vdd)
    idsat = float(np.interp(v, vm, im))
    idsat_lo = float(np.interp(v, vl, il))

    sat = (vm >= sat_frac * v) & (vm <= v)
    gds = _slope(vm[sat], im[sat])
    gds = gds if (np.isfinite(gds) and gds > 0) else float("nan")

    tri = vm <= tri_frac * v
    gtri = _slope(vm[tri], im[tri])
    ron = (1.0 / gtri) if (np.isfinite(gtri) and gtri > 0) else float("nan")

    gm_op = (idsat - idsat_lo) / dvg if dvg else float("nan")
    av = (gm_op / gds) if (np.isfinite(gds) and gds > 0 and np.isfinite(gm_op)) else float("nan")
    with np.errstate(divide="ignore", invalid="ignore"):
        av_db = 20.0 * np.log10(av) if (np.isfinite(av) and av > 0) else float("nan")
    early = (idsat / gds) if (np.isfinite(gds) and gds > 0) else float("nan")

    return {"Idsat_A_per_um": idsat,
            "gds_S_per_um": gds,
            "Ron_Ohm_um": ron,
            "gm_op_S_per_um": gm_op,
            "intrinsic_gain": av,
            "intrinsic_gain_dB": float(av_db) if np.isfinite(av_db) else float("nan"),
            "Early_V": early,
            "n_bias_points": int(len(vm))}


if __name__ == "__main__":
    metrics = extract_metrics(sys.argv[1] if len(sys.argv) > 1 else "nmos_idvg.plt")
    print(json.dumps(metrics, indent=2))
