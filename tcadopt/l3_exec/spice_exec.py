"""l3_exec.spice_exec -- run HSPICE on one candidate model card.

WHY A SECOND EVALUATOR EXISTS
-----------------------------
`optimizer/runner.run_one` hardcodes a TWO-STEP flow: run the structure tool,
check the mesh file appeared, then run the device tool. If the structure step
fails or its mesh is missing, the run is abandoned (runner.py lines 118-126).

A circuit simulator has no structure step. There is no mesh, so that check can
never pass, and the existing runner cannot be used for extraction without
changing behaviour the TCAD path depends on. Rather than weaken a proven code
path, extraction gets its own evaluator that presents the SAME interface --
`evaluate_batch(param_dicts, tag) -> list of result dicts` -- so `run_campaign`,
the physics guard, the experiment DB and the optimizer are all reached
unchanged. This is the interchangeability the architecture was built for; this
module is the proof it works.

WHAT ONE EVALUATION DOES
------------------------
1. Render the candidate into a BSIM-CMG model card (`l2_decks.cardgen`).
2. Write one HSPICE deck per target sweep.
3. Run HSPICE once per deck, each in its own directory, with a timeout and (on
   POSIX) its own process group so a hung run is killed whole.
4. Parse each listing into a curve (`l3_exec.hspice_parser`).
5. Return {sweep_name: (v, i)} plus a status.

Batches run in parallel exactly like the TCAD path.

v1.1.10 -- THE UNITS FAULT, AND THE ONE LINE THAT FIXES IT
----------------------------------------------------------
HSPICE prints `i(M1)` in AMPERES FOR THE WHOLE DEVICE -- here one stack of
NGAA = 4 sheets, Weff = 4 x 2 x (10 + 5) nm = 120 nm (BSIM-CMG eq. 3.53).
The I-V targets are loaded by `l3_exec.targets.load_iv_targets` with
`per_um=True`, i.e. in AMPERES PER MICRON of that same 0.120 um -- the CSV's
own column `id_uA_per_um` is exactly `id_A / 0.120 um`.

Up to v1.1.9 nothing divided the model by the width, so every I-V fit asked
the model for a DEVICE current equal to the reference's PER-MICRON number:
1/0.120 = 8.333 times the real device. The capacitance was never affected --
both sides of it are in farads for the whole device, which the CFS test in
`cardgen` measured to five figures.

`iv_width_um` closes it. When it is given, every I-V current the listing
returns is divided by it before anything sees it, so model and reference
are both in A/um of the same width. C-V is left alone. When it is NOT given
the evaluator behaves exactly as v1.1.9 did, so an old spec reproduces its
old numbers -- and `run_fit` prints a warning saying the comparison is in
mixed units.
"""
import os
import signal
import subprocess
import time
from multiprocessing import Pool

import numpy as np

from ..l2_decks import cardgen
from .hspice_parser import (has_error, parse_lis, sweep_columns,
                            cv_columns, cv_gate_row, op_gate_row)

# v1.1.17: a target whose name carries this separator is a DERIVED curve --
# one more row of the same simulation, not another simulation. `nsfet_n_CV_
# 0.05#cgd` rides on the deck `nsfet_n_CV_0.05` writes. No deck is written for
# it and no extra HSPICE run happens; the gate row costs nothing.
DERIVED = "#"

SPICE_TOOL = os.environ.get("TCADOPT_SPICE_TOOL", "hspice")
SPICE_ARGS = (os.environ.get("TCADOPT_SPICE_ARGS", "").split()
              if os.environ.get("TCADOPT_SPICE_ARGS") else [])
SPICE_TIMEOUT = int(os.environ.get("TCADOPT_SPICE_TIMEOUT", "300"))
RUNS = os.environ.get("TCADOPT_FIT_RUNS",
                      os.path.join(os.path.dirname(os.path.dirname(
                          os.path.dirname(os.path.abspath(__file__)))),
                          "runs_fit"))


def spice_command(deck):
    """`hspice -i deck.sp -o deck` unless overridden by the environment."""
    base = os.path.splitext(os.path.basename(deck))[0]
    return [SPICE_TOOL] + list(SPICE_ARGS) + ["-i", deck, "-o", base]


