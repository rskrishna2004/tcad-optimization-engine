"""l3_exec.metrics -- rich transistor figure-of-merit (FoM) library.

The enabler for "optimize ANY target metric, not just ION/IOFF/gm". Computes a broad
set of FoMs from an Id-Vg sweep, sign-agnostic (works for NMOS and PMOS via |Id|,|Vg|
relative to source). Multi-bias FoMs (DIBL) combine two sweeps; AC FoMs (ft, fmax)
are documented hooks for when an AC deck is available.

All returned keys are friendly names the scorer's METRIC_KEYS can target directly.

$Id: metrics.py, 2026/06/18 [YOUR NAME] $
"""
import numpy as np


def _prep(vg, idd):
    """Magnitudes, sorted by |Vg| ascending. Works for NMOS and PMOS."""
    vg = np.abs(np.asarray(vg, float))
    idd = np.abs(np.asarray(idd, float))
    o = np.argsort(vg)
    return vg[o], idd[o]


def constant_current_vt(vg, idd, icrit):
    """Constant-current threshold: |Vg| where |Id| crosses icrit (A/um).
    icrit should already be scaled for W/L if needed (here W/L folded into A/um)."""
    vg, idd = _prep(vg, idd)
    if idd.max() < icrit or idd.min() > icrit:
        return float("nan")
    # interpolate on the monotonic-rising portion
    return float(np.interp(icrit, idd, vg))


def subthreshold_swing(vg, idd):
    """Min SS (mV/dec) = 1000 / max d(log10|Id|)/d|Vg| in the rising region."""
    vg, idd = _prep(vg, idd)
    with np.errstate(divide="ignore"):
        logi = np.log10(np.clip(idd, 1e-30, None))
    slope = np.gradient(logi, vg)
    s = np.max(slope)
    return float(1000.0 / s) if s > 0 else float("inf")


def foms_from_idvg(vg, idd, vdd, voff=0.0, vt_icrit=1.0e-7, id_targets=()):
    """Full single-sweep FoM set. id_targets: currents (A/um) at which to report
    transconductance efficiency gm/Id and gm (analog bias-point metrics)."""
    vg, idd = _prep(vg, idd)
    ion = float(np.interp(vdd, vg, idd))
    ioff = float(np.interp(voff, vg, idd))
    gm = np.gradient(idd, vg)
    gm_pk = float(np.max(gm))
    vg_pk = float(vg[int(np.argmax(gm))])
    ss = subthreshold_swing(vg, idd)
    vt = constant_current_vt(vg, idd, vt_icrit)
    gm_id = gm / np.clip(idd, 1e-30, None)
    out = {
        "ION_A_per_um": ion,
        "IOFF_A_per_um": ioff,
        "ION_IOFF_ratio": (ion / ioff) if ioff > 0 else float("inf"),
        "gm_peak_S_per_um": gm_pk,
        "Vg_at_gm_peak_V": vg_pk,
        "SS_mV_per_dec": ss,
        "Vt_V": vt,
        "gm_over_Id_peak_1_per_V": float(np.max(gm_id)),
        "n_bias_points": int(len(vg)),
    }
    for it in id_targets:
        if idd.max() >= it >= idd.min():
            vgt = float(np.interp(it, idd, vg))
            gmt = float(np.interp(vgt, vg, gm))
            out["gm_at_%g_S_per_um" % it] = gmt
            out["gm_over_Id_at_%g_1_per_V" % it] = gmt / it
    return out


def dibl_mV_per_V(vt_lin, vt_sat, vd_lin, vd_sat):
    """DIBL = |Vt_lin - Vt_sat| / |Vd_sat - Vd_lin|  (mV/V). Needs two IdVg sweeps."""
    return abs(vt_lin - vt_sat) / abs(vd_sat - vd_lin) * 1000.0


