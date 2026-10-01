"""l1_spec.curve_scorer -- fit a MODEL CURVE to a REFERENCE CURVE.

WHY THIS EXISTS
---------------
Every scorer already in TCADOpt (`l1_spec/scorer.py`) reduces a simulation to
scalar figures of merit and combines them:

    score = sum_i w_i * log10(metric_i) - penalties          [CappedScalarScorer]

That is the right objective for DESIGN optimization -- "make I_ON large while
I_OFF stays under a cap". It is the wrong objective for PARAMETER EXTRACTION,
which asks a different question:

    does the compact model's ENTIRE I-V curve lie on top of the TCAD curve,
    at every bias point, across every decade of current?

Matching four scalars does not do that. Two very different parameter sets can
reproduce the same I_ON, I_OFF, SS and V_th while disagreeing badly in between,
and it is exactly "in between" that a circuit simulator spends its time. So this
module adds the missing objective: a residual over the whole measured curve.

THE RESIDUAL, AND WHY IT HAS TWO HALVES
---------------------------------------
Drain current spans about eight decades from sub-threshold leakage to the
on-state. One error measure cannot serve both ends:

  * A plain relative error (Id_model - Id_ref)/Id_ref is dominated entirely by
    the on-state. Sub-threshold, where the current is a millionth as large,
    contributes essentially nothing, so the fit is free to be wrong by a factor
    of ten down there and still look excellent.

  * A plain log error log10(Id_model/Id_ref) treats every decade equally, which
    is right for sub-threshold, but it stops discriminating in the on-state:
    being 3% off is 0.013 decades, a number so small the optimizer cannot see it
    against sub-threshold noise.

So the residual is split at a current threshold and reported as two numbers that
are each meaningful on their own:

    E_sub = RMS of  log10(|Id_model| / |Id_ref|)     over points below I_split
            -> reads directly as "decades of error", the natural unit of
               sub-threshold accuracy

    E_on  = RMS of  (Id_model - Id_ref) / Id_ref     over points at or above
            I_split
            -> reads directly as "fractional error", the natural unit of drive
               accuracy

    total = w_sub * E_sub + w_on * E_on

and the score handed to the optimizer is  -total  (TCADOpt maximizes).

Keeping the two halves separate is not cosmetic. When a fit stalls, the two
numbers say WHICH half stalled, and therefore which parameters to unfreeze --
a single blended number cannot tell you that.

I_split defaults to the same constant-current threshold used to define V_th, so
"sub-threshold" here means the same thing it means everywhere else in the
project rather than being a new arbitrary line.

WHAT CHANGED IN v1.1.3, AND WHY -- THE NOISE FLOOR HAD ONE UNIT
---------------------------------------------------------------
v1.1.2 carried a single `rel_floor`, documented as "currents below this are
noise", default 1e-14 A. It was applied to EVERY target:

    good = isfinite(model) & isfinite(ref) & (|ref| > rel_floor)

`kind="cv"` targets hold CAPACITANCE, not current. The reference C-V of this
project runs from 2.98e-17 F to 5.94e-17 F. Every one of those numbers is
smaller than 1e-14, so `good` was False at every C-V point, every C-V sweep was
discarded, and the residual the optimizer and the Jacobian were built from
contained I-V points ONLY.

It was silent. `breakdown()` reported the sweep as `missing`, which the caller
read as "this parameter set does not simulate", and the C-V curves were in fact
being simulated and parsed perfectly. Measured on the real run:

    targets            10 sweeps, 990 points
    residual           804 points          <- 8 I-V sweeps only
    discarded          186 = 182 C-V points (ALL of them)
                           +   4 I-V points at Vd=0, where the TCAD reference
                               is ~1e-19 A and the floor is doing its job

The consequence was not a small bias. It made every capacitance parameter --
CFS, CFD, CGBO, DELTAWCV, QMTCENCV, QM0, PCLMCV -- report a Jacobian column of
EXACTLY 0.0 and be certified "cannot be determined by this data", in the same
run whose own one-at-a-time probes showed four of them moving Cgg by tens of
percent. A derivative of a residual that does not contain C-V cannot see a
C-V-only parameter. The number was right; the question was void.

THE FIX: a noise floor is a property of the QUANTITY, so there is now one per
kind, and `floor_for(kind)` is the single place that decides.

  iv : `rel_floor`, unchanged, 1e-14 A. Every existing I-V result is therefore
       bit-identical -- 804 points before, 804 points after.
  cv : `cap_floor`, 1e-21 F. Grounded, not guessed: HSPICE prints the AC
       current to 7 significant figures (`-356.9422p`), so the smallest change
       it can express is 1e-16 A, i.e. 1e-16/(2*pi*1e6) = 1.59e-23 F of
       capacitance. (That is also, to 4 digits, the 1.592e-23 F bias-spread
       measured in the Weff regression test -- the C-V chain is at its print
       resolution and nothing else.) 1e-21 F is ~63 print quanta: high enough
       to reject a zero or a parse artefact, ~30000x below the smallest real
       value in the data, so it discards nothing physical.
"""
import math