def _run(cmd, cwd, timeout, logname):
    """Run one tool safely: output to a file (no pipe deadlock), own process
    group so a timeout kills the whole group. Same policy as runner.run_tool."""
    with open(os.path.join(cwd, logname), "w") as logf:
        kw = dict(cwd=cwd, stdout=logf, stderr=subprocess.STDOUT)
        if os.name == "posix":
            kw["preexec_fn"] = os.setsid
        p = subprocess.Popen(cmd, **kw)
        try:
            return p.wait(timeout=timeout), False
        except subprocess.TimeoutExpired:
            try:
                if os.name == "posix":
                    os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                else:
                    p.kill()
            except OSError:
                pass
            p.wait()
            return -9, True


def _sweep_deck_args(t):
    """Turn one target sweep into the deck arguments that reproduce it.

    The model is swept at EXACTLY the reference biases: same start, same stop,
    and a step taken from the reference spacing. Comparing a model curve to a
    reference curve on a different grid is how a fit quietly becomes an
    interpolation artefact, so the grid is copied rather than chosen.
    """
    v = t["v"]
    lo, hi = float(v.min()), float(v.max())
    step = (hi - lo) / max(len(v) - 1, 1)
    kind = t.get("sweep_kind", "IdVg").lower()
    if t["kind"] == "cv":
        # ENDPOINT GUARD (v1.1.3). The deck writes the step with "%.6f", so a
        # step like 0.0088889 becomes 0.008889 and 90 of them overshoot `hi` by
        # 1e-5 V. HSPICE then stops one point EARLY and the reference's last
        # bias falls outside the model curve, where _interp_model returns NaN
        # and the point is dropped. Measured on the real Step-4 run: the C-V
        # decks returned 90 points against 91 reference points, losing the
        # Vg = +0.6 point -- the single most informative bias in the sweep.
        # Half a step of headroom costs one extra simulated point, outside the
        # comparison range, and guarantees the endpoint is covered.
        return "cv", dict(vd=abs(float(t["bias"])), freq=1.0e6,
                          vg_start=lo, vg_stop=hi + 0.5 * step, vg_step=step)
    if kind == "idvd":
        return "idvd", dict(vg=abs(float(t["bias"])),
                            vd_start=lo, vd_stop=hi, vd_step=step)
    return "idvg", dict(vd=abs(float(t["bias"])),
                        vg_start=lo, vg_stop=hi, vg_step=step)


ROW_TERMS = ("cgd", "cgs", "cgb")


def _cv_attach_row(res, base, row, v_ac, i_ac, want, curves, freq):
    """Hang the gate ROW off one C-V result, and cross-check it three ways.

    Adds `<base>#cgd`, `<base>#cgs`, `<base>#cgb` to `res["curves"]` -- only
    the ones something actually asked for, so an old spec that names no row
    targets gets exactly the curves it got in v1.1.16.

    Three checks are recorded in `res["gate_row"][base]`, and each one is a
    real measurement rather than an assertion:

      closure_pct   Cgd + Cgs + Cgb - Cgg, as a percentage of Cgg. The row of
                    a capacitance matrix sums to zero because the gate charge
                    cannot depend on shifting every terminal together. On the
                    Step-19 listing this is 3.3e-4 % at worst.

      ac_vs_op_pct  Cgg from the AC branch current against Cgg from the
                    operating-point print. Two different code paths reading
                    two different parts of the same listing: if they agree,
                    neither the deck nor the parser is lying. Measured on the
                    Step-19 listing: 0.000 %.

      column        the same simulation also carries the gate COLUMN -- Cdg,
                    Csg, Cbg -- which is a DIFFERENT set of derivatives and is
                    kept as a diagnostic, never as a fit target. The reference
                    is a row; fitting a column to it would be fitting the
                    wrong quantity, which is exactly the mistake Step 19 made.
    """
    g = {"n": int(row["n"]),
         "closure_pct": float(np.max(np.abs(row["closure_pct"])))}
    try:
        iq = np.interp(row["vg"], np.asarray(v_ac, float),
                       np.asarray(i_ac, float))
        den = np.maximum(np.abs(row["cgg"]), 1e-30)
        g["ac_vs_op_pct"] = float(np.max(np.abs(iq - row["cgg"]) / den) * 100.0)
    except Exception:
        g["ac_vs_op_pct"] = None
    for k in ("vth", "vdsat"):
        try:
            g[k + "_top"] = float(row[k][int(np.argmax(row["vg"]))])
        except Exception:
            pass
    try:
        col = cv_gate_row(curves, freq)
    except Exception:
        col = None
    if col is not None:
        j = int(np.argmax(col["vg"]))
        g["column"] = {"cdg": float(col["cgd"][j]), "csg": float(col["cgs"][j]),
                       "cbg": float(col["cgb"][j]), "cgg": float(col["cgg"][j]),
                       "vg": float(col["vg"][j]),
                       "closure_pct": float(np.max(np.abs(col["closure_pct"])))}
    res.setdefault("gate_row", {})[base] = g
    for t in ROW_TERMS:
        name = base + DERIVED + t
        if name in want:
            res["curves"][name] = (row["vg"], row[t])


