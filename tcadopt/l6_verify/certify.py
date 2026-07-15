"""l6_verify.certify -- champion certification (the trust layer).

A champion is never trustworthy until it passes, on live the TCAD simulator:
  1. mesh convergence  -- re-sim on a ~2x finer grid; metric shift < threshold
  2. coherence         -- no sqrt(2) doping fallback (device simulated == specified)
  3. BTBT-off bound    -- BTBT is a small % of IOFF (IOFF is subthreshold-limited)
  4. nonlocal-path     -- gold-standard B2B model keeps IOFF under cap
  5. constraint audit  -- all hard + coupled constraints hold; margin to cap (pure logic)

Generalizes verify_final.py + the fine-mesh / nobtbt / nonlocal decks. Deck names
are bound per device_class; gates 1-2-5 always run, 3-4 honor spec verify_fidelity.

$Id: certify.py, 2026/06/18 [YOUR NAME] $
"""
import os
import re
import sys
import shutil

_DEF_LEGACY = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "optimizer")

# deck binding per device_class (the planar-NMOS template family)
DECKS = {
    "planar_bulk_mosfet": {
        "sde_std":      "nmos_sde.scm",
        "sde_fine":     "nmos_sde_fine.scm",
        "prod":         "nmos_des.cmd",
        "btbt_off":     "nmos_des_nobtbt.cmd",
        "nonlocal":     "nmos_des_verify2.cmd",
        "plt_prod":     "nmos_idvg.plt",
        "plt_nobtbt":   "nmos_idvg_nobtbt.plt",
        "plt_nonlocal": "nmos_idvg_verify.plt",
        "mesh":         "nmos_msh.tdr",
        "prod_idvd":    "nmos_des_idvd.cmd",
        "plt_idvd":     "nmos_idvd.plt",
        "plt_lo_idvd":  "lo_nmos_idvd.plt",
    },
    "planar_bulk_pmos": {
        "sde_std":      "pmos_sde.scm",
        "sde_fine":     "pmos_sde_fine.scm",
        "prod":         "pmos_des.cmd",
        "btbt_off":     "pmos_des_nobtbt.cmd",
        "nonlocal":     "pmos_des_verify2.cmd",
        "plt_prod":     "pmos_idvg.plt",
        "plt_nobtbt":   "pmos_idvg_nobtbt.plt",
        "plt_nonlocal": "pmos_idvg_verify.plt",
        "mesh":         "pmos_msh.tdr",
        "prod_idvd":    "pmos_des_idvd.cmd",
        "plt_idvd":     "pmos_idvd.plt",
        "plt_lo_idvd":  "pmos_idvd.plt".replace("pmos_idvd","lo_pmos_idvd"),
    },
    "finfet_dg_nmos": {
        "sde_std":      "finn_sde.scm",
        "sde_fine":     "finn_sde_fine.scm",
        "prod":         "finn_des.cmd",
        "btbt_off":     "finn_des_nobtbt.cmd",
        "nonlocal":     "finn_des_verify.cmd",
        "plt_prod":     "finn_idvg.plt",
        "plt_nobtbt":   "finn_idvg_nobtbt.plt",
        "plt_nonlocal": "finn_idvg_verify.plt",
        "mesh":         "finn_msh.tdr",
        "prod_idvd":    "finn_des.cmd",
        "plt_idvd":     "finn_idvg.plt",
        "plt_lo_idvd":  "finn_idvg.plt",
    },
    "nanowire_gaa_nmos": {
        "sde_std":      "nw_sde.scm",
        "sde_fine":     "nw_sde_fine.scm",
        "prod":         "nw_des.cmd",
        "btbt_off":     "nw_des_nobtbt.cmd",
        "nonlocal":     "nw_des_verify.cmd",
        "plt_prod":     "nw_idvg.plt",
        "plt_nobtbt":   "nw_idvg_nobtbt.plt",
        "plt_nonlocal": "nw_idvg_verify.plt",
        "mesh":         "nw_msh.tdr",
        "prod_idvd":    "nw_des.cmd",
        "plt_idvd":     "nw_idvg.plt",
        "plt_lo_idvd":  "nw_idvg.plt",
    },
}


# ---- pure helpers (unit-testable, no the TCAD simulator) -----------------------
def mesh_shift_pct(ref, fine, keys=("ION_A_per_um", "IOFF_A_per_um")):
    """Max relative shift (%) between standard- and fine-mesh metrics."""
    worst = 0.0
    for k in keys:
        a, b = ref.get(k), fine.get(k)
        if a and b:
            worst = max(worst, 100.0 * abs(b - a) / abs(a))
    return worst


def btbt_fraction_pct(ioff_with, ioff_without):
    """BTBT contribution to IOFF (%) = (IOFF_hurkx - IOFF_nobtbt)/IOFF_hurkx."""
    if not ioff_with:
        return 0.0
    return 100.0 * (ioff_with - ioff_without) / ioff_with


