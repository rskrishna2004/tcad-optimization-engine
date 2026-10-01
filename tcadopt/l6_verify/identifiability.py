"""l6_verify.identifiability -- can this data determine these parameters at all?

THE QUESTION THIS ANSWERS
-------------------------
An extraction produces a number for every parameter. That is not the same as
determining every parameter. If two parameters change the simulated curve in
the same way, then infinitely many pairs of values fit the data equally well,
and the two numbers the optimizer happens to report are one arbitrary choice out
of that infinite set. They will look precise and they will not transfer to a
different geometry, temperature or bias.

This is called a DEGENERACY (or a lack of identifiability), and it is the single
most common way a compact-model extraction is quietly wrong. It cannot be found
by looking at the fit error, because a degenerate fit fits perfectly. It has to
be measured separately, and this module measures it.

WHAT CHANGED IN v1.1.1, AND WHY
-------------------------------
v1.1.0 shipped this module and it was run for real against PrimeSim HSPICE
U-2023.03 on a 4-sheet GAA nanosheet FET.  Reading its own output against the
code that produced it exposed four defects.  All four are fixed here, and the
fixes are the reason this file exists in this form.

  (1) THE RANKING COMPARED DIFFERENT UNITS.
      The column for a `log` parameter was divided by a step in ln(p), so it
      carried units of d(residual)/d(ln p) -- dimensionless.  The column for a
      `lin` parameter was divided by a step in p, so it carried units of
      d(residual)/dp -- per volt, per ohm, per metre-squared-per-volt-second.
      Sorting those numbers against each other and calling the result a
      sensitivity ranking is a unit error.  In the v1.1.0 run it put PHIG at
      2.36e+02 and U0 at 2.78e+00 and reported PHIG as 85x stronger, when the
      only real difference was that one column was per-volt and the other was
      per-log.

      FIX: every column is now converted to a single common quantity before
      anything is compared -- see SWING below.

  (2) THE DEAD/ALIVE THRESHOLD WAS RELATIVE TO THAT BROKEN RANKING.
      `DEAD_FRAC = 1e-3` meant "dead if smaller than one thousandth of the
      largest column".  With the largest column in the wrong units, the cutoff
      landed at 0.236 and three parameters (PCLM 0.229, PDIBL1 0.220,
      CDSCD 0.210) were declared "not measured" by a margin of a few percent
      against a number that had no physical meaning.

      FIX: the threshold is now absolute and physical -- see SWING_MIN.

  (3) PARAMETERS WERE PROBED AT THE BOTTOM OF THEIR OWN RANGE.
      CIT, DVT0, UD and RDSWMIN all have a model default of exactly 0 (checked
      against HSPICE's own echo of the card, not against the manual's tables).
      A `log` axis cannot hold 0, so the probe centre fell back to the range
      floor -- 1e-6, 1e-3, 1e-4, 1e-3.  Each of those parameters enters its
      term multiplicatively, so d(residual)/d(ln p) = p * d(residual)/dp goes
      to zero as p goes to zero REGARDLESS of how strong the parameter is.
      Reporting them as "the data does not respond to this" measured where the
      probe was put, not what the data contains.

      FIX: a centre within EDGE_FRAC of either end of its range is moved to a
      defensible interior point, the move is recorded, and the report says so
      in words.  See `plan_perturbations`.

  (4) ONE STEP WAS 90% OF A PARAMETER'S ENTIRE RANGE.
      PHIG is `lin` with base 4.50, so a 3% relative step gave +-0.135 V --
      a 270 mV central difference across a range only 300 mV wide.  In
      sub-threshold log10(I) is genuinely linear in PHIG so that chord is a
      fair derivative; in the on-state the response is not linear and the
      chord is a range average, not a derivative.

      FIX: no step may exceed MAX_STEP_FRAC of the parameter's range, and
      `converged_step` measures directly whether the derivative has stopped
      changing with step size -- the same convergence discipline l6_verify
      already applies to a TCAD mesh.

WHAT IS MEASURED NOW: SWING
---------------------------
For each parameter the module reports

    SWING = the RMS change in the scored residual produced by moving that
            parameter across its whole plausible range.

It is computed as ||dr/dc|| * (range width in c) / sqrt(N), where c is the
parameter's own natural coordinate -- p for a linear parameter, ln(p) for one
that spans decades -- so the coordinate cancels and every parameter ends up
expressed in the same quantity.

SWING is a FIRST-ORDER estimate: it is a local derivative multiplied by a
range, not a re-evaluation at both ends of the range.  Declaring the same
parameter on a linear axis and on a log axis therefore gives slightly different
SWINGs -- for a range spanning 16x, measured on an analytic test model, the two
differ by about 11%.  That is the chord-versus-tangent difference.

THAT 11% ESTIMATE WAS MEASURED ON A SMOOTH ANALYTIC SURFACE AND IT DOES NOT
HOLD ON THE REAL MODEL.  v1.1.6 ran this module on a real Stage-4 card and the
same step measured PCLMCV two ways:

    local derivative x range width        SWING = 0.006754  -> "cannot be
                                                                determined"
    the residual re-evaluated at
    PCLMCV = 0.013, 0.13 and 1.3          spread = 0.0987   -> plainly
                                                                determinable

A factor of FIFTEEN, not eleven per cent, and on the wrong side of the cut.
The cause is not subtle: PCLMCV's effect on the capacitance is almost nil from
0.013 to 0.13 and then large from 0.13 to 1.3, so a derivative taken at 0.013
knows nothing about the part of the range that matters.  Any parameter that
sits inside an exponential, a power law or a max(0, ...) will do the same --
and BSIM-CMG is full of them (K0 sits inside exp(), eq. 3.525).

So the derivative SWING is kept, because it is cheap enough to run over every
parameter at once and it is right for the many parameters that are locally
linear, but it is NO LONGER THE LAST WORD.  `scan_swing` below measures the
same quantity by re-evaluating the residual across the declared range, and for
any parameter near the cut, or any parameter whose model equation is non-linear
in it, the scan is the number to believe.  Where the two disagree by more than
about 2x, the scan wins and the disagreement is itself worth reporting: it says
the parameter's effect is concentrated somewhere other than where the centre
sits.

SWING is read directly:

  * where the reference current is ABOVE `i_split` the residual is fractional
    current error, so SWING = 0.01 means "sweeping this parameter across its
    entire range moves the current by about 1% RMS".
  * where it is BELOW `i_split` the residual is log10 current, so SWING = 0.01
    means "about 0.01 decades RMS", i.e. 2.3%.

Both regions are also reported separately (`swing_sub`, `swing_on`), and so is
the per-sweep breakdown.  That answers the question an extraction actually
faces -- WHICH STAGE AND WHICH SWEEP SHOULD FIT THIS PARAMETER -- instead of
only "is it dead".

A parameter whose SWING is below SWING_MIN cannot be determined by this data:
the entire range of it is worth less than the accuracy we are trying to fit to,
so the optimizer will return whatever it started from.

WHAT CHANGED IN v1.1.3, AND WHY
-------------------------------
v1.1.2 shipped and was run for real.  Reading ITS output against the code that
produced it exposed a fifth defect, and this one was not in the ranking -- it
was in the data the ranking was computed from.

  (5) THE C-V SWEEPS WERE NEVER IN THE RESIDUAL.
      `residual_vector` filtered reference points with

          good = ... & (a_ref > scorer.rel_floor)

      and `rel_floor` is a CURRENT noise floor, 1e-14 A.  A `kind="cv"` target
      holds capacitance: this project's reference C-V runs from 2.98e-17 F to
      5.94e-17 F, so every C-V point failed the test and every C-V sweep was
      dropped.  Measured: 10 sweeps and 990 points went in; 804 came out -- the
      eight I-V sweeps, plus the correct rejection of 4 Vd=0 points where the
      TCAD current really is ~1e-19 A.

      The damage was not a bias, it was a void question.  CFS, CFD, CGBO,
      DELTAWCV, QMTCENCV, QM0 and PCLMCV each reported a column norm of EXACTLY
      0.000e+00 and were certified "cannot be determined by this data" -- in the
      same run whose own one-at-a-time probes had just shown four of them moving
      Cgg by tens of percent.  A derivative of a residual that contains no C-V
      cannot see a C-V-only parameter.  Every number was arithmetically correct
      and none of them meant what the report said they meant.

      FIX: the floor is now a property of the QUANTITY.  `CurveResidualScorer`
      owns `floor_for(kind)` -- amperes for `iv`, farads for `cv` -- and this
      module asks it rather than reaching for `rel_floor` directly, so the two
      cannot drift apart again.  A C-V residual entry is a fractional error,
      the same unit as an I-V on-state entry, so SWING stays comparable; but
      mixing them in one `on-state` column would hide which half moved, so
      `region_masks` + `analyse(cvm=...)` report `swing_cv` separately.

      GENERAL LESSON, worth more than the fix: a filter that silently removes
      data is the most dangerous line in an analysis tool, because everything
      downstream keeps working and keeps printing.  Anything that drops points
      must say how many it dropped and from where.  `analyse` now reports the
      per-kind point count for exactly that reason.

  (6) A PARAMETER CAN BE SWITCHED OFF BY A DIFFERENT PARAMETER, and this
      module cannot see it.  `plan_perturbations` guards against a probe centre
      sitting at the edge of the parameter's OWN range -- defect (3).  It has
      no way to know that BSIM-CMG evaluates its whole charge-centroid section
      "only if QMTCENIV or QMTCENCV is non-zero", so that QM0, PQM, AQMTCEN and
      BQMTCEN are all identically inert while QMTCENCV = 0, however well
      centred their own probes are.  The same holds for QM0ACC and PQMACC under
      QMTCENCVA, and for every other prefactor-plus-switch pair in the model.

      There is no fix inside this module, because the gating lives in the
      model's source, not in the ranges: a parameter that is a switch for one
      model can be a coefficient in another.  What there is instead is a rule
      for the caller, and it is the reason this paragraph exists:

          MEASURE A GATED PARAMETER AT A CENTRE WHERE ITS GATE IS OPEN,
          IN A SEPARATE PASS, AND LABEL THE TABLE.

      Two passes at two centres give two internally consistent Jacobians. Do
      NOT merge their columns into one collinearity analysis: a correlation
      between columns taken at different operating points is not a statement
      about the model.  Report them as two tables and say which centre each
      one was measured at.

WHY IT BELONGS IN l6_verify
---------------------------
l6_verify is the layer that refuses to trust a result until it has been checked
by something other than the score that produced it.  Mesh convergence does that
for a TCAD champion.  This does it for an extracted parameter set.  Same job,
different failure mode -- and, as of v1.1.3, the check has itself been checked
twice, each time against its own output on real silicon-model data.
"""
import numpy as np