def foms_multibias(sweeps, vdd, vt_icrit=1.0e-7, **kw):
    """sweeps: {Vd: (vg, idd)}. Adds DIBL (and Vt at each Vd) to the saturation-Vd
    FoM set. The highest |Vd| is taken as saturation, the lowest as linear."""
    vds = sorted(sweeps.keys(), key=abs)
    vd_lin, vd_sat = vds[0], vds[-1]
    base = foms_from_idvg(sweeps[vd_sat][0], sweeps[vd_sat][1], vdd,
                          vt_icrit=vt_icrit, **kw)
    if len(vds) >= 2:
        vt_lin = constant_current_vt(sweeps[vd_lin][0], sweeps[vd_lin][1], vt_icrit)
        vt_sat = constant_current_vt(sweeps[vd_sat][0], sweeps[vd_sat][1], vt_icrit)
        base["Vt_lin_V"] = vt_lin
        base["Vt_sat_V"] = vt_sat
        base["DIBL_mV_per_V"] = dibl_mV_per_V(vt_lin, vt_sat, vd_lin, vd_sat)
    return base


# ---- AC hooks (documented; require an AC deck producing Cgg) -----------
def ft_GHz(gm_S_per_um, cgg_F_per_um):
    """Cutoff frequency ft = gm / (2*pi*Cgg). Requires Cgg from an AC sweep."""
    import math
    return gm_S_per_um / (2.0 * math.pi * cgg_F_per_um) / 1e9


# ---- plt convenience: rich metrics straight from a .plt -----------------
def metrics_from_plt(plt_path, vdd=1.0, **kw):
    """Parse an IdVg .plt (via the legacy plt_parser) and return the rich FoM set."""
    import os
    import sys
    legacy = os.environ.get("TCADOPT_LEGACY")
    if legacy and legacy not in sys.path:
        sys.path.insert(0, legacy)
    from plt_parser import parse_plt   # noqa: E402
    d = parse_plt(plt_path)
    vg = d["gate OuterVoltage"]
    idd = d["drain TotalCurrent"]
    return foms_from_idvg(vg, idd, vdd, **kw)


if __name__ == "__main__":
    # self-test against a clean EKV-style IdVg (subthreshold-exp -> square-law),
    # which has a well-defined minimum SS and gm/Id ceiling.
    import math
    vt = 0.30
    nvth = 0.0347          # SS = nvth*ln10*1000 ~ 80 mV/dec
    scale = 1.0e-6
    vg = np.linspace(0.0, 1.0, 201)
    y = (vg - vt) / (2.0 * nvth)
    z = np.log1p(np.exp(np.clip(y, -60, 60)))      # smooth subthreshold->strong inv
    idd = scale * z ** 2
    m = foms_from_idvg(vg, idd, 1.0, vt_icrit=1e-7, id_targets=(1e-5,))
    print("synthetic EKV IdVg FoMs:")
    for k in ("ION_A_per_um", "IOFF_A_per_um", "SS_mV_per_dec", "Vt_V",
              "gm_peak_S_per_um", "gm_over_Id_peak_1_per_V",
              "gm_over_Id_at_1e-05_1_per_V"):
        print("   %-30s %.4g" % (k, m.get(k)))
    ceiling = math.log(10) / (m["SS_mV_per_dec"] / 1000.0)   # subthreshold gm/Id ceiling
    assert 75 < m["SS_mV_per_dec"] < 85, m["SS_mV_per_dec"]
    assert m["ION_A_per_um"] > m["IOFF_A_per_um"] > 0
    assert 0.0 < m["Vt_V"] < 1.0
    assert abs(m["gm_over_Id_peak_1_per_V"] / ceiling - 1.0) < 0.1, \
        "gm/Id peak should ~ ln10/SS (%.1f vs %.1f)" % (m["gm_over_Id_peak_1_per_V"], ceiling)
    assert m["gm_over_Id_at_1e-05_1_per_V"] < m["gm_over_Id_peak_1_per_V"]
    print("metrics self-test OK: SS~80, gm/Id peak tracks the ln10/SS ceiling,")
    print("efficiency at 10uA below the subthreshold peak -- all physically consistent.")