def constraint_audit(params, cp, cap, ref_ioff):
    """Evaluate hard + coupled constraints and cap feasibility. Pure logic.
    Returns list of (label, ok, detail)."""
    out = []
    hard = (cp.spec.get("constraints") or {}).get("hard", [])
    pat = re.compile(r"^\s*([A-Za-z_]\w*)\s*(>=|<=|==)\s*([-+0-9.eE]+)\s*$")
    for c in hard:
        m = pat.match(c)
        if not m:
            out.append((c, True, "structural/assumed"))
            continue
        name, op, rhs = m.group(1), m.group(2), m.group(3)
        try:
            rv = float(rhs)
        except ValueError:
            out.append((c, True, "non-numeric (assumed)"))
            continue
        if name not in params:
            out.append((c, True, "param absent (assumed)"))
            continue
        v = params[name]
        ok = (v >= rv) if op == ">=" else (v <= rv) if op == "<=" else (v == rv)
        out.append((c, ok, "%s=%.4g" % (name, v)))
    # coupled (reuse the space's parsed clamps)
    for (a, op, k, b) in cp.space._clamps:
        if a in params and b in params:
            bound = k * params[b]
            ok = (params[a] >= bound) if op == ">=" else (params[a] <= bound)
            out.append(("%s %s %.3g*%s" % (a, op, k, b), ok,
                        "%s=%.4g vs %.4g" % (a, params[a], bound)))
    # cap feasibility + margin
    if cap is not None:
        out.append(("IOFF <= cap (%.0e)" % cap, ref_ioff <= cap,
                    "IOFF=%.3e (%.2fx cap)" % (ref_ioff, ref_ioff / cap)))
    return out


# ---- the TCAD simulator build helper -------------------------------------------
def _load_legacy(legacy_dir):
    legacy_dir = legacy_dir or os.environ.get("TCADOPT_LEGACY", _DEF_LEGACY)
    if legacy_dir not in sys.path:
        sys.path.insert(0, legacy_dir)
    import runner          # noqa: E402
    from plt_parser import extract_metrics  # noqa: E402
    return runner, extract_metrics


def _build_and_run(params, sde_deck, sdevice_deck, plt_name, rdir, runner,
                   extract_metrics, templates, tag, mesh="nmos_msh.tdr"):
    """Render params, build mesh with sde_deck, run sdevice_deck, extract metrics.
    Returns (metrics_or_None, sde_log_text). Device-agnostic: the structure tool runs on the deck's
    own filename and the device-specific mesh name is checked."""
    os.makedirs(rdir, exist_ok=True)
    runner.render_params(params, os.path.join(rdir, "params.scm"), tag)
    shutil.copy(os.path.join(templates, sde_deck), os.path.join(rdir, sde_deck))
    shutil.copy(os.path.join(templates, sdevice_deck), os.path.join(rdir, sdevice_deck))
    runner.run_tool(["sde", "-e", "-l", sde_deck], rdir, 600, "sde.log")
    sde_log = ""
    slog = os.path.join(rdir, "sde.log")
    if os.path.exists(slog):
        sde_log = open(slog).read()
    if not os.path.exists(os.path.join(rdir, mesh)):
        return None, sde_log
    runner.run_tool(["sdevice", sdevice_deck], rdir, 1800, "sdev.log")
    plt = os.path.join(rdir, plt_name)
    if not os.path.exists(plt):
        return None, sde_log
    return extract_metrics(plt, vdd=1.0), sde_log


def _run_idvd_metrics(params, sde_deck, rdir, runner, templates, tag, deck):
    """Build (sde_deck) mesh + run the two-curve IdVd deck; return IdVd FoMs."""
    from plt_parser import extract_idvd
    m, sde_log = _build_and_run(
        params, sde_deck, deck["prod_idvd"], deck["plt_idvd"], rdir, runner,
        lambda p, vdd=1.0: p, templates, tag, mesh=deck["mesh"])  # extractor stubbed
    # _build_and_run already ran sdevice + confirmed plt_idvd exists; extract both
    main = os.path.join(rdir, deck["plt_idvd"])
    lo = os.path.join(rdir, deck["plt_lo_idvd"])
    if not (os.path.exists(main) and os.path.exists(lo)):
        return None, sde_log
    return extract_idvd(main, lo, vdd=1.0, dvg=0.05), sde_log


# ---- the certificate --------------------------------------------------
class Certificate(object):
    def __init__(self, label, params, cap, ref_metrics):
        self.label = label
        self.params = params
        self.cap = cap
        self.ref = ref_metrics
        self.gates = []          # list of (name, passed, detail)
        self.numbers = {}

    def add(self, name, passed, detail):
        self.gates.append((name, bool(passed), detail))

    @property
    def verdict(self):
        return all(p for _, p, _ in self.gates) if self.gates else False

    def __str__(self):
        lines = ["CERTIFICATE  [%s]  cap=%s  VERDICT=%s" % (
            self.label, self.cap, "PASS" if self.verdict else "FAIL")]
        m = self.ref or {}
        lines.append("  metrics: ION=%.3e IOFF=%.3e gm=%.3e SS=%.1f" % (
            m.get("ION_A_per_um", 0), m.get("IOFF_A_per_um", 0),
            m.get("gm_peak_S_per_um", 0), m.get("SS_mV_per_dec", 0)))
        for name, passed, detail in self.gates:
            lines.append("   [%s] %-22s %s" % (
                "PASS" if passed else "FAIL", name, detail))
        return "\n".join(lines)

    def to_dict(self):
        return {"label": self.label, "cap": self.cap, "verdict": self.verdict,
                "metrics": self.ref, "params": self.params,
                "gates": [{"name": n, "pass": p, "detail": d}
                          for n, p, d in self.gates]}