# A pair above this is reported as a degeneracy. 0.99 is deliberately strict:
# below it two parameters still share most of their effect but retain a little
# independent signal, which a wider bias range can often separate.
COLLINEAR_WARN = 0.99
COLLINEAR_NOTE = 0.90

# ---------------------------------------------------------------------------
# SWING_MIN -- the absolute threshold that replaces v1.1.0's relative DEAD_FRAC.
#
# 0.01 means: sweeping the parameter across its ENTIRE plausible range changes
# the fitted quantity by 1% RMS (1% of current above i_split, 0.01 decades =
# 2.3% below it).  A compact model is not expected to track TCAD to better than
# a few percent, so a parameter worth less than 1% across its whole range is
# below the model-form error and cannot be extracted from this data no matter
# how the optimizer is configured.  Raise it to be stricter; every SWING is
# reported so the cut can be re-made without re-running anything.
# ---------------------------------------------------------------------------
SWING_MIN = 1.0e-2

# A probe centre closer than this (as a fraction of the range width, measured in
# the parameter's own coordinate) to either end is unusable: at the bottom of a
# log range a multiplicative parameter has no derivative to measure.
EDGE_FRAC = 0.02

# No central difference may span more than this fraction of the parameter's
# range. Above that it is a chord across the range, not a local derivative.
MAX_STEP_FRAC = 0.10

# Fallback relative step when the caller gives no range for a parameter.
DEFAULT_REL_STEP = 0.02


# ===========================================================================
#  residual
# ===========================================================================
def residual_vector(scorer, model_curves, want_masks=False):
    """Flatten a set of curves into one residual vector, using the same
    log/linear split the scorer itself uses, so the Jacobian is the Jacobian
    of the objective that was actually optimized -- not of some other quantity
    that merely resembles it.

    With want_masks=True also returns, per residual entry, which sweep it came
    from and whether it is a sub-threshold (log) or on-state (relative) entry.
    Those masks are what let SWING be split by region and by sweep.
    """
    from ..l1_spec.curve_scorer import _interp_model
    v, src, sub_mask = [], [], []
    for t in scorer.targets:
        mc = model_curves.get(t["name"])
        if mc is None:
            return (None, None, None) if want_masks else None
        iq = _interp_model(t["v"], mc[0], mc[1])
        if iq is None:
            return (None, None, None) if want_masks else None
        a_ref = np.abs(np.asarray(t["i"], float))
        a_mod = np.abs(iq)
        # The floor must be in the unit of the quantity being compared. Ask the
        # scorer; fall back to the old single current floor only for a scorer
        # too old to have the accessor, and then only for I-V, because applying
        # a current floor to farads is precisely defect (5).
        kind = t.get("kind", "iv")
        if hasattr(scorer, "floor_for"):
            floor = scorer.floor_for(kind)
        else:
            floor = 0.0 if kind == "cv" else scorer.rel_floor
        good = np.isfinite(a_mod) & np.isfinite(a_ref) & (a_ref > floor)
        a_ref, a_mod = a_ref[good], np.maximum(a_mod[good], 1e-30)
        w = float(t.get("weight", 1.0)) ** 0.5
        if kind == "cv":
            r = (a_mod - a_ref) / a_ref
            s = np.zeros(r.shape, bool)
        else:
            sub = a_ref < scorer.i_split
            r = np.empty_like(a_ref)
            r[sub] = np.log10(a_mod[sub]) - np.log10(a_ref[sub])
            r[~sub] = (a_mod[~sub] - a_ref[~sub]) / a_ref[~sub]
            s = sub
        v.append(w * r)
        src.append(np.array([t["name"]] * len(r), dtype=object))
        sub_mask.append(s)
    if not v:
        return (None, None, None) if want_masks else None
    out = np.concatenate(v)
    if not want_masks:
        return out
    return out, np.concatenate(src), np.concatenate(sub_mask)


def region_masks(scorer, src):
    """Split a residual vector by TARGET KIND, given the per-entry sweep names.

    `residual_vector`'s `sub` mask splits I-V into log (sub-threshold) and
    relative (on-state) entries. A C-V entry is a relative error too, so it
    lands in `~sub` and would be averaged in with on-state drain current --
    arithmetically fine, and useless for deciding which measurement determines
    a parameter. This returns the C-V mask so the two can be reported apart.

    Returns {"cv": bool array, "iv": bool array, "n_cv": int, "n_iv": int}.
    """
    # v1.1.17: `src` is None when residual_vector found no usable curve at
    # all. That happens for real -- Step 19 lost both C-V sweeps to a parser
    # fault -- and until now it raised
    #     TypeError: 'NoneType' object is not iterable
    # four levels down, which read like an engine bug and killed the run.
    # An empty split is the honest answer to "which entries are C-V" when
    # there are no entries, and it lets the caller report a missing curve
    # instead of a stack trace.
    if src is None:
        e = np.zeros(0, bool)
        return {"cv": e, "iv": e, "n_cv": 0, "n_iv": 0, "empty": True}
    kinds = {}
    for t in getattr(scorer, "targets", []):
        kinds[t["name"]] = t.get("kind", "iv")
    cv = np.array([kinds.get(str(n), "iv") == "cv" for n in src], bool)
    return {"cv": cv, "iv": ~cv, "n_cv": int(cv.sum()), "n_iv": int((~cv).sum())}