def _one(job):
    # v1.1.10: an optional 8th element carries the I-V normalisation width.
    # Seven-element jobs (anything built before v1.1.10) still run unchanged.
    params, run_id, targets, models, structures, temp, nf = job[:7]
    iv_width_um = job[7] if len(job) > 7 else None
    rdir = os.path.join(RUNS, "fit_%s" % run_id)
    os.makedirs(rdir, exist_ok=True)
    res = {"run_id": str(run_id), "params": dict(params), "status": "fail",
           "stage": "init", "curves": {}, "metrics": None, "wall_s": 0.0,
           "run_dir": rdir, "iv_width_um": iv_width_um}
    t0 = time.time()
    try:
        # one card per device polarity present in the targets
        res["stage"] = "card"
        cards = {}
        for dev in sorted(set(t["device"] for t in targets)):
            pol = "pmos" if dev.endswith("_p") else "nmos"
            cpath = os.path.join(rdir, "%s.lib" % dev)
            cardgen.write_card(cpath, models.get(dev, dev),
                               params.get(dev, params),
                               polarity=pol,
                               structure=(structures or {}).get(dev),
                               run_id=run_id)
            cards[dev] = cpath

        res["stage"] = "spice"
        errs = []
        # derived curves ride on their parent sweep -- no deck, no run
        run_targets = [t for t in targets if DERIVED not in t["name"]]
        want = set(t["name"] for t in targets)
        for t in run_targets:
            kind, kw = _sweep_deck_args(t)
            base = t["name"]
            deck = os.path.join(rdir, "%s.sp" % base)
            cardgen.write_deck(deck, kind, cards[t["device"]],
                               models.get(t["device"], t["device"]),
                               base, temp=temp, nf=nf, **kw)
            rc, to = _run(spice_command("%s.sp" % base), rdir, SPICE_TIMEOUT,
                          "run_%s.log" % base)
            lis = os.path.join(rdir, "%s.lis" % base)
            bad, msg = has_error(lis)
            if to:
                errs.append("%s: timed out" % base)
                continue
            if bad:
                errs.append("%s: %s" % (base, msg[:120]))
                continue
            try:
                curves = parse_lis(lis)
                # Match on the QUANTITY row, not the printed name. HSPICE
                # strips the wrapper -- `.print dc i(M1)` comes back named
                # `m1` -- so asking for "i(vd)" finds nothing. Asking for a
                # current finds the current column whatever it is called.
                if kind == "cv":
                    # An AC listing is a DIFFERENT SHAPE from a DC one: its
                    # quantities are two words (`i real`, `i imag`), and the
                    # gate bias is not a column at all -- HSPICE writes one
                    # table per bias and puts the bias in a
                    # '*** parameter 0:vg = ... ***' line above it. Asking
                    # sweep_columns for a "volt" x and a "cgg" y found neither,
                    # every C-V sweep failed to parse, and because a result is
                    # only `ok` when EVERY sweep parses, that one bug marked
                    # all 990 points of every evaluation as a failure --
                    # including the eight I-V sweeps that were fine.
                    # cv_columns reads the AC shape and does the
                    # C = -Im(I(vg))/(2*pi*f) arithmetic where it can be seen.
                    #
                    # v1.1.17: TWO INDEPENDENT ROUTES TO THE SAME Cgg.
                    # `op_gate_row` reads HSPICE's own operating-point print,
                    # which is in every listing because `.option list node` is
                    # in every deck. It gives Cgg AND the gate ROW -- Cgd,
                    # Cgs, Cgb -- which is the quantity the reference CSV
                    # holds. It also means a C-V sweep can no longer be LOST:
                    # if the AC table fails to parse for any reason, Cgg comes
                    # from the op-point print instead, and the run continues.
                    # Step 19 died because there was only one route.
                    row = None
                    try:
                        row = op_gate_row(lis)
                    except Exception:
                        row = None
                    try:
                        v, i = cv_columns(curves, kw.get("freq", 1.0e6))
                    except Exception:
                        if row is None:
                            raise
                        v, i = row["vg"], row["cgg"]
                        res.setdefault("cv_from_oppoint", []).append(base)
                    if row is not None:
                        _cv_attach_row(res, base, row, v, i, want,
                                       curves, kw.get("freq", 1.0e6))
                else:
                    v, i = sweep_columns(curves, x_hint="volt",
                                         y_hint="current")
                    # v1.1.10: amperes for the whole device -> amperes per
                    # micron of the same width the targets were divided by.
                    if iv_width_um:
                        i = i / float(iv_width_um)
                if len(v) < 3:
                    errs.append("%s: only %d points parsed" % (base, len(v)))
                    continue
                res["curves"][base] = (v, i)
            except Exception as exc:
                errs.append("%s: %s: %s" % (base, type(exc).__name__, exc))

        # v1.1.17: derived curves are not simulations. Counting them here
        # would make n_ok exceed n_all and every good run would be reported
        # `partial`.
        n_all = len(run_targets)
        n_ok = sum(1 for t in run_targets if t["name"] in res["curves"])
        res["status"] = ("ok" if n_ok == n_all
                         else "partial" if n_ok else "fail")
        if errs:
            res["error"] = "; ".join(errs[:4])
        res["stage"] = "done"
        return res
    except Exception as exc:
        res["error"] = "%s: %s" % (type(exc).__name__, exc)
        return res
    finally:
        res["wall_s"] = round(time.time() - t0, 1)


