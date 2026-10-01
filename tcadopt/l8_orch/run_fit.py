"""l8_orch.run_fit -- staged BSIM-CMG parameter extraction.

WHY EXTRACTION IS STAGED, NOT ONE BIG SEARCH
--------------------------------------------
BSIM-CMG has hundreds of parameters. Handing all of them to the optimizer at
once is not "letting it work harder"; it is asking a physically meaningless
question, because most of those parameters are degenerate with each other.
A threshold shift can be produced by the gate work function, by body doping, or
by a short-channel coefficient. A drive-current error can be absorbed by
mobility or by series resistance. Fit them together and the optimizer will find
SOME combination that matches the curve -- and that combination will be wrong
in every way that matters: it will not extrapolate to a geometry or a
temperature it was not fitted at, and its parameters will not mean what their
names say.

The industry answer, and the one used here, is to extract in stages, each stage
using the bias region where its parameters dominate and everything already
extracted held FROZEN:

  Stage 1  electrostatics    PHIG, CIT, ... on the sub-threshold region at low
                             Vd, where mobility and series resistance barely
                             matter
  Stage 2  short-channel     DVT0, DVT1, ETA0, DSUB, ... on the Vd dependence
                             of threshold (DIBL), with Stage-1 values frozen
  Stage 3  mobility + Rds    U0, UA, UD, RDSWMIN, ... on the on-state, where
                             they dominate and the electrostatics are settled
  Stage 4  capacitance       CGSP, CGDP, CGBO, ... on the C-V curves, which the
                             DC fit never constrained
  Stage 5  global polish     a small trust region around everything at once,
                             to remove residual interaction, starting from a
                             point that is already physically meaningful

Each stage is a normal TCADOpt campaign. Same ParamSpace, same GP, same trust
region, same experiment DB. What changes per stage is which parameters are free,
which target sweeps are scored, and what the previous stage froze.

Freezing is what makes the result an EXTRACTION rather than a curve fit. It is
also what makes it defensible in a viva: for every parameter you can say which
measurement determined it and which ones were held fixed while it was found.

WHY A STAGE ALSO NEEDS A BIAS WINDOW (v1.1.4)
---------------------------------------------
Choosing WHICH SWEEPS a stage is scored on is only half of "use the bias region
where these parameters dominate". The other half is WHICH PART of a sweep, and
until v1.1.4 there was no way to say it.

It is not a detail. Measured on this project's real data, with the whole
Ids-Vgs curve at Vds = 50 mV in the residual:

    PHIG   sub-threshold SWING 4.965      U0   sub-threshold SWING 0.795
    PHIG  ~ U0     r = -0.9746   strongly coupled

Physically those two are nothing alike -- one is a flat-band voltage, the other
a mobility. They correlate because the residual spans the whole curve: over a
window that includes the on-state, lowering the threshold and raising the
mobility both raise the current, and a single RMS number cannot tell a shift
from a scale. Restrict the same fit to the sub-threshold decades and the
degeneracy weakens, because down there a threshold shift moves the curve
SIDEWAYS while mobility moves it UP -- different shapes, separable.

So a stage may now carry

    v_window: [lo, hi]                      # applies to every sweep in it
    sweep_windows: {name: [lo, hi]}         # or per sweep, overriding the above

in the bias variable that sweep is swept in (Vgs for IdVg and C-V, Vds for
IdVd). The reference curve is clipped to the window BEFORE the deck arguments
are derived from it, so the simulator sweeps only the window too -- the stage
gets cheaper as well as sharper. A window that leaves fewer than 5 points is
refused rather than silently fitted, and the number of points kept is printed
for every sweep, because a stage quietly scoring 3 points is exactly the sort
of thing that produces a confident wrong answer.

WHY A STAGE MAY ALSO BE SEEDED (v1.1.4)
---------------------------------------
`run_stage` used to begin every stage from a fresh Latin-hypercube sample over
the whole box, ignoring everything already known. For a staged extraction that
is throwing away the most useful information available: stage N has just
finished, and its answer is a point in stage N+1's box that is known to be
good.

It is not a theoretical concern. Measured against a stand-in simulator while
this step was being written:

    free = {PHIG}              -> residual 0.09682
    free = {PHIG, CDSC}        -> residual 0.10589      WORSE
    free = {PHIG, CDSC, DVT1}  -> residual 0.12516      WORSE STILL

Those three sets are NESTED -- every card the first can reach, the second can
reach too, by leaving CDSC at its default. A nested model class cannot fit
worse. The bigger searches simply failed to find what the smaller one had
already found: the two-dimensional run stalled at 0.10589 in round 2 and then
spent five rounds and a trust-region restart not improving on it.

A comparison between those numbers is worthless. Worse, it invites exactly the
wrong conclusion: it looks like evidence that CDSC does not help, when it is
only evidence that the search stopped early.

    `seed_points=[{...}, ...]`

evaluates those cards as part of the initial design, before the GP fits
anything. Pass stage N's champion and stage N+1 starts from a best-so-far it
cannot do worse than, so a nested comparison is monotone BY CONSTRUCTION and
the difference between two stages means what it appears to mean. Points are
clipped into the box by `ParamSpace.encode`, and any parameter the stage does
not have free is simply ignored, so a whole previous card can be handed over
without filtering it first.

WHAT CHANGED IN v1.1.6
----------------------
A STAGE CAN NOW TIE ONE PARAMETER EXACTLY TO ANOTHER.

    stages:
      - name: s4_capacitance
        parameters:
          cfs: [0.0, 5.0e-10, lin, F/m]
        tied:
          cfd: cfs

`cfd` is not searched, has no dimension, and costs nothing -- it is set to
`cfs` every time a point is decoded, so the card that reaches HSPICE always
carries the pair the model declares:

    bsimcmg_parameters.include:1813
        `MPRnb(cfd, cfs, "F/m", "Outer fringe capacitance at drain side")

That line is the model saying CFD's DEFAULT IS CFS. `l1_spec.paramspace`
carries the full argument and the other four pairs BSIM-CMG declares the same
way; the two changes here are that `run_stage` passes the spec's `tied` block
to `ParamSpace`, and that a tied parameter is FROZEN with the stage's own free
parameters at the end. Without the second half the tie would hold inside the
stage and then break between stages, when the next stage read the follower
back out of the old card -- the same silent asymmetry, one stage later.

WHAT CHANGED IN v1.1.5
----------------------
Two things, both found by reading a real Stage-1 result rather than by
inspection of the code.

(1) A PARAMETER FITTED ONTO ITS OWN BOUNDARY WAS REPORTED AS AN EXTRACTION.

    Stage 1 of the nanosheet extraction returned

        phig = 4.39001        cdsc = 0.05

    and 0.05 was, exactly, the top of the range the spec gave CDSC. Nothing
    anywhere said so. A value sitting on a boundary is not a measurement of
    the parameter; it is the optimizer reporting that it wanted more than it
    was allowed, and the true optimum is somewhere outside the box. Quoting it
    as an extracted value is simply wrong, and in this case the bound was not
    even physical -- BSIM-CMG declares CDSC with `MPRnb`, which is Verilog-A
    for "no bounds at all", so the ceiling was an arbitrary choice made while
    writing the spec.

    `_check_rails` now measures, for every fitted parameter, how far it sits
    from each end of its own box IN THE COORDINATE IT WAS SEARCHED IN (linear
    or log, whichever the spec declared), and prints a loud block when anything
    lands within RAIL_FRAC of an end. The stage still completes -- the number
    may be perfectly usable, and refusing to finish would lose the rest of the
    run -- but nobody can now read the value without also reading that it is on
    a wall.

(2) A CONVERGED STAGE KEPT SPENDING ITS BUDGET.

    v1.1.4 added `min_rounds` because a stage was stopping after 20 of 80
    evaluations on a flat patch. It worked, and then overshot: on the real
    Stage 1 the two-parameter fit reached its final value in round 4 and then
    ran 27 more rounds -- 108 further HSPICE evaluations -- without improving
    by a single digit. `min_rounds` is a fraction of the BUDGET, and the budget
    has nothing to do with whether the search is still finding anything.

    `min_rounds_after_gain` is the same idea attached to the right thing: the
    stage may not stop until this many rounds have passed SINCE THE LAST
    IMPROVEMENT. Measured against the three real Stage-1 fits, it would have
    stopped them at rounds 15, 16 and 12 instead of 16, 32 and 47 -- the same
    answers, 204 fewer evaluations. Default 0, so the old behaviour is
    unchanged unless a spec asks for the new one.

WHAT SEEDING DOES *NOT* DO, measured rather than assumed. On the same isolated
two-parameter surface, budget 80, median of three random seeds, with the
brute-force optimum at 0.029559:

    no seed                      0.05575
    seeded with the incumbent    0.05257
    seeded with a 5-point cloud  0.05633

All three are the same number to within the scatter between seeds. Seeding
does not make the search better; it makes the COMPARISON valid. Those are
different things and it is worth keeping them apart, because the tempting
conclusion -- "seed everything, it helps" -- is not what the numbers say.

USE
    python -m tcadopt.l8_orch.run_fit problems/nsfet_gaa_fit.yaml
    python -m tcadopt.l8_orch.run_fit problems/nsfet_gaa_fit.yaml --stage 2
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import yaml                                                    # noqa: E402

from tcadopt.l1_spec.paramspace import ParamSpace              # noqa: E402
from tcadopt.l1_spec.curve_scorer import build_curve_scorer    # noqa: E402
from tcadopt.l3_exec.targets import load_targets, summarize    # noqa: E402
from tcadopt.l3_exec.spice_exec import HSpiceEvaluator         # noqa: E402
from tcadopt.l5_opt.optimizer import Optimizer                 # noqa: E402
from tcadopt.l7_memory import ExperimentDB, code_version       # noqa: E402


def _default_db():
    return os.path.join(ROOT, "results", "extraction.db")


def _frozen_path(spec_path):
    return os.path.join(ROOT, "results",
                        "frozen_%s.json" % os.path.splitext(
                            os.path.basename(spec_path))[0])


def load_frozen(spec_path):
    p = _frozen_path(spec_path)
    if os.path.exists(p):
        with open(p) as fh:
            return json.load(fh)
    return {}


def save_frozen(spec_path, frozen):
    p = _frozen_path(spec_path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        json.dump(frozen, fh, indent=1, sort_keys=True)
    return p


MIN_WINDOW_POINTS = 5


def _apply_window(t, win):
    """Clip one target to a bias window, in that sweep's own swept variable.

    Returns (clipped_target, note). The clip happens here, before
    `_sweep_deck_args` reads `t["v"]`, so the deck is built for the window too
    rather than simulating points that will be thrown away.
    """
    import numpy as np
    if not win:
        return t, None
    lo, hi = float(win[0]), float(win[1])
    v = np.asarray(t["v"], float)
    m = (v >= lo - 1e-12) & (v <= hi + 1e-12)
    n = int(m.sum())
    if n < MIN_WINDOW_POINTS:
        raise ValueError(
            "stage window [%g, %g] leaves only %d point(s) of %s -- refusing. "
            "A stage fitted on a handful of points returns a confident number "
            "that the data does not support." % (lo, hi, n, t["name"]))
    out = dict(t)
    out["v"] = v[m]
    out["i"] = np.asarray(t["i"], float)[m]
    return out, "%s: %d of %d points kept, %g .. %g" % (
        t["name"], n, len(v), float(out["v"].min()), float(out["v"].max()))


def _stage_targets(all_targets, stage):
    """Select the sweeps this stage is scored on, their weights, and the bias
    window each is clipped to. Returns (targets, notes)."""
    names = stage.get("sweeps")
    ts = [dict(t) for t in all_targets
          if (names is None or t["name"] in names)]
    wmap = stage.get("sweep_weights") or {}
    win_all = stage.get("v_window")
    win_map = stage.get("sweep_windows") or {}
    out, notes = [], []
    for t in ts:
        t["weight"] = float(wmap.get(t["name"], t.get("weight", 1.0)))
        t2, note = _apply_window(t, win_map.get(t["name"], win_all))
        if note:
            notes.append(note)
        out.append(t2)
    return out, notes


def run_stage(spec_path, stage_index=None, db_path=None, verbose=True,
              evaluator_factory=None, seed=0, seed_points=None):
    """Run one stage (or every remaining stage when stage_index is None).

    `seed_points` is a list of parameter dicts to evaluate as part of the
    initial design -- normally the previous stage's champion, so a nested stage
    cannot score worse than the stage it extends. Keys the stage does not have
    free are ignored; values outside the box are clipped into it.

    `evaluator_factory(targets, scorer, spec, stage) -> evaluator` lets a caller
    substitute the simulator. This mirrors how `run_campaign` accepts an
    injected evaluator, and it is what makes the whole staged loop testable
    without a SPICE licence: the ParamSpace, the GP, the trust region, the
    scorer, the database and the freezing logic are all exercised for real
    against a stand-in simulator.
    """
    with open(spec_path) as fh:
        spec = yaml.safe_load(fh)
    fit = spec["fit"]
    stages = spec["stages"]
    all_targets, dropped = load_targets(fit, root=ROOT)
    if verbose:
        print("=" * 70)
        print("EXTRACTION  %s" % spec["problem_id"])
        print(summarize(all_targets, dropped))

    db = ExperimentDB(db_path or _default_db())
    cv = code_version(ROOT)
    frozen = load_frozen(spec_path)
    todo = ([stages[stage_index - 1]] if stage_index
            else stages)

    for st in todo:
        label = st["name"]
        params = st["parameters"]
        space = ParamSpace(params, coupled=st.get("coupled", []),
                           tied=st.get("tied"))
        targets, win_notes = _stage_targets(all_targets, st)
        scorer = build_curve_scorer(targets, st.get("objective", fit))

        if verbose:
            print("-" * 70)
            print("STAGE %s  free=%d  frozen=%d  sweeps=%d" % (
                label, space.dim, len(frozen), len(targets)))
            print("  free      : %s" % ", ".join(space.names))
            if space.tied_names:
                # v1.1.6: a tie is invisible in the free list and in the
                # fitted-value report, because the parameter has no dimension
                # of its own. It has to be printed or nobody reading the log
                # can tell that two numbers in the card moved together.
                print("  tied      : %s  (the model's own default relation)"
                      % "; ".join(space.describe_ties()))
            if frozen:
                print("  frozen    : %s" % ", ".join(
                    "%s=%.4g" % (k, v) for k, v in sorted(frozen.items())))
            print("  scored on : %s" % ", ".join(t["name"] for t in targets))
            # v1.1.10: say which units the I-V comparison is in, every stage.
            if fit.get("iv_width_um"):
                print("  I-V units : model current / %g um = A/um, the same "
                      "unit as the targets" % float(fit["iv_width_um"]))
            elif any(t.get("kind", "iv") == "iv" for t in targets):
                print("  !! I-V UNITS: the targets are A/um and the model is "
                      "amperes per DEVICE -- set fit.iv_width_um")
            if win_notes:
                print("  bias window:")
                for n in win_notes:
                    print("     %s" % n)
            else:
                print("  bias window: none -- every point of every sweep")

        ev = (evaluator_factory(targets, scorer, spec, st)
              if evaluator_factory else HSpiceEvaluator(
            targets,
            models=fit.get("models", {}),
            structures=fit.get("structures"),
            n_parallel=int(spec.get("budget", {}).get("parallel", 8)),
            temp=float(spec.get("operating", {}).get("T_K", 300.0)) - 273.15
            if spec.get("operating", {}).get("T_K", 300.0) > 200 else 27.0,
            nf=int(fit.get("nf", 1)),
            scorer=scorer,
            iv_width_um=fit.get("iv_width_um")))

        budget = st.get("budget", spec.get("budget", {}))
        parallel = int(budget.get("parallel", 8))
        max_evals = int(budget.get("max_evals", 120))
        init_n = int(budget.get("init_n", max(parallel, 2 * space.dim + 4)))
        round_n = int(budget.get("round_n", parallel))
        max_rounds = max(1, (max_evals - init_n) // max(round_n, 1))
        # v1.1.4: trust-region schedule and stopping rule, per stage.
        # Defaults reproduce the pre-1.1.4 behaviour exactly.
        tr_kw = dict(budget.get("trust_region") or {})
        opt = Optimizer(space, tr_kw=(tr_kw or None))
        floor_eps = float(budget.get("floor_eps", 1.0e-4))
        floor_patience = int(budget.get("floor_patience", 2))
        min_rounds = int(budget.get("min_rounds", 0))
        # v1.1.5: keep going for this many rounds AFTER the last improvement,
        # rather than for a fixed fraction of the budget. See the docstring --
        # min_rounds cost 108 wasted HSPICE evaluations on a stage that had
        # finished improving in round 4.
        min_after_gain = int(budget.get("min_rounds_after_gain", 0))
        last_gain_round = -1
        if verbose and (tr_kw or min_rounds):
            print("  search rules: trust_region=%s  floor_eps=%.3g  "
                  "patience=%d  min_rounds=%d"
                  % (tr_kw or "default", floor_eps, floor_patience,
                     min_rounds))

        def evaluate(U, tag):
            plists = []
            for u in U:
                p = dict(frozen)          # everything already extracted
                p.update(space.decode(u))  # this stage's free parameters
                plists.append(p)
            results = ev.evaluate_batch(plists, tag=tag)
            for u, p, r in zip(U, plists, results):
                s = (scorer(r.get("curves")) if r.get("curves") else None)
                if s is not None and not (s == s and abs(s) < 1e30):
                    s = None
                if s is not None and s <= -1e8:
                    s = None               # non-simulating: keep out of the GP
                db.record(spec["problem_id"], params=p, encoded=list(u),
                          metrics=r.get("metrics"), status=r.get("status"),
                          score=s, campaign=label, trial_id=r.get("run_id"),
                          failure_class=r.get("failure_class"), seed=seed,
                          code_ver=cv, wall_time=r.get("wall_s"))
            return results

        U = opt.propose([], [], init_n, mode="lhs_init", seed=seed)
        # SEEDING. Prepended, not appended, so that if the budget is tight the
        # known-good points are the ones that certainly get evaluated.
        if seed_points:
            seeded = []
            for sp in seed_points:
                if not isinstance(sp, dict):
                    continue
                if not all(n in sp for n in space.names):
                    continue          # cannot place it in this box; skip it
                try:
                    seeded.append(space.encode(sp))
                except Exception:
                    continue
            if seeded:
                U = seeded + list(U)
                if verbose:
                    print("  seeded with %d known point(s): %s"
                          % (len(seeded), "; ".join(
                              ", ".join("%s=%.6g" % (n, sp[n])
                                        for n in space.names)
                              for sp in seed_points
                              if all(n in sp for n in space.names))))
        evaluate(U, "%s_init" % label)
        best = _best(db, spec["problem_id"], label)
        hist = [best["score"]] if best else []
        if verbose and best:
            print("  init best error = %.5f" % (-best["score"]))

        for rd in range(max_rounds):
            X, y = db.history_encoded(spec["problem_id"], campaign=label)
            if len(y) < 3:
                break
            U = opt.propose(X, y, round_n, mode="bo_round", seed=seed + rd + 1)
            evaluate(U, "%s_r%d" % (label, rd))
            best = _best(db, spec["problem_id"], label)
            if not best:
                continue
            hist.append(best["score"])
            if len(hist) >= 2 and hist[-1] > hist[-2] + floor_eps:
                last_gain_round = rd
            if verbose:
                print("  round %-2d best error = %.5f%s"
                      % (rd, -best["score"],
                         "   <- improved" if last_gain_round == rd else ""))
            if Optimizer.floor_detected(hist, patience=floor_patience,
                                        eps=floor_eps):
                if opt.exhausted(
                        max_restarts=int(budget.get("max_restarts", 2))):
                    # v1.1.4: a stage may be required to spend a minimum number
                    # of rounds before it is allowed to declare itself done.
                    # Without it a stage can stop on a flat patch having used a
                    # fraction of its budget -- measured: 20 evaluations of an
                    # 80 budget, with a factor of three still available. Where
                    # there is a known answer to hit, spending the budget is
                    # the point.
                    quiet = rd - last_gain_round
                    enough_budget = (rd + 1) >= min_rounds
                    enough_quiet = (min_after_gain <= 0
                                    or quiet >= min_after_gain)
                    if enough_budget and enough_quiet:
                        if verbose:
                            print("  floor + trust region exhausted -> stage "
                                  "done (round %d of %d, %d evals, %d round(s)"
                                  " since the last gain)"
                                  % (rd + 1, max_rounds,
                                     init_n + (rd + 1) * round_n, quiet))
                        break
                    if verbose:
                        why = []
                        if not enough_budget:
                            why.append("min_rounds=%d" % min_rounds)
                        if not enough_quiet:
                            why.append("only %d of %d quiet rounds since the "
                                       "last gain" % (quiet, min_after_gain))
                        print("  floor reached at round %d but %s "
                              "-- re-expanding and continuing"
                              % (rd + 1, " and ".join(why)))
                opt.force_restart()

        champ = _best(db, spec["problem_id"], label)
        if champ is None:
            print("  STAGE %s produced no usable fit -- stopping." % label)
            print("  Nothing is frozen from a stage that did not converge.")
            return frozen, db
        # freeze ONLY this stage's own free parameters
        for k in space.names:
            frozen[k] = champ["params"][k]
        for k, v in space.fixed.items():
            frozen.setdefault(k, v)
        # v1.1.6: a tied parameter is part of this stage's answer even though
        # it was never searched. If it is not frozen here, the next stage picks
        # it up from the card's old value and the tie is quietly broken between
        # stages -- which is exactly the failure the tie exists to prevent.
        for k in space.tied_names:
            if k in champ["params"]:
                frozen[k] = champ["params"][k]
        p = save_frozen(spec_path, frozen)
        if verbose:
            print("  STAGE %s COMPLETE  error = %.5f" % (label, -champ["score"]))
            _report(champ, space.names)
            _check_rails(champ, space)
            print("  frozen -> %s" % p)

    return frozen, db


def _best(db, problem_id, label):
    rows = [r for r in db.query(problem_id=problem_id, campaign=label)
            if r.get("score") is not None]
    return max(rows, key=lambda r: r["score"]) if rows else None


RAIL_FRAC = 0.01          # within 1% of an end of the box: a RAIL, loud
NEAR_FRAC = 0.05          # within 5%: PRESSED AGAINST the wall, worth saying


def _check_rails(champ, space, verbose=True):
    """Say so, loudly, when a fitted value has landed on the edge of its box.

    The distance is measured in the coordinate the parameter was SEARCHED in:
    a log-scaled parameter is 1% from its bound when log10(p) is 1% of the
    log10 span from the end, which is the only definition that matches what the
    optimizer actually explored.

    Returns the list of offending names so a caller can act on it.
    """
    import math
    hits, near = [], []
    for (name, lo, hi, islog) in getattr(space, "free", []):
        v = champ["params"].get(name)
        if v is None:
            continue
        try:
            if islog:
                if v <= 0 or lo <= 0 or hi <= 0:
                    continue
                t = ((math.log10(v) - math.log10(lo))
                     / (math.log10(hi) - math.log10(lo)))
            else:
                if hi <= lo:
                    continue
                t = (float(v) - lo) / (hi - lo)
        except Exception:
            continue
        if t <= RAIL_FRAC:
            hits.append((name, v, lo, hi, "LOW"))
        elif t >= 1.0 - RAIL_FRAC:
            hits.append((name, v, lo, hi, "HIGH"))
        elif t <= NEAR_FRAC:
            near.append((name, v, lo, hi, "LOW", 100.0 * t))
        elif t >= 1.0 - NEAR_FRAC:
            near.append((name, v, lo, hi, "HIGH", 100.0 * (1.0 - t)))
    if hits and verbose:
        print("")
        print("  " + "!" * 68)
        print("  !!  %d FITTED PARAMETER(S) LANDED ON THE EDGE OF THE BOX."
              % len(hits))
        print("  !!  A value on a boundary is NOT an extracted value. It is the")
        print("  !!  search saying it wanted to go further and was not allowed,")
        print("  !!  so the real optimum is OUTSIDE the range given here and")
        print("  !!  this number is a property of the spec, not of the device.")
        for (n, v, lo, hi, side) in hits:
            print("  !!     %-12s = %-14.6g  at the %s end of [%.6g, %.6g]"
                  % (n, v, side, lo, hi))
        print("  !!  Widen the range and re-run before quoting any of these.")
        print("  !!  Check the parameter's real bounds first: the model may")
        print("  !!  declare none at all (Verilog-A `MPRnb`), in which case the")
        print("  !!  ceiling was invented when the spec was written.")
        print("  " + "!" * 68)
    if near and verbose:
        # v1.1.8: the second tier. Step 9's mobility fit put FOUR of its five
        # parameters inside 5% of a box end and only ONE of them was inside
        # 1%, so only one was reported. A parameter 2.6% of the way in is not
        # "comfortably inside"; it is leaning on the wall, and one warning
        # beside four leaning parameters gives the wrong impression of how
        # much room the fit had.
        print("")
        print("  ..  %d more fitted parameter(s) are PRESSED AGAINST a box end"
              % len(near))
        print("  ..  (inside %.0f%% of it, but not inside %.0f%%). Not rails,"
              % (100 * NEAR_FRAC, 100 * RAIL_FRAC))
        print("  ..  but the box is shaping the answer and should be widened")
        print("  ..  before the value is quoted:")
        for (n, v, lo, hi, side, pct) in near:
            print("  ..     %-12s = %-14.6g  %.1f%% from the %s end of "
                  "[%.6g, %.6g]" % (n, v, pct, side, lo, hi))
    return [h[0] for h in hits]


def _report(champ, names):
    print("  extracted:")
    for k in names:
        print("     %-12s = %.6g" % (k, champ["params"][k]))
    m = champ.get("metrics") or {}
    if m.get("fit_worst_sub_decades") is not None:
        print("  worst sub-threshold error : %.4f decades (%.1f%% in current)"
              % (m["fit_worst_sub_decades"],
                 100.0 * (10.0 ** m["fit_worst_sub_decades"] - 1.0)))
    if m.get("fit_worst_on_pct") is not None:
        print("  worst on-state error      : %.2f %%" % m["fit_worst_on_pct"])


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m tcadopt.l8_orch.run_fit <fit_spec.yaml> "
              "[--stage N]")
        sys.exit(1)
    idx = None
    if "--stage" in sys.argv:
        idx = int(sys.argv[sys.argv.index("--stage") + 1])
    run_stage(sys.argv[1], stage_index=idx)