# ===========================================================================
#  perturbation planning -- this is defect (3) and (4)
# ===========================================================================
def plan_perturbations(params, names, ranges=None, rel_step=DEFAULT_REL_STEP,
                       abs_steps=None, clip=True):
    """Decide, per parameter, exactly where and how far to perturb -- and say so.

    `ranges`    : {name: (lo, hi, "lin"|"log")}. Without it a parameter falls
                  back to v1.1.0 behaviour and is flagged `no_range`, because
                  SWING cannot be formed without a range.
    `abs_steps` : {name: step} to override the step in the parameter's own
                  natural coordinate (volts for a lin parameter, ln-units for a
                  log one). Use it for anything whose meaningful scale is not a
                  fixed fraction of its value -- a gate work function's scale is
                  millivolts whatever its absolute value happens to be.

    Returns a list of dicts, one per parameter, each carrying the base value,
    the value actually probed around, the two perturbed values, the step, the
    coordinate, the range width in that coordinate, and any warnings. Nothing
    about the perturbation is implicit: it is all in this record and it all ends
    up in the JSON.
    """
    ranges = ranges or {}
    abs_steps = abs_steps or {}
    plan = []
    for n in names:
        base = float(params[n])
        rec = {"name": n, "base": base, "warnings": []}
        rng = ranges.get(n)

        if rng is None:
            # No range: keep v1.1.0's relative step, and refuse to form SWING.
            span = abs(base) if abs(base) > 1e-12 else 1.0
            h = 2.0 * rel_step * span
            rec.update({"coord": "lin", "centre": base, "width": None,
                        "lo": base - 0.5 * h, "hi": base + 0.5 * h, "h": h})
            rec["warnings"].append(
                "no range given -- sensitivity is reported in raw 1/[%s] units "
                "and is NOT comparable with any other parameter" % n)
            plan.append(rec)
            continue

        lo_r, hi_r, mode = float(rng[0]), float(rng[1]), str(rng[2]).lower()

        if mode == "log":
            if lo_r <= 0:
                rec["warnings"].append(
                    "log range with a non-positive lower bound -- treated as lin")
                mode = "lin"
        if mode == "log":
            c_lo, c_hi = np.log(lo_r), np.log(hi_r)
            width = c_hi - c_lo
            c_base = np.log(base) if base > 0 else c_lo
            if base <= 0:
                rec["warnings"].append(
                    "base value is %g, which a log axis cannot hold" % base)
        else:
            c_lo, c_hi = lo_r, hi_r
            width = c_hi - c_lo
            c_base = base

        # ---- defect (3): a centre at the edge of its own range ------------
        c_probe = c_base
        edge = None
        if width > 0:
            if (c_base - c_lo) / width < EDGE_FRAC:
                edge = "bottom"
            elif (c_hi - c_base) / width < EDGE_FRAC:
                edge = "top"
        if edge is not None:
            # Move to an interior point. A quarter of the way in from the edge
            # is far enough for the parameter's term to be active and near
            # enough that it is still a small, physically ordinary value.
            c_probe = c_lo + 0.25 * width if edge == "bottom" \
                else c_hi - 0.25 * width
            p_probe = float(np.exp(c_probe)) if mode == "log" else float(c_probe)
            rec["warnings"].append(
                "base %g sits at the %s of its range; a perturbation there "
                "measures the probe position, not the data. Probed at %g "
                "instead -- read this parameter's SWING as 'what this data "
                "could determine IF the parameter were active', not as its "
                "sensitivity at the default." % (base, edge, p_probe))

        # ---- defect (4): step size ---------------------------------------
        if n in abs_steps:
            h = float(abs_steps[n])
            rec["warnings"].append("step set explicitly to %g in %s coordinate"
                                   % (h, "ln(p)" if mode == "log" else "p"))
        elif mode == "log":
            h = 2.0 * np.log1p(rel_step)
        else:
            # The step is taken relative to the point actually PROBED, not to
            # the original base value. For a parameter whose default is 0 the
            # base carries no scale at all, and falling back to 1.0 there once
            # produced a step 120x wider than the parameter's entire range.
            ref = c_probe if mode != "log" else base
            span = abs(ref) if abs(ref) > 1e-12 else \
                (abs(width) if width > 0 else 1.0)
            h = 2.0 * rel_step * span

        if width > 0 and h > MAX_STEP_FRAC * width:
            if clip:
                h_new = MAX_STEP_FRAC * width
                rec["warnings"].append(
                    "step %g spanned %.0f%% of the range; a central difference "
                    "that wide is a chord across the range, not a derivative. "
                    "Clipped to %g (%.0f%%)."
                    % (h, 100.0 * h / width, h_new, 100.0 * MAX_STEP_FRAC))
                h = h_new
            else:
                # clip=False is for `converged_step`, whose whole job is to show
                # what an over-wide step does. Clipping there would silently
                # collapse every large step onto the same value and the study
                # would report a flat, meaningless plateau.
                rec["warnings"].append(
                    "step %g spans %.0f%% of the range -- deliberately NOT "
                    "clipped (convergence study)"
                    % (h, 100.0 * h / width))

        # keep both legs inside the range
        half = 0.5 * h
        if c_probe - half < c_lo:
            c_probe = c_lo + half
        if c_probe + half > c_hi:
            c_probe = c_hi - half
        if h <= 0 or not np.isfinite(h):
            rec["warnings"].append("unusable step -- parameter skipped")
            rec.update({"coord": mode, "centre": base, "width": width,
                        "lo": base, "hi": base, "h": 0.0, "skip": True})
            plan.append(rec)
            continue

        c_a, c_b = c_probe - half, c_probe + half
        if mode == "log":
            p_a, p_b, p_c = float(np.exp(c_a)), float(np.exp(c_b)), float(np.exp(c_probe))
        else:
            p_a, p_b, p_c = float(c_a), float(c_b), float(c_probe)

        rec.update({"coord": "ln(p)" if mode == "log" else "p",
                    "mode": mode, "centre": p_c, "width": float(width),
                    "lo": p_a, "hi": p_b, "h": float(h),
                    "range": [lo_r, hi_r], "moved": edge is not None})
        plan.append(rec)
    return plan


# ===========================================================================
#  Jacobian
# ===========================================================================
def jacobian(evaluator, scorer, params, names, rel_step=DEFAULT_REL_STEP,
             log_names=(), ranges=None, abs_steps=None, plan=None,
             progress=None):
    """Central-difference Jacobian of the residual w.r.t. each named parameter.

    Central differences cost 2N simulations instead of N, and they are worth it:
    a one-sided difference on a noisy simulator biases every column in the same
    direction, which shows up as false collinearity -- the exact thing this
    module exists to detect.

    `ranges` supersedes `log_names`: give {name: (lo, hi, "lin"|"log")} and the
    module can form SWING, police the step size, and detect a centre stuck at
    the edge of its range. `log_names` alone is kept so v1.1.0 callers still
    run, but they get raw mixed-unit columns and a warning saying so.
    """
    if plan is None:
        if ranges is None and log_names:
            ranges = {}
            for n in names:
                b = float(params[n])
                if n in log_names and b > 0:
                    ranges[n] = (b / 10.0, b * 10.0, "log")
        plan = plan_perturbations(params, names, ranges=ranges,
                                  rel_step=rel_step, abs_steps=abs_steps)

    cols, used, meta, src, sub = [], [], [], None, None
    for rec in plan:
        n = rec["name"]
        if rec.get("skip"):
            continue
        p_hi, p_lo = dict(params), dict(params)
        p_hi[n], p_lo[n] = rec["hi"], rec["lo"]
        r = evaluator.evaluate_batch([p_hi, p_lo], tag="jac_%s" % n)
        # v1.1.2: accept `partial` as well as `ok`.
        #
        # A result is only `ok` when EVERY sweep parsed. In the v1.1.1 run one
        # sweep TYPE -- C-V -- could not be parsed at all, so every evaluation
        # came back `fail`, and all 34 columns were dropped even though the
        # eight I-V sweeps in each one were perfectly good. Two hours of HSPICE
        # produced nothing.
        #
        # `residual_vector` already refuses to build a vector when a scored
        # sweep is missing, and the hi/lo lengths are compared below, so a
        # partial result that is genuinely unusable still cannot slip through.
        # Rejecting the whole evaluation here was belt AND braces AND a
        # padlock, and the padlock threw away the data.
        bad = [x for x in r if x.get("status") not in ("ok", "partial")]
        if bad:
            why = bad[0].get("error") or "no error text returned"
            rec["warnings"].append("evaluation failed: %s" % why)
            if progress:
                progress(n, None, why)
            continue
        v_hi, s_hi, m_hi = residual_vector(scorer, r[0]["curves"], want_masks=True)
        v_lo = residual_vector(scorer, r[1]["curves"])
        if v_hi is None or v_lo is None or len(v_hi) != len(v_lo):
            why = ("residual vectors did not line up (hi=%s lo=%s) -- a sweep "
                   "present in one run is missing or a different length in the "
                   "other. First run's error: %s"
                   % ("None" if v_hi is None else len(v_hi),
                      "None" if v_lo is None else len(v_lo),
                      r[0].get("error") or "none"))
            rec["warnings"].append(why)
            if progress:
                progress(n, None, why)
            continue
        col = (v_hi - v_lo) / rec["h"]
        cols.append(col)
        used.append(n)
        meta.append(rec)
        if src is None:
            src, sub = s_hi, m_hi
        if progress:
            progress(n, float(np.linalg.norm(col)), None)
    if not cols:
        return None, [], plan, None, None
    return np.column_stack(cols), used, meta, src, sub