import numpy as np

_EPS = 1e-30


def _interp_model(v_ref, v_mod, i_mod):
    """Put the model curve on the reference bias grid.

    The deck is normally swept at exactly the reference biases, in which case
    this is the identity. It is done anyway because a simulator is free to add
    or drop a point, and a silently misaligned comparison is the single easiest
    way to produce a fit result that is confidently wrong.

    Interpolation is done on log10|I| so that a point landing between two
    sub-threshold samples is interpolated along the exponential the physics
    actually follows, not along a straight line through it.
    """
    v_mod = np.asarray(v_mod, float)
    i_mod = np.asarray(i_mod, float)
    o = np.argsort(v_mod)
    v_mod, i_mod = v_mod[o], i_mod[o]
    keep = np.concatenate(([True], np.diff(v_mod) > 1e-12))
    v_mod, i_mod = v_mod[keep], i_mod[keep]
    if len(v_mod) < 2:
        return None
    sign = np.sign(np.median(i_mod)) or 1.0
    li = np.log10(np.maximum(np.abs(i_mod), _EPS))
    lq = np.interp(np.asarray(v_ref, float), v_mod, li,
                   left=np.nan, right=np.nan)
    return sign * (10.0 ** lq)


class CurveResidualScorer(object):
    """Score a set of simulated curves against reference curves.

    targets: list of dicts, each
        {"name": str,               a label, e.g. "IdVg_n_vd0.60"
         "v":    array,             the swept bias
         "i":    array,             the reference current at those biases
         "weight": float,           relative importance of this sweep
         "kind": "iv" | "cv"}

    The scorer is called with {name: (v_model, i_model)} and returns a float to
    MAXIMIZE. A missing or unusable sweep returns the engine's standard
    rejection sentinel -1e9, which `run_campaign`'s surrogate hygiene already
    knows to exclude from the GP fit.
    """

    mode = "curve_residual"

    def __init__(self, targets, i_split=1.0e-7, w_sub=1.0, w_on=1.0,
                 rel_floor=1.0e-14, cap_floor=1.0e-21, report=None):
        self.targets = list(targets)
        self.i_split = float(i_split)
        self.w_sub = float(w_sub)
        self.w_on = float(w_on)
        self.rel_floor = float(rel_floor)   # CURRENTS below this are noise (A)
        self.cap_floor = float(cap_floor)   # CAPACITANCES below this are noise (F)
        self.report = report or []

    # ------------------------------------------------------------------ floors
    def floor_for(self, kind):
        """The noise floor for one kind of target, in that kind's own unit.

        A noise floor is a property of the QUANTITY being compared, so it
        cannot be a single number shared by amperes and farads. Everything that
        filters reference points -- this module and l6_verify.identifiability --
        asks here, so the two can never drift apart again.
        """
        return self.cap_floor if kind == "cv" else self.rel_floor

    # -------------------------------------------------------------- residuals
    def residuals(self, name, v_ref, i_ref, v_mod, i_mod, kind="iv"):
        """Per-sweep error breakdown. Returns None if the sweep is unusable."""
        i_q = _interp_model(v_ref, v_mod, i_mod)
        if i_q is None:
            return None
        a_ref = np.abs(np.asarray(i_ref, float))
        a_mod = np.abs(i_q)
        good = (np.isfinite(a_mod) & np.isfinite(a_ref)
                & (a_ref > self.floor_for(kind)))
        if good.sum() < 3:
            return None
        a_ref, a_mod = a_ref[good], np.maximum(a_mod[good], _EPS)

        if kind == "cv":
            # Capacitance spans well under one decade, so the log/linear split
            # is meaningless here: one relative error over every point is both
            # correct and directly readable as "percent off".
            rel = (a_mod - a_ref) / a_ref
            return {"name": name, "n": int(good.sum()),
                    "e_sub": 0.0, "n_sub": 0,
                    "e_on": float(np.sqrt(np.mean(rel ** 2))),
                    "n_on": int(good.sum()),
                    "max_abs_rel": float(np.max(np.abs(rel)))}

        sub = a_ref < self.i_split
        on = ~sub
        e_sub = e_on = 0.0
        if sub.sum() >= 2:
            d = np.log10(a_mod[sub]) - np.log10(a_ref[sub])
            e_sub = float(np.sqrt(np.mean(d ** 2)))
        if on.sum() >= 2:
            r = (a_mod[on] - a_ref[on]) / a_ref[on]
            e_on = float(np.sqrt(np.mean(r ** 2)))
        rel_all = (a_mod - a_ref) / a_ref
        return {"name": name, "n": int(good.sum()),
                "e_sub": e_sub, "n_sub": int(sub.sum()),
                "e_on": e_on, "n_on": int(on.sum()),
                "max_abs_rel": float(np.max(np.abs(rel_all)))}

    # ----------------------------------------------------------------- scoring
    def breakdown(self, model_curves):
        """Full per-sweep report. `model_curves`: {name: (v, i)}."""
        rows, wsum, acc = [], 0.0, 0.0
        for t in self.targets:
            mc = model_curves.get(t["name"])
            if mc is None:
                rows.append({"name": t["name"], "missing": True})
                continue
            r = self.residuals(t["name"], t["v"], t["i"], mc[0], mc[1],
                               kind=t.get("kind", "iv"))
            if r is None:
                rows.append({"name": t["name"], "missing": True})
                continue
            w = float(t.get("weight", 1.0))
            r["weight"] = w
            r["error"] = self.w_sub * r["e_sub"] + self.w_on * r["e_on"]
            rows.append(r)
            acc += w * r["error"]
            wsum += w
        total = (acc / wsum) if wsum > 0 else None
        n_missing = sum(1 for r in rows if r.get("missing"))
        return {"per_sweep": rows, "total_error": total,
                "n_missing": n_missing, "n_sweeps": len(self.targets)}

    def __call__(self, model_curves):
        """The optimizer's objective: -total_error, to be MAXIMIZED."""
        if not model_curves:
            return -1e9
        b = self.breakdown(model_curves)
        # Any sweep the model could not produce means this parameter set does
        # not simulate. Partial credit there would teach the GP that breaking
        # the model is a way to score well.
        if b["total_error"] is None or b["n_missing"]:
            return -1e9
        t = b["total_error"]
        if not (t == t and abs(t) < 1e30):
            return -1e9
        return -float(t)

    def as_metrics(self, model_curves):
        """Flatten the breakdown into a metrics dict for the experiment DB, so
        every fit attempt is queryable later exactly like a design trial."""
        b = self.breakdown(model_curves)
        out = {"fit_total_error": b["total_error"],
               "fit_n_missing": b["n_missing"],
               "fit_n_sweeps": b["n_sweeps"]}
        subs, ons = [], []
        for r in b["per_sweep"]:
            if r.get("missing"):
                continue
            out["fit_%s_e_sub_dec" % r["name"]] = r["e_sub"]
            out["fit_%s_e_on_rel" % r["name"]] = r["e_on"]
            if r["n_sub"]:
                subs.append(r["e_sub"])
            if r["n_on"]:
                ons.append(r["e_on"])
        if subs:
            out["fit_worst_sub_decades"] = max(subs)
        if ons:
            out["fit_worst_on_pct"] = 100.0 * max(ons)
        return out


def build_curve_scorer(targets, cfg=None):
    """Factory mirroring `scorer.build_scorer`, driven by the spec's
    `fit:` block so a fit problem is described in YAML like any other."""
    cfg = cfg or {}
    return CurveResidualScorer(
        targets,
        i_split=float(cfg.get("i_split_A_per_um", 1.0e-7)),
        w_sub=float(cfg.get("w_subthreshold", 1.0)),
        w_on=float(cfg.get("w_on_state", 1.0)),
        rel_floor=float(cfg.get("current_noise_floor_A", 1.0e-14)),
        cap_floor=float(cfg.get("capacitance_noise_floor_F", 1.0e-21)),
        report=cfg.get("report"))