class HSpiceEvaluator(object):
    """Same interface as l3_exec.execute.TCADEvaluator, over one tool.

    `evaluate_batch(param_dicts, tag)` returns result dicts carrying
    `curves` -- {sweep_name: (v, i)} -- which the curve scorer consumes.
    """

    name = "hspice"

    def __init__(self, targets, models=None, structures=None, n_parallel=8,
                 temp=27.0, nf=1, scorer=None, iv_width_um=None):
        self.targets = list(targets)
        self.models = models or {}
        self.structures = structures or {}
        self.n_parallel = int(n_parallel)
        self.temp = float(temp)
        self.nf = int(nf)
        self.scorer = scorer
        # v1.1.10: None keeps the v1.1.9 behaviour (model current per DEVICE);
        # a number divides every I-V current by that width in microns.
        self.iv_width_um = (float(iv_width_um) if iv_width_um else None)

    def evaluate_batch(self, param_dicts, tag="f"):
        jobs = [(p, "%s%03d" % (tag, i), self.targets, self.models,
                 self.structures, self.temp, self.nf, self.iv_width_um)
                for i, p in enumerate(param_dicts)]
        if self.n_parallel > 1 and len(jobs) > 1:
            with Pool(processes=min(self.n_parallel, len(jobs))) as pool:
                results = pool.map(_one, jobs)
        else:
            results = [_one(j) for j in jobs]
        for r in results:
            if self.scorer is not None and r.get("curves"):
                try:
                    r["metrics"] = self.scorer.as_metrics(r["curves"])
                except Exception as exc:
                    r["metric_warn"] = str(exc)
            r.setdefault("failure_class",
                         "ok" if r["status"] == "ok" else "spice_error")
        ok = sum(1 for r in results if r["status"] == "ok")
        print("      batch done: %d/%d ok" % (ok, len(results)))
        return results