# ===========================================================================
#  analysis
# ===========================================================================
def analyse(J, names, meta=None, src=None, sub=None, r0=None,
            noise_floor=None, swing_min=SWING_MIN, cvm=None):
    """Turn a Jacobian into readings that can actually be compared.

    `meta`  : the per-parameter plan records from `plan_perturbations`, which
              carry the range width needed to form SWING.
    `src`   : per-residual-entry sweep name, for the per-sweep breakdown.
    `sub`   : per-residual-entry sub-threshold flag, for the region split.
    `r0`    : the residual vector at the unperturbed centre. Reported so the
              SWING numbers can be read against the error already present.
    `noise_floor` : the column norm measured for a parameter KNOWN to be inert.
              Anything at or below it is numerical noise, not signal.
    `cvm`   : per-residual-entry C-V flag, from `region_masks`. When given, the
              C-V entries get their own SWING column and are taken OUT of the
              on-state column, so "moves the drain current" and "moves the gate
              capacitance" are never averaged into one number.
    """
    if J is None or J.size == 0:
        return {"ok": False, "reason": "no usable Jacobian"}
    norms = np.linalg.norm(J, axis=0)
    npts = J.shape[0]
    if not np.isfinite(norms).any() or float(np.nanmax(norms)) <= 0.0:
        return {"ok": False,
                "reason": "every column of the Jacobian is zero -- no parameter "
                          "changed the simulated curve at all. Either the "
                          "perturbation is too small to register, the simulator "
                          "is returning a cached or identical result, or the "
                          "parameters are not reaching the model."}

    by_name = {}
    if meta:
        for rec in meta:
            by_name[rec["name"]] = rec

    # ---- SWING: the one comparable number ---------------------------------
    swing, swing_sub, swing_on, per_sweep, comparable = {}, {}, {}, {}, {}
    swing_cv = {}
    # on-state means 'I-V above i_split'. Without a C-V mask that is
    # exactly ~sub; with one, the C-V entries move to their own column.
    on_mask = (~sub & ~cvm) if (sub is not None and cvm is not None) \
        else (None if sub is None else ~sub)
    sweeps = sorted(set(src.tolist())) if src is not None else []
    for i, n in enumerate(names):
        rec = by_name.get(n, {})
        w = rec.get("width")
        col = J[:, i]
        if w is None or not np.isfinite(w) or w <= 0:
            comparable[n] = False
            swing[n] = float("nan")
            swing_sub[n] = float("nan")
            swing_on[n] = float("nan")
            swing_cv[n] = float("nan")
            continue
        comparable[n] = True
        swing[n] = float(np.linalg.norm(col) * w / np.sqrt(npts))
        if sub is not None:
            ns, no = int(sub.sum()), int(on_mask.sum())
            swing_sub[n] = float(np.linalg.norm(col[sub]) * w / np.sqrt(ns)) \
                if ns else 0.0
            swing_on[n] = float(np.linalg.norm(col[on_mask]) * w / np.sqrt(no)) \
                if no else 0.0
        if cvm is not None:
            nc = int(cvm.sum())
            swing_cv[n] = float(np.linalg.norm(col[cvm]) * w / np.sqrt(nc)) \
                if nc else 0.0
        if src is not None:
            d = {}
            for s in sweeps:
                m = (src == s)
                k = int(m.sum())
                d[s] = float(np.linalg.norm(col[m]) * w / np.sqrt(k)) if k else 0.0
            per_sweep[n] = d

    # ---- dead / live, on an ABSOLUTE physical threshold --------------------
    dead, live, live_idx, why = [], [], [], {}
    for i, n in enumerate(names):
        if not comparable[n]:
            dead.append(n)
            why[n] = "no range given -- SWING could not be formed"
            continue
        s = swing[n]
        if noise_floor is not None and np.linalg.norm(J[:, i]) <= noise_floor:
            dead.append(n)
            why[n] = ("column norm %.3e is at or below the measured noise floor "
                      "%.3e" % (np.linalg.norm(J[:, i]), noise_floor))
        elif s < swing_min:
            dead.append(n)
            why[n] = ("SWING %.3e -- the parameter's ENTIRE range is worth less "
                      "than %.1f%% RMS, below the threshold" % (s, 100 * swing_min))
        else:
            live.append(n)
            live_idx.append(i)

    # ---- collinearity, over every live column -----------------------------
    pairs = []
    if len(live_idx) >= 2:
        Jl = J[:, live_idx]
        Jn = Jl / np.linalg.norm(Jl, axis=0)
        C = Jn.T @ Jn
        for a_ in range(len(live)):
            for b_ in range(a_ + 1, len(live)):
                r = float(C[a_, b_])
                if abs(r) >= COLLINEAR_NOTE:
                    pairs.append((live[a_], live[b_], r))
        pairs.sort(key=lambda t: -abs(t[2]))
        # v1.1.13: the SVD's right singular vectors, not just its values. The
        # smallest ones name the COMBINATIONS of parameters the data cannot
        # see -- which is the honest answer to "why is VSAT sitting on its
        # box end": it is free to move along a direction nothing measures.
        _u, sv, Vt = np.linalg.svd(Jn, full_matrices=False)
        del _u
        cond = float(sv[0] / sv[-1]) if sv[-1] > 0 else float("inf")
        eff = int(np.sum(sv > sv[0] * 1e-3))
        nulls = null_directions(sv, Vt, live)
    else:
        sv = np.array([1.0])
        cond = float("inf") if len(live_idx) < 2 else 1.0
        eff = len(live_idx)
        nulls = []

    warn = {}
    if meta:
        for rec in meta:
            if rec.get("warnings"):
                warn[rec["name"]] = list(rec["warnings"])

    out = {"ok": True, "names": list(names),
           "swing": swing, "swing_sub": swing_sub, "swing_on": swing_on,
           "swing_cv": swing_cv,
           "n_cv": (int(cvm.sum()) if cvm is not None else 0),
           "n_iv": (int((~cvm).sum()) if cvm is not None else int(J.shape[0])),
           "per_sweep": per_sweep, "sweeps": sweeps,
           "raw_column_norm": dict(zip(names, [float(x) for x in norms])),
           "comparable": comparable,
           "dead": dead, "live": live, "dead_reason": why,
           "collinear": pairs, "condition_number": cond,
           "singular_values": [float(x) for x in sv],
           "null_directions": nulls,
           "effective_rank": eff, "n_free": len(names), "n_live": len(live),
           "n_points": int(npts), "swing_min": float(swing_min),
           "noise_floor": (None if noise_floor is None else float(noise_floor)),
           "warnings": warn}
    if r0 is not None:
        out["r0_norm"] = float(np.linalg.norm(r0))
        out["r0_rms"] = float(np.linalg.norm(r0) / np.sqrt(len(r0)))
    if meta:
        out["plan"] = [{k: v for k, v in rec.items()} for rec in meta]
    return out


# ===========================================================================
#  step-size convergence -- defect (4), measured rather than assumed
# ===========================================================================
SCAN_POINTS = 5


def scan_points(rng, n_points=SCAN_POINTS, base=None):
    """The values to evaluate a parameter at, spread across its DECLARED range.

    Spacing follows the parameter's own coordinate -- even in p for a linear
    parameter, even in ln(p) for a log one -- so a parameter declared over
    decades is sampled over decades rather than piling every point at the top.

    A log-scaled range whose lower bound is 0 (which several BSIM-CMG
    parameters have, being `MPRcz` or `MPRnb` with a 0 default) cannot be
    sampled logarithmically from its bottom, so the bottom is replaced by the
    smaller of `base` and hi/1e4 and the fact is returned so it can be printed.
    """
    lo, hi, mode = float(rng[0]), float(rng[1]), str(rng[2]).lower()
    note = None
    if mode == "log" and lo <= 0:
        alt = hi / 1.0e4
        if base is not None and base > 0:
            alt = min(alt, float(base))
        note = ("log range starts at %g; sampled from %g instead" % (lo, alt))
        lo = alt
    n = max(int(n_points), 2)
    if mode == "log":
        xs = np.exp(np.linspace(np.log(lo), np.log(hi), n))
    else:
        xs = np.linspace(lo, hi, n)
    return [float(x) for x in xs], note