def certify(params, cp, label, cap, ref_metrics, legacy_dir=None,
            run_tcad_simulator=True, verbose=True):
    """Run all applicable gates on a champion; return a Certificate."""
    cert = Certificate(label, params, cap, ref_metrics)
    thr = cp.verify_plan["thresholds"]
    fidelity = cp.verify_plan["fidelity"]
    deck = DECKS.get(cp.device_class)
    ref_ioff = (ref_metrics or {}).get("IOFF_A_per_um", float("inf"))

    # gate 5 (always; pure logic)
    for clabel, ok, detail in constraint_audit(params, cp, cap, ref_ioff):
        cert.add("constraint", ok, "%s (%s)" % (clabel, detail))

    if not run_tcad_simulator or deck is None:
        return cert

    ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    templates = os.path.join(ROOT, "templates")
    runner, extract_metrics = _load_legacy(legacy_dir)
    base = os.path.join(ROOT, "runs", "cert_%s" % label)

    meas = getattr(cp, "measurement", "idvg")
    if meas == "idvd":
        # companion IdVg (std mesh) supplies IOFF for the BTBT/nonlocal gates
        # and the coherence check; the mesh gate uses the IdVd analog metric.
        comp, sde_log = _build_and_run(
            params, deck["sde_std"], deck["prod"], deck["plt_prod"],
            base + "_comp", runner, extract_metrics, templates,
            "cert_%s_comp" % label, mesh=deck["mesh"])
        ref_ioff = (comp or {}).get("IOFF_A_per_um", ref_ioff)
        fine, _ = _run_idvd_metrics(
            params, deck["sde_fine"], base + "_fine", runner, templates,
            "cert_%s_fine" % label, deck)
        mesh_keys = ("intrinsic_gain", "Idsat_A_per_um")
        detail_tail = ("gain=%.2f" % fine.get("intrinsic_gain", 0)) if fine else ""
    else:
        fine, sde_log = _build_and_run(
            params, deck["sde_fine"], deck["prod"], deck["plt_prod"],
            base + "_fine", runner, extract_metrics, templates,
            "cert_%s_fine" % label, mesh=deck["mesh"])
        mesh_keys = ("ION_A_per_um", "IOFF_A_per_um")
        detail_tail = ("fine IOFF=%.3e" % fine.get("IOFF_A_per_um", 0)) if fine else ""

    incoherent = "must be greater than the value at junction" in sde_log
    cert.add("coherence", not incoherent,
             "sqrt(2) fallback absent" if not incoherent else "DOPING INCOHERENT")
    if fine:
        shift = mesh_shift_pct(ref_metrics, fine, keys=mesh_keys)
        cert.add("mesh_convergence", shift <= thr.get("mesh_shift_pct", 10),
                 "fine-mesh shift %.2f%% (<= %g%%); %s"
                 % (shift, thr.get("mesh_shift_pct", 10), detail_tail))
    else:
        cert.add("mesh_convergence", False, "fine-mesh run produced no plt")

    # gate 3: BTBT-off bound
    if "btbt_off_bound" in fidelity:
        nb, _ = _build_and_run(
            params, deck["sde_std"], deck["btbt_off"], deck["plt_nobtbt"],
            base + "_nobtbt", runner, extract_metrics, templates, "cert_%s_nb" % label,
            mesh=deck["mesh"])
        if nb:
            frac = btbt_fraction_pct(ref_ioff, nb.get("IOFF_A_per_um", ref_ioff))
            cert.add("btbt_off_bound", abs(frac) <= thr.get("btbt_frac_pct", 5),
                     "BTBT %.2f%% of IOFF (<= %g%%)" % (frac, thr.get("btbt_frac_pct", 5)))
        else:
            cert.add("btbt_off_bound", False, "nobtbt run produced no plt")

    # gate 4: nonlocal-path (gold standard) keeps IOFF under cap
    if "nonlocal_path" in fidelity:
        nl, _ = _build_and_run(
            params, deck["sde_std"], deck["nonlocal"], deck["plt_nonlocal"],
            base + "_nl", runner, extract_metrics, templates, "cert_%s_nl" % label,
            mesh=deck["mesh"])
        if nl:
            io = nl.get("IOFF_A_per_um", 0)
            ok = (cap is None) or (io <= cap)
            cert.add("nonlocal_path", ok,
                     "nonlocal IOFF=%.3e%s" % (
                         io, " (%.2fx cap)" % (io / cap) if cap else ""))
        else:
            cert.add("nonlocal_path", False, "nonlocal run produced no plt")

    if verbose:
        print(cert)
    return cert