def scan_swing(evaluator, scorer, params, name, rng, n_points=SCAN_POINTS,
               tag=None, src_ref=None, sub_ref=None, cv_ref=None):
    """SWING MEASURED rather than extrapolated.

    Evaluates the residual vector at `n_points` values spread across the
    parameter's declared range and reports the largest RMS displacement of that
    vector from the value at the centre card.  That is the same quantity the
    derivative SWING estimates -- "what is this parameter worth, over its whole
    range, in the residual's own units" -- computed by measurement.

    Every point goes in ONE `evaluate_batch` call, so the whole scan costs the
    same wall time as its slowest single evaluation when the evaluator runs in
    parallel.

    Returns a dict:
      points      : the values evaluated
      err         : scorer total error at each point (None where it failed)
      swing_scan  : max over points of ||r(p) - r(centre)|| / sqrt(N)
      swing_sub / swing_on / swing_cv : the same, restricted to each region
      per_sweep   : the same, restricted to each sweep
      best        : the scanned value with the lowest total error
      n_ok        : how many points produced a usable residual vector
      note        : any adjustment made to the range before sampling
    Fields that could not be formed are absent rather than zero.
    """
    out = {"name": name}
    xs, note = scan_points(rng, n_points=n_points,
                           base=params.get(name))
    if note:
        out["note"] = note
    out["points"] = xs
    cards = []
    for x in xs:
        q = dict(params)
        q[name] = x
        cards.append(q)
    cards.append(dict(params))                     # the centre, last
    res = evaluator.evaluate_batch(cards, tag=(tag or ("scan_%s" % name)))
    vecs, errs = [], []
    for r in res:
        if r.get("status") not in ("ok", "partial"):
            vecs.append(None)
            errs.append(None)
            continue
        v = residual_vector(scorer, r.get("curves"))
        vecs.append(v)
        try:
            e = scorer(r.get("curves"))
            errs.append(None if e is None else -float(e))
        except Exception:
            errs.append(None)
    r_c = vecs[-1]
    out["err"] = errs[:-1]
    out["err_centre"] = errs[-1]
    good = [k for k in range(len(xs))
            if vecs[k] is not None and r_c is not None
            and len(vecs[k]) == len(r_c)]
    out["n_ok"] = len(good)
    if not good:
        out["swing_scan"] = float("nan")
        return out
    npts = len(r_c)

    def _rms(mask):
        best = 0.0
        for k in good:
            d = vecs[k] - r_c
            d = d if mask is None else d[mask]
            m = len(d)
            if m:
                best = max(best, float(np.linalg.norm(d) / np.sqrt(m)))
        return best

    out["swing_scan"] = _rms(None)
    if sub_ref is not None:
        on = (~sub_ref & ~cv_ref) if cv_ref is not None else ~sub_ref
        out["swing_sub_scan"] = _rms(sub_ref)
        out["swing_on_scan"] = _rms(on)
    if cv_ref is not None:
        out["swing_cv_scan"] = _rms(cv_ref)
    if src_ref is not None:
        d = {}
        for s_name in sorted(set(src_ref.tolist())):
            d[s_name] = _rms(src_ref == s_name)
        out["per_sweep_scan"] = d
    ok_err = [(errs[k], xs[k]) for k in good if errs[k] is not None]
    if ok_err:
        out["best"] = min(ok_err)[1]
        out["best_err"] = min(ok_err)[0]
    # v1.1.10: THE CENTRE CARD IS A CANDIDATE TOO. Up to v1.1.9 `best` was
    # the best of the SCANNED points only. Step 12 scanned KSATIV at 0.1,
    # 2.075, 4.05, 6.025 and 8 around a centre of 1.0 and reported
    # best = 2.075 at error 0.236 -- while the centre itself scored 0.106.
    # The box gate then judged the box by a point that was worse than where
    # it started. The centre is evaluated anyway (it is the last card of the
    # batch), so it now competes, and the scan says when it won.
    out["best_is_centre"] = False
    e_c, p_c = out.get("err_centre"), params.get(name)
    if e_c is not None and p_c is not None:
        try:
            p_c = float(p_c)
        except (TypeError, ValueError):
            p_c = None
    if e_c is not None and p_c is not None and np.isfinite(e_c) and (
            "best_err" not in out or e_c < out["best_err"]):
        if "best" in out:
            out["best_scan_point"] = out["best"]
            out["best_scan_err"] = out["best_err"]
        out["best"] = p_c
        out["best_err"] = float(e_c)
        out["best_is_centre"] = True
    del npts
    return out


def scan_vs_derivative(scan, swing_derivative, factor=2.0):
    """One line saying whether the two agree, and which to believe if not."""
    sv = scan.get("swing_scan")
    if sv is None or not np.isfinite(sv) or swing_derivative is None \
            or not np.isfinite(swing_derivative):
        return "scan %s vs derivative %s -- cannot compare" % (
            sv, swing_derivative)
    if swing_derivative <= 0:
        return ("scan %.4g vs derivative 0 -- the derivative saw nothing and "
                "the scan %s" % (sv, "did" if sv > 0 else "agrees"))
    r = sv / swing_derivative
    if 1.0 / factor <= r <= factor:
        return "scan %.4g vs derivative %.4g -- agree (x%.2f)" % (
            sv, swing_derivative, r)
    return ("scan %.4g vs derivative %.4g -- DISAGREE by x%.2f; believe the "
            "scan, and read it as 'the effect is concentrated away from the "
            "centre'" % (sv, swing_derivative, r))


def confirm_dead(evaluator, scorer, params, names, ranges,
                 n_points=SCAN_POINTS, swing_min=None, derivative=None,
                 src_ref=None, sub_ref=None, cv_ref=None, tag="dead"):
    """v1.1.10: never certify a parameter dead from a derivative alone.

    The derivative SWING is a slope at ONE point times the range width. A
    parameter sitting where its own term is flat -- ETA0 at 0.036 in log
    coordinate, PDIBL2 at 1.4e-6, UA at 1.2e-3 -- has a small slope there
    and a large effect elsewhere in its range. Step 12 measured it: of the
    nine parameters the derivative called dead, a scan found FIVE alive,
    PDIBL2 by a factor of 3086.

    This scans every name in `names` across its declared range (one parallel
    batch each, `scan_swing`) and returns, per name:

      scan        the scanned SWING (max RMS residual change over the range)
      derivative  the derivative SWING passed in, if any
      ratio       scan / derivative
      verdict     'dead, confirmed' | 'ALIVE -- the derivative was wrong'
                  | 'unmeasured'
      best, best_is_centre, best_err   from the scan
    """
    cut = SWING_MIN if swing_min is None else float(swing_min)
    derivative = derivative or {}
    out = {}
    for n in names:
        if n not in ranges or n not in params:
            continue
        try:
            s = scan_swing(evaluator, scorer, params, n, ranges[n],
                           n_points=n_points, tag="%s_%s" % (tag, n),
                           src_ref=src_ref, sub_ref=sub_ref, cv_ref=cv_ref)
        except Exception as exc:                       # pragma: no cover
            out[n] = {"verdict": "unmeasured", "error": repr(exc)}
            continue
        sv = s.get("swing_scan")
        d = derivative.get(n)
        rec = {"scan": sv, "derivative": d,
               "best": s.get("best"), "best_err": s.get("best_err"),
               "best_is_centre": s.get("best_is_centre", False),
               "swing_sub_scan": s.get("swing_sub_scan"),
               "swing_on_scan": s.get("swing_on_scan"),
               "swing_cv_scan": s.get("swing_cv_scan")}
        if d is not None and sv is not None:
            rec["ratio"] = (float(sv) / float(d)) if d > 0 else float("inf")
        if sv is None or not np.isfinite(sv):
            rec["verdict"] = "unmeasured"
        elif sv >= cut:
            rec["verdict"] = "ALIVE -- the derivative was wrong"
        else:
            rec["verdict"] = "dead, confirmed"
        out[n] = rec
    return out


def format_confirm_dead(res):
    """The printable table for `confirm_dead`."""
    L = ["  %-11s %-13s %-13s %-9s %s"
         % ("param", "derivative", "scan", "ratio", "verdict"),
         "  " + "-" * 72]
    for n in sorted(res):
        r = res[n]
        d, sv, rt = r.get("derivative"), r.get("scan"), r.get("ratio")
        L.append("  %-11s %-13s %-13s %-9s %s"
                 % (n, "%.4g" % d if d is not None else "-",
                    "%.4g" % sv if sv is not None else "-",
                    ("%.0fx" % rt) if (rt is not None and np.isfinite(rt))
                    else ("inf" if rt is not None else "-"),
                    r.get("verdict", "?")))
    return "\n".join(L)


def converged_step(evaluator, scorer, params, name, rng, steps,
                   rel_to=None):
    """Recompute one column at several step sizes and report whether it settled.

    This is the parameter-extraction equivalent of a mesh-convergence study: a
    derivative that changes when the step changes is not a derivative yet. The
    returned list carries the step, the column norm, the angle in degrees
    between that column and the one taken at the smallest step, and the angle
    to the PREVIOUS step. A derivative that has converged has a norm that stops
    moving AND a direction that stops turning, and the direction is what
    collinearity depends on.

    READ IT AS A PLATEAU, NOT AS "THE SMALLEST STEP IS RIGHT". Shrinking the
    step forever does not improve a derivative taken on a simulator: below some
    size the difference of two nearly identical runs is dominated by the
    solver's own convergence tolerance, and the column becomes noise. The
    trustworthy step is the one in the middle of a flat stretch -- where
    `angle_prev_deg` is near zero and the norm has stopped moving -- with the
    noise floor from a provably inert parameter marking the bottom end.

    The step is deliberately NOT clipped to MAX_STEP_FRAC here: clipping is what
    keeps a production Jacobian honest, but in a convergence study it would
    collapse every large step onto the same value and manufacture a flat
    plateau that means nothing.
    """
    out, ref, prev = [], None, None
    for h in sorted(steps):
        plan = plan_perturbations(params, [name], ranges={name: rng},
                                  abs_steps={name: h}, clip=False)
        J, used, meta, src, sub = jacobian(evaluator, scorer, params, [name],
                                           plan=plan)
        if J is None:
            out.append({"h": h, "ok": False,
                        "why": "; ".join(plan[0].get("warnings", []))
                               or "no column produced"})
            continue
        col = J[:, 0]
        nrm = float(np.linalg.norm(col))
        unit = col / nrm if nrm > 0 else None
        if ref is None:
            ref = unit

        def _ang(u, w):
            if u is None or w is None:
                return None
            c = float(np.clip(np.dot(u, w), -1.0, 1.0))
            return float(np.degrees(np.arccos(abs(c))))

        out.append({"h": h, "ok": True, "norm": nrm,
                    "angle_deg": _ang(unit, ref),
                    "angle_prev_deg": _ang(unit, prev),
                    "lo": meta[0]["lo"], "hi": meta[0]["hi"],
                    "h_used": meta[0]["h"],
                    "swing": (nrm * meta[0]["width"] / np.sqrt(len(col))
                              if meta[0].get("width") else None)})
        prev = unit
    return out


# ===========================================================================
#  report
# ===========================================================================
def report(a, confirmed=None):
    """The printable identifiability report.

    v1.1.10: `confirmed` is the dict `confirm_dead` returns. When it is
    given, a parameter the derivative calls dead but a scan finds alive is
    NOT printed under 'cannot be determined' -- it gets its own block, with
    both numbers, so no report can retire a live parameter on a slope alone.
    """
    confirmed = confirmed or {}
    if not a.get("ok"):
        return ("identifiability: MEASUREMENT FAILED\n  %s"
                % a.get("reason", "unavailable"))
    n_live = a.get("n_live", a["n_free"])
    L = ["identifiability of the extracted parameter set",
         "  parameters probed : %d" % a["n_free"],
         "  residual points   : %d" % a.get("n_points", 0)]
    # Say how the points split. A filter that silently removes a whole class of
    # data is how v1.1.2 certified every capacitance parameter "cannot be
    # determined"; the count is printed so that can never happen unnoticed.
    if a.get("n_cv"):
        L.append("                      (%d I-V + %d C-V)"
                 % (a.get("n_iv", 0), a.get("n_cv", 0)))
    elif a.get("n_points"):
        L.append("                      (I-V only -- no C-V entered the residual)")
    if "r0_rms" in a:
        L.append("  residual at the probe centre : %.4g RMS  (norm %.4g)"
                 % (a["r0_rms"], a["r0_norm"]))
    if a.get("noise_floor") is not None:
        L.append("  measured numerical noise floor : %.3e (column norm)"
                 % a["noise_floor"])
    L += ["  parameters this data can determine : %d" % n_live,
          "  effective rank    : %d   (independent directions among those %d)"
          % (a["effective_rank"], n_live),
          "  condition number  : %.3g" % a["condition_number"]]
    if a["effective_rank"] < n_live:
        L.append("  -> %d MORE live parameter(s) than the data can separate."
                 % (n_live - a["effective_rank"]))

    L.append("")
    has_cv = bool(a.get("n_cv"))
    L.append("  SWING = RMS residual change over the parameter's WHOLE range.")
    L.append("          Above i_split one unit = 100% current error;")
    L.append("          below it one unit = one decade. Cut at %.3g."
             % a["swing_min"])
    if has_cv:
        L.append("          C-V is a separate column: one unit = 100% Cgg error.")
    L.append("")
    if has_cv:
        L.append("  %-11s %-11s %-11s %-11s %-11s %s"
                 % ("param", "SWING", "sub-thr", "on-state", "C-V", ""))
        L.append("  " + "-" * 76)
    else:
        L.append("  %-11s %-11s %-11s %-11s %s"
                 % ("param", "SWING", "sub-thr", "on-state", ""))
        L.append("  " + "-" * 64)
    order = sorted(a["swing"],
                   key=lambda k: -(a["swing"][k]
                                   if np.isfinite(a["swing"][k]) else -1))
    for n in order:
        s = a["swing"][n]
        ss = a.get("swing_sub", {}).get(n, float("nan"))
        so = a.get("swing_on", {}).get(n, float("nan"))
        sc = a.get("swing_cv", {}).get(n, float("nan"))
        mark = "  <-- cannot be determined" if n in a["dead"] else ""
        if n in a["dead"] and n in confirmed:
            v = confirmed[n].get("verdict", "")
            if v.startswith("ALIVE"):
                mark = "  <-- slope ~0 here, but a SCAN says ALIVE"
            elif v.startswith("dead"):
                mark = "  <-- cannot be determined (slope AND scan)"
        if not np.isfinite(s):
            if has_cv:
                L.append("  %-11s %-11s %-11s %-11s %-11s (raw norm %.3e, no range)"
                         % (n, "n/a", "n/a", "n/a", "n/a",
                            a["raw_column_norm"][n]))
            else:
                L.append("  %-11s %-11s %-11s %-11s  (raw norm %.3e, no range)"
                         % (n, "n/a", "n/a", "n/a", a["raw_column_norm"][n]))
        elif has_cv:
            L.append("  %-11s %-11.4g %-11.4g %-11.4g %-11.4g%s"
                     % (n, s, ss, so, sc, mark))
        else:
            L.append("  %-11s %-11.4g %-11.4g %-11.4g%s" % (n, s, ss, so, mark))

    rescued = [n for n in a["dead"]
               if str(confirmed.get(n, {}).get("verdict", "")).startswith(
                   "ALIVE")]
    really = [n for n in a["dead"] if n not in rescued]
    if really:
        L.append("")
        L.append("  CANNOT BE DETERMINED by this data:")
        for n in really:
            why = a.get("dead_reason", {}).get(n, "")
            if n in confirmed and confirmed[n].get("scan") is not None:
                why += "; scan SWING %.3g agrees" % confirmed[n]["scan"]
            L.append("     %-11s %s" % (n, why))
        L.append("     Fitting these would return the starting guess with a")
        L.append("     confident-looking number attached to it.")
    if rescued:
        L.append("")
        L.append("  THE DERIVATIVE SAID DEAD, A SCAN SAYS ALIVE (v1.1.10):")
        for n in rescued:
            c = confirmed[n]
            L.append("     %-11s slope SWING %.3g, scanned SWING %.3g -- the "
                     "parameter sits where its own term is flat"
                     % (n, a["swing"].get(n, float("nan")),
                        c.get("scan", float("nan"))))

    ps = a.get("per_sweep") or {}
    if ps and a.get("sweeps"):
        L.append("")
        L.append("  which sweep carries the information (SWING per sweep):")
        # v1.1.11: the column was 16 wide and the name was cut to its last
        # 15 characters, so `nsfet_n_IdVd_0.38` printed as `fet_n_IdVd_0.38`
        # -- a 17-character sweep name lost the device it belongs to. The
        # column is now as wide as the longest name it has to carry.
        # v1.1.12: with ten sweeps the header ran to 203 characters. Every
        # sweep here belongs to the same device, so the common prefix is
        # printed ONCE, above the table, and the columns carry what differs.
        pre = _common_prefix(list(a["sweeps"]))
        if len(pre) < 4 or len(a["sweeps"]) < 2:
            pre = ""
        short = [s[len(pre):] if pre else s for s in a["sweeps"]]
        if pre:
            L.append("  (every column name below starts with '%s')" % pre)
        cw = max(11, max(len(x) for x in short) + 2)
        fmt = "%" + str(cw) + "s"
        hdr = "  %-11s" % "param" + "".join(fmt % x for x in short)
        L.append(hdr)
        L.append("  " + "-" * (len(hdr) - 2))
        for n in order:
            if n in a["dead"] or n not in ps:
                continue
            L.append("  %-11s" % n + "".join(("%" + str(cw) + ".4g")
                                             % ps[n][s] for s in a["sweeps"]))

    if a["collinear"]:
        L.append("")
        L.append("  degenerate pairs among the parameters that ARE determined:")
        for x, y, r in a["collinear"]:
            tag = "DEGENERATE" if abs(r) >= COLLINEAR_WARN else "strongly coupled"
            L.append("     %-10s ~ %-10s  r = %+.4f   %s" % (x, y, r, tag))
    elif n_live >= 2:
        L.append("")
        L.append("  among the %d determined parameters no pair exceeds |r| = %.2f:"
                 % (n_live, COLLINEAR_NOTE))
        L.append("     that subset is separable.")

    if a.get("warnings"):
        L.append("")
        L.append("  HOW EACH PARAMETER WAS PROBED -- read these, they change")
        L.append("  what the numbers above mean:")
        for n in sorted(a["warnings"]):
            for w in a["warnings"][n]:
                ls = _wrap_note(w, 60)
                L.append("     %-11s %s" % (n, ls[0]))
                for extra in ls[1:]:
                    L.append("     %-11s %s" % ("", extra))
    return "\n".join(L)


# ===========================================================================
#  v1.1.9 -- THE BOX-ADEQUACY GATE
# ===========================================================================
#  WHY THIS EXISTS, AND WHAT IT WOULD HAVE CAUGHT.
#
#  Step 10 ran `scan_swing` over UA, EU and ETAMOB before fitting them, and
#  the scan printed, in its own `best` column:
#
#       etamob   best = 0.5      declared range [0.5, 4.0]     <- the bottom
#       eu       best = 6.0      declared range [0.5, 6.0]     <- the top
#       ua       best = 0.001    declared range [0.001, 30]    <- the bottom
#
#  Every one of those is the scan saying "the lowest residual I found is at
#  the edge of the box you gave me, so the real optimum is probably outside
#  it". The fit then ran anyway, and came back with two rails and a third
#  parameter 1.9% from a rail. The information needed to stop that was
#  already measured and already printed; nothing acted on it.
#
#  The same thing happened, more expensively, to ETA0. Its declared range in
#  the Step-9 and Step-10 identifiability specs was [0.001, 1.5]. ETA0 sets
#  the drain-induced barrier lowering through
#
#       dvth_dibl = -ETA0 * Theta_DIBL * (vdsx + ETA1*sqrt(vdsx+0.01))
#                                                      (body:1793)
#
#  and on this geometry Theta_DIBL = 3.6488e-03 (body:962, DSUB = 1.06), so
#  the WHOLE of that box can only produce 5.5 mV/V of DIBL. The device has
#  23.3 mV/V. The box could not reach the answer, the SWING computed over
#  that box therefore reported the parameter as nearly worthless, and the
#  parameter was left at its default for ten steps.
#
#  A box that cannot reach the answer is not a conservative choice. It is a
#  silent, confident wrong answer, and it is invisible to every check that
#  reports a parameter's behaviour WITHIN its declared range -- which is all
#  of them, SWING included.
#
#  `box_adequacy` is the check that is not invisible to it. It reads the
#  `best` that `scan_swing` already returns, compares it with the ends of the
#  declared range in the parameter's own coordinate, and says plainly whether
#  the box is shaping the answer. It is a pure function of data already in
#  hand: it costs no simulations at all.
# ===========================================================================

BOX_EDGE_FRAC = 0.02        # inside this fraction of the span = "at the edge"
BOX_NEAR_FRAC = 0.10        # inside this fraction = "leaning on the edge"


def _coord(x, mode):
    """A parameter's own coordinate: p for lin, ln(p) for log."""
    if str(mode).lower() == "log":
        return np.log(max(float(x), 1.0e-300))
    return float(x)


def box_adequacy(scan, rng, edge_frac=BOX_EDGE_FRAC, near_frac=BOX_NEAR_FRAC):
    """Is the declared range big enough for the answer the scan just found?

    `scan` is a dict returned by `scan_swing`; `rng` is the (lo, hi, mode)
    triple that scan was given.  Returns a dict:

      name      : the parameter
      best      : the scanned value with the lowest total error
      lo, hi    : the declared range
      frac      : where `best` sits in the range, 0 at lo and 1 at hi,
                  measured in the parameter's OWN coordinate
      verdict   : 'ok'      -- the best is in the interior, the box is fine
                  'edge'    -- the best is within edge_frac of an end
                  'near'    -- within near_frac but not edge_frac
      side      : 'low' | 'high' | None
      advice    : one sentence, or None when the verdict is 'ok'

    Nothing here decides anything on its own.  A `best` at the bottom of the
    range can be the honest answer -- a parameter whose model term really is
    switched off in this device will want its floor -- but that is a
    conclusion to be reached and written down, not one to be reached by
    accident because the box stopped the search.  The point of the check is
    that the question gets ASKED every time, in the output, before the fit.
    """
    name = scan.get("name")
    out = {"name": name, "verdict": "ok", "side": None, "advice": None}
    best = scan.get("best")
    if best is None or not np.isfinite(best):
        out["verdict"] = "unknown"
        out["advice"] = ("the scan produced no usable best value, so the box "
                         "cannot be judged")
        return out
    lo, hi, mode = float(rng[0]), float(rng[1]), str(rng[2]).lower()
    out["best"], out["lo"], out["hi"], out["mode"] = float(best), lo, hi, mode
    if mode == "log" and lo <= 0:
        lo = min(hi / 1.0e4, float(best) if best > 0 else hi / 1.0e4)
        out["lo_used"] = lo
    a, b, x = _coord(lo, mode), _coord(hi, mode), _coord(best, mode)
    span = b - a
    if span <= 0:
        out["verdict"] = "unknown"
        out["advice"] = "the declared range has zero width"
        return out
    frac = (x - a) / span
    out["frac"] = float(frac)
    if frac <= edge_frac:
        out["verdict"], out["side"] = "edge", "low"
    elif frac >= 1.0 - edge_frac:
        out["verdict"], out["side"] = "edge", "high"
    elif frac <= near_frac:
        out["verdict"], out["side"] = "near", "low"
    elif frac >= 1.0 - near_frac:
        out["verdict"], out["side"] = "near", "high"
    if out["verdict"] == "edge":
        end = lo if out["side"] == "low" else hi
        out["advice"] = (
            "the scan's best value sits ON the %s end (%g) of the declared "
            "range. Either widen the range past it and re-scan, or write "
            "down why that end is the physical answer -- do not fit inside "
            "this box and quote the number that comes out."
            % (out["side"], end))
    elif out["verdict"] == "near":
        end = lo if out["side"] == "low" else hi
        out["advice"] = (
            "the scan's best value is within %.0f%% of the %s end (%g). The "
            "box is probably shaping the answer; widening it is cheap."
            % (100.0 * near_frac, out["side"], end))
    return out


def box_audit(scans, ranges, edge_frac=BOX_EDGE_FRAC,
              near_frac=BOX_NEAR_FRAC, live_only=True, switches=()):
    """box_adequacy over a whole scan set.  Returns {name: verdict dict}.

    v1.1.16 adds two refusals, both paid for by Step 18:

    `live_only` skips a parameter whose scanned SWING is below the
    determinability cut. Step 18's gate widened DELTAVSATCV from [0.05, 5] to
    [0.05, 50] and then to nothing, VSATCV from 400,000 m/s to 4,000,000, and
    SUBBANDMOD past its own top -- on the strength of "best values" whose
    entire range is worth 2.8e-05, 4.1e-05 and 4.3e-04 of RMS residual. The
    scan's "best" for a dead parameter is numerical noise, and widening a box
    around noise is how a card ends up with a velocity of four million metres
    per second.

    `switches` names the parameters that are MODE SELECTORS, not knobs.
    Step 18 widened CGEOMOD, an integer that chooses between three different
    sets of parasitic-capacitance equations, to [-0.5, 1]. There is no such
    thing as CGEOMOD = -0.5. A switch is reported and never widened.
    """
    out = {}
    sw = set(str(x).lower() for x in (switches or ()))
    for name in sorted(scans):
        if name not in ranges:
            continue
        sv = scans[name] if isinstance(scans[name], dict) else {}
        if live_only:
            sg = sv.get("swing_scan")
            try:
                dead = (sg is None or not np.isfinite(sg)
                        or float(sg) < SWING_MIN)
            except Exception:
                dead = False
            if dead:
                out[name] = {
                    "name": name, "verdict": "not determinable",
                    "best": sv.get("best"), "swing": sg,
                    "lo": float(ranges[name][0]), "hi": float(ranges[name][1]),
                    "frac": None, "side": None,
                    "advice": "its whole range is worth %s of RMS residual,"
                              " below the cut of %g: the scan's best point is"
                              " noise and the box is not the problem"
                              % ("%.3g" % sg if sg is not None else "nothing",
                                 SWING_MIN)}
                continue
        if name.lower() in sw:
            out[name] = {
                "name": name, "verdict": "a switch, not a knob",
                "best": sv.get("best"),
                "lo": float(ranges[name][0]), "hi": float(ranges[name][1]),
                "frac": None, "side": None,
                "advice": "this selects a set of equations, not a value."
                          " Its ends are the modes the model has; widening"
                          " them would ask for a mode that does not exist"}
            continue
        try:
            out[name] = box_adequacy(scans[name], ranges[name],
                                     edge_frac=edge_frac,
                                     near_frac=near_frac)
        except Exception as exc:                       # pragma: no cover
            out[name] = {"name": name, "verdict": "unknown",
                         "advice": "box_adequacy raised %r" % (exc,)}
    return out


def null_directions(sv, Vt, names, n_max=4, cut=0.15, ratio_min=20.0):
    """The combinations of parameters this data does NOT determine.

    sv, Vt : from numpy.linalg.svd of the COLUMN-NORMALISED Jacobian, so
             one unit along any axis means "the amount of that parameter
             which moves the residual by the same amount as any other".
    names  : the live parameter names, in the Jacobian's column order.

    A direction with a small singular value is a combined move that barely
    changes the model: the parameters in it trade against each other and
    only their combination is measured. Reported when it is at least
    `ratio_min` times weaker than the best-determined direction.
    """
    out = []
    if sv is None or Vt is None or len(names) < 2:
        return out
    s0 = float(sv[0]) if len(sv) and sv[0] > 0 else 1.0
    for j in range(len(sv) - 1, -1, -1):
        s_ = float(sv[j])
        ratio = (s0 / s_) if s_ > 0 else float("inf")
        if ratio < ratio_min or len(out) >= int(n_max):
            break
        vec = np.asarray(Vt[j], float)
        load = sorted(((names[k], float(vec[k])) for k in range(len(names))),
                      key=lambda t: -abs(t[1]))
        keep = [(n, w) for n, w in load if abs(w) >= float(cut)][:6]
        if not keep:
            keep = load[:2]
        out.append({"sigma": s_, "ratio": ratio, "loadings": keep})
    return out


def format_null_directions(an, title="what this data does NOT determine"):
    """The printable block. Empty when every direction is measured."""
    nd = (an or {}).get("null_directions") or []
    L = ["  %s:" % title]
    if not nd:
        L.append("    every combination of the live parameters moves the")
        L.append("    model by a measurable amount. Nothing to report.")
        return "\n".join(L)
    L.append("    Each line is a direction in parameter space -- a way of")
    L.append("    moving several parameters TOGETHER. The ratio says how")
    L.append("    much weaker it is than the best-measured direction.")
    L.append("")
    for k, d in enumerate(nd):
        parts = []
        for n, w in d["loadings"]:
            parts.append("%+.2f %s" % (w, n))
        L.append("    %d)  %s" % (k + 1, "  ".join(parts)))
        L.append("        %.0fx weaker than the strongest direction"
                 " (sigma %.3g)" % (d["ratio"], d["sigma"]))
    L.append("")
    L.append("    A parameter that appears here with a large weight is NOT")
    L.append("    determined on its own by this data, however confident its")
    L.append("    fitted value looks. Only the combination is. That is the")
    L.append("    reason to put such a parameter where the MODEL says it")
    L.append("    should be and let its partners take the slack -- which is")
    L.append("    what the prior in l5_opt/lm_align.py does.")
    return "\n".join(L)


def _common_prefix(names):
    """The longest string every name starts with ('' if there is none)."""
    if not names:
        return ""
    out = names[0]
    for n in names[1:]:
        while out and not n.startswith(out):
            out = out[:-1]
        if not out:
            return ""
    return out


def _wrap_note(text, width=62):
    """Break a long note into lines a terminal can show. (v1.1.12 -- these
    notes were being printed 250 characters wide.)"""
    out, line = [], ""
    for word in str(text).split():
        if line and len(line) + 1 + len(word) > width:
            out.append(line)
            line = word
        else:
            line = (line + " " + word) if line else word
    if line:
        out.append(line)
    return out or [""]


def format_box_report(audit, title="box adequacy, BEFORE any fit runs"):
    """The printable block.  Silent-clean when every box is adequate."""
    L = ["  %s:" % title,
         "  %-11s %-13s %-13s %-13s %-9s %s"
         % ("param", "scan best", "range low", "range high", "position",
            "verdict"),
         "  " + "-" * 76]
    edge, near = [], []
    for name in sorted(audit):
        a = audit[name]
        v = a.get("verdict", "unknown")
        if v == "edge":
            edge.append(name)
        elif v == "near":
            near.append(name)
        L.append("  %-11s %-13.6g %-13.6g %-13.6g %-9s %s"
                 % (name, a.get("best") if a.get("best") is not None
                    else float("nan"),
                    a.get("lo", float("nan")), a.get("hi", float("nan")),
                    ("%.0f%%" % (100.0 * a["frac"]))
                    if a.get("frac") is not None else "-",
                    {"ok": "ok", "near": ".. leaning %s" % a.get("side"),
                     "edge": "<-- AT THE %s END"
                             % str(a.get("side", "?")).upper(),
                     "unknown": "?"}.get(v, v)))
    if edge:
        L.append("")
        L.append("  THE BOX IS AT FAULT, NOT THE PARAMETER: %s"
                 % ", ".join(edge))
        for n in edge:
            ls = _wrap_note(audit[n].get("advice", ""), 60)
            L.append("     %-11s %s" % (n, ls[0]))
            for extra in ls[1:]:
                L.append("     %-11s %s" % ("", extra))
        L.append("  A fit started now would return a value on the boundary,")
        L.append("  and a value on a boundary is a property of the spec, not")
        L.append("  of the device. Widen, or justify the end in writing.")
    if near:
        L.append("")
        L.append("  .. leaning on a box end (inside %.0f%%): %s"
                 % (100.0 * near_frac_of(audit, near), ", ".join(near)))
    if not edge and not near:
        L.append("")
        L.append("  every scanned best is in the interior of its own box.")
    return "\n".join(L)


def near_frac_of(audit, names):
    """The near_frac actually used, recovered from the report for printing."""
    del audit, names
    return BOX_NEAR_FRAC
