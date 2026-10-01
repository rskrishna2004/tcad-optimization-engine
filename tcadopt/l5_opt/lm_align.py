"""l5_opt.lm_align -- a Levenberg-Marquardt aligner that runs BEFORE the
Bayesian search.  (TCADOpt v1.1.13)

WHY IT EXISTS
-------------
The trust-region Bayesian optimizer this engine is built on is very good at
two things: polishing a card that is already close, and not being fooled by
simulator noise. It is poor at one thing: a LARGE, COORDINATED move in many
dimensions at once, from far away. Its initial design scatters a few dozen
points across the box; in ten or more dimensions none of them lands in a
narrow valley, the best of them is the seed, and the trust region then
polishes the seed. Step 12 of the BSIM-CMG extraction showed exactly that:
of its three fits, two came back EXACTLY at their seeds and the third moved
every parameter for a 1% gain.

A residual VECTOR -- one entry per bias point -- carries far more than the
single number the Bayesian search sees. Its Jacobian says how every point
moves for every parameter, and a Gauss-Newton step uses all of that at once.
Levenberg-Marquardt damps the step so it cannot run away where the model is
nonlinear. This module is that, and nothing more:

  * every parameter in its OWN coordinate -- p for a linear range, ln p for
    a log range -- the convention l1_spec.paramspace and l6_verify use;
  * box-constrained: every trial point is clipped into its declared range;
  * a central-difference Jacobian with EVERY perturbed card in ONE
    `evaluate_batch` call, so one Jacobian costs one batch of 2N runs;
  * a whole LADDER of damping values and step lengths, again in ONE batch;
  * a step is kept only if it LOWERS the sum of squares; lambda adapts.

It does not replace the Bayesian search. It hands it a seed that is already
in the right valley, and the Bayesian search does what it is good at.

WHAT v1.1.11 FIXES, AND WHY
---------------------------
Step 13 ran the v1.1.10 aligner on eleven parameters from a card that was
8.33x too strong. It stopped at ITERATION ONE with a 0.05% gain and called
itself converged. Reading the step it took, parameter by parameter:

    etamob   0.8918  ->  0.1     (its lower bound: the step wanted -28000)
    eu       3.597   ->  4.616
    ua       0.00122 ->  0.00100
    u0       0.023497 -> 0.023492   (a move of 1.4e-4 of its own trust cap)

Three of those -- UA, EU, ETAMOB -- are the mobility-degradation group, and
the identifiability pass at that card measured their columns at EXACTLY
0.000e+00: the model term they belong to is switched off in this device's
configuration, so the residual does not move when they move. Their Jacobian
columns were not exactly zero during the fit, only tiny, and that is worse
than zero. The Marquardt-scaled normal equations damp column k by
lambda*A_kk, so a column with A_kk ~ eps^2 and gradient g_k ~ eps gets

    delta_k  ~  -g_k / (A_kk * (1 + lambda))  ~  s / (eps * (1 + lambda))

which is ENORMOUS -- 28000 in ETAMOB's own units. v1.1.10 then scaled the
WHOLE step vector down until its largest component fitted inside its trust
cap, so the one meaningless component divided every meaningful one by
about 1e4. The step that was left changed nothing, the gain fell under the
0.3% tolerance, and the aligner stopped one iteration in.

Four changes, each of which alone would have prevented it:

  (1) COLUMN SCREENING. Columns are scaled by their own trust cap, so
      `|column|` means "how much the residual moves for one cap of this
      parameter" and is comparable across parameters. A column below
      `col_drop` of the largest is dropped from THAT iteration's solve and
      reported. A parameter the data cannot see does not get to veto a step.
  (2) A DAMPING FLOOR. The Marquardt diagonal is floored at `damp_floor`
      times its own largest entry, so a nearly-flat column can no longer be
      damped by nearly nothing.
  (3) PER-COMPONENT TRUST CLIPPING. Each component is clipped to its own
      cap. One runaway component can no longer shrink the others.
  (4) A LADDER, NOT A GUESS. Every iteration solves the damped system at
      several lambdas and evaluates them, plus two step lengths at the best
      of them, in ONE batch -- so the iteration cannot be wasted on a
      damping value that happens to be wrong, and `rho` (the actual gain
      over the gain the linear model predicted) is printed for every
      accepted step.

  and, so a stall is diagnosed rather than declared a convergence:
  a minimum number of iterations, and `stall_patience` consecutive small
  gains before "converged" is printed.

WHAT v1.1.13 ADDS
-----------------
`prior`. Step 15's identifiability measured an effective rank of 21 over 31
free parameters: ten independent combinations of parameters do not move the
model at all. Along those directions the fit is free, and "free" in practice
means "stops wherever the box ends" -- Step 15's card carries VSAT = 30091
m/s, sitting exactly on the floor of its range, 2.8x below the model's own
default and below the speed this device's own electrons are measured to
travel. Nothing is wrong with the fit; the data simply has no opinion, and a
number with no opinion behind it should be the one the MODEL declares, not
the one my box happened to stop at.

So: a weak pull towards a reference card, with a weight set from the data's
own curvature, so it is negligible wherever the data has an opinion and
decisive wherever it has none. It is the standard regularised (MAP)
extraction, it is what makes a card publishable rather than merely fitted,
and the no-regression gate proves per stage that it cost nothing.

WHAT v1.1.12 ADDS
-----------------
`extend=True`. Step 14 ran this aligner twice with a fixed iteration
budget and both runs ended on the words "iteration limit" with the last
step still taking 5% and 11% off the sum of squares. The number 16 was not
a convergence criterion, it was a guess about how long the run would take.
With `extend=True` the budget grows while the run is still gaining and
stops when it is not, up to a hard ceiling -- so the stopping rule is a
measurement instead of a guess. Nothing else changed: with the default
`extend=False` this function is v1.1.11 exactly.

`lm_align(..., legacy=True)` runs the v1.1.10 algorithm unchanged. It is
kept so the fault above can be REPRODUCED next to the fix on the same
problem rather than described -- which is what step14's PART 0 does.

$Id: lm_align.py, 2026/09/26 v1.1.14 $
"""
import numpy as np

from ..l1_spec.curve_scorer import _interp_model


# ---------------------------------------------------------------------------
#  the residual
# ---------------------------------------------------------------------------
def ratio_residual(targets, curves, i_split, floor_iv=1.0e-14,
                   floor_cv=1.0e-21, per_sweep=True):
    """Model against reference as a LOG RATIO at every usable point.

    Sub-threshold I-V (|I_ref| < i_split): log10(I_mod / I_ref), in decades --
    the scorer's own unit there. On-state I-V and all C-V: ln(mod / ref),
    which equals the scorer's relative error to first order and, unlike a
    relative error, stays linear when the model is several TIMES off -- a
    relative error is bounded at -1 below and unbounded above, which bends a
    Gauss-Newton step.

    per_sweep=True divides each sweep's entries by sqrt(its point count), so
    every sweep weighs the same whatever its length, as the scorer averages
    sweeps. Returns None if any sweep is missing or any model point at a
    usable reference point is not a positive finite number -- a vector with
    points silently dropped cannot be compared with one that has them.
    """
    out = []
    for t in targets:
        mc = curves.get(t["name"]) if curves else None
        if mc is None:
            return None
        iq = _interp_model(t["v"], mc[0], mc[1])
        if iq is None:
            return None
        a_ref = np.abs(np.asarray(t["i"], float))
        a_mod = np.abs(np.asarray(iq, float))
        kind = t.get("kind", "iv")
        floor = floor_cv if kind == "cv" else floor_iv
        base = np.isfinite(a_ref) & (a_ref > floor)
        good = base & np.isfinite(a_mod) & (a_mod > 0)
        if int(good.sum()) != int(base.sum()) or int(good.sum()) < 1:
            return None
        ar, am = a_ref[good], a_mod[good]
        if kind == "cv":
            r = np.log(am / ar)
        else:
            sub = ar < float(i_split)
            r = np.where(sub, np.log10(am / ar), np.log(am / ar))
        w = float(t.get("weight", 1.0)) ** 0.5
        if per_sweep:
            w = w / np.sqrt(float(len(r)))
        out.append(w * r)
    return np.concatenate(out) if out else None


# ---------------------------------------------------------------------------
#  coordinates
# ---------------------------------------------------------------------------
def _mode(rng):
    lo, hi, mode = float(rng[0]), float(rng[1]), str(rng[2]).lower()
    if mode == "log" and lo <= 0:
        mode = "lin"                 # a log axis cannot hold a zero bound
    return lo, hi, mode


def _to_u(x, mode):
    return float(np.log(max(float(x), 1e-300))) if mode == "log" \
        else float(x)


def _to_p(u, mode):
    return float(np.exp(u)) if mode == "log" else float(u)


def _fmt_names(ns, n_max=6):
    ns = list(ns)
    if not ns:
        return "-"
    if len(ns) <= n_max:
        return ", ".join(ns)
    return ", ".join(ns[:n_max]) + " (+%d more)" % (len(ns) - n_max)


# ---------------------------------------------------------------------------
#  the aligner (v1.1.11)
# ---------------------------------------------------------------------------
def lm_align(evaluate, residual, params, names, ranges, n_iter=12,
             rel_step=0.02, lam0=1.0e-2, alphas=(0.5, 1.0, 1.5),
             max_frac=0.25, tol=0.01, min_iter=3, max_retries=3,
             col_drop=3.0e-4, damp_floor=1.0e-6, stall_patience=2,
             lam_ladder=(0.1, 1.0, 10.0, 100.0), tag="lm", log=None,
             post=None, legacy=False, extend=False, max_iter=None,
             extend_gain=None, prior=None, prior_strength=1.0e-4):
    """Box-constrained Levenberg-Marquardt on a residual vector.

    evaluate : callable(list_of_param_dicts, tag) -> list of result dicts
               (an evaluator's `evaluate_batch`)
    residual : callable(result_dict) -> 1-D array, or None if unusable
    params   : the full starting card
    names    : the parameters to move; each needs a range
    ranges   : {name: (lo, hi, 'lin'|'log')}
    max_frac : no single step may move a parameter by more than this fraction
               of its range width (own coordinate) -- the trust cap. Each
               component is clipped to its own cap (v1.1.11); v1.1.10 scaled
               the whole vector by the worst component.
    tol      : an accepted step that improves the sum of squares by less than
               this fraction is a "small" step
    min_iter : never stop on small gains before this many accepted steps
    stall_patience : how many consecutive small gains end the run
    col_drop : a Jacobian column shorter than this fraction of the longest
               one (both measured per trust cap) is dropped from the solve
               for that iteration and reported. 3e-4 is below the smallest
               column any parameter in this project's identifiability tables
               has ever had while still being measurable (PCLM, at 1.5e-3 of
               PHIG's), and far above the 1e-7 that a switched-off model term
               leaves behind.
    damp_floor : the Marquardt diagonal is floored at this fraction of its
               own largest entry
    lam_ladder : the damping values tried, as multiples of the running
               lambda; all of them are evaluated in one batch
    post     : optional callable(card) -> card applied to EVERY card before it
               is evaluated -- this is where a model's own default relations
               (CFD = CFS, VSAT1 = VSAT when tied) are enforced, so the aligner
               can never evaluate a card the model would not describe
    legacy   : run the v1.1.10 algorithm instead (for regression tests)
    extend   : (v1.1.12) do not stop at `n_iter` while the run is still
               gaining. When the budget runs out and the LAST accepted step
               gained at least `extend_gain` (default: `tol`, the same
               threshold the convergence test uses), the budget grows by
               half of `n_iter` again, up to `max_iter` (default 3*n_iter).
               An iteration limit is an arbitrary number; a gain is a
               measurement, and a run that is still gaining when it is cut
               off has not finished. Step 14's PARTS 4 and 5 both stopped
               that way -- PART 5's last step before the cut was still
               taking 11% off the sum of squares.
    max_iter : the hard ceiling `extend` may grow the budget to
    extend_gain : the gain that justifies an extension (default: `tol`)
    prior    : (v1.1.13) {name: value} -- a value each parameter is pulled
               TOWARDS, normally the model's own declared default. The pull
               is deliberately far too weak to bend the fit: its weight is
               `prior_strength` times the largest curvature the DATA itself
               has, so a parameter the data determines moves about
               `prior_strength` of the way towards it (0.1% at the default)
               while a parameter the data cannot see at all goes essentially
               all the way. That is the whole point: it decides only what the
               data has no opinion about, and the whole-objective gate then
               proves it cost nothing.
    prior_strength : that weight, as a fraction of the data's own largest
               curvature -- which makes it a THRESHOLD: every direction in
               parameter space whose curvature is below it is decided by the
               prior, and every direction above it by the data. 1e-4 by
               default, which at Step 15's measured spectrum resolves only
               the handful of directions that are genuinely invisible.

    Returns a dict:
      params    the best card found (the start, if nothing improved it)
      S0, S     sum of squares at the start and at the end
      history   one record per iteration
      n_evals   HSPICE evaluations used
      ok        False only if the START could not be evaluated
      stopped   why the loop ended
      inert     columns dropped at the last iteration (data cannot see them)
      at_bound  parameters sitting on a box end at the answer
    """
    if legacy:
        return _lm_legacy(evaluate, residual, params, names, ranges,
                          n_iter=n_iter, rel_step=rel_step, lam0=lam0,
                          alphas=(0.25, 0.5, 1.0, 1.5), max_frac=max_frac,
                          tol=tol, max_retries=max_retries, tag=tag, log=log,
                          post=post)
    say = log if log is not None else (lambda *a, **k: None)
    names = [n for n in names if n in ranges and n in params]
    N = len(names)
    lo, hi, md = [], [], []
    for n in names:
        a, b, m = _mode(ranges[n])
        lo.append(_to_u(a, m))
        hi.append(_to_u(b, m))
        md.append(m)
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    width = hi - lo
    cap = np.maximum(float(max_frac) * width, 1e-12)      # one trust cap

    def card(u):
        c = dict(params)
        for k, n in enumerate(names):
            c[n] = _to_p(u[k], md[k])
        return post(c) if post is not None else c

    u = np.asarray([_to_u(params[n], md[k]) for k, n in enumerate(names)])
    u = np.clip(u, lo, hi)
    n_evals = [0]

    # ---- the prior (v1.1.13) -------------------------------------------
    p_idx, u_ref = [], []
    for k, n in enumerate(names):
        pv = (prior or {}).get(n)
        if pv is None:
            continue
        try:
            fv = float(pv)
        except (TypeError, ValueError):
            continue
        if md[k] == "log" and fv <= 0:
            continue
        p_idx.append(k)
        u_ref.append(float(np.clip(_to_u(fv, md[k]), lo[k], hi[k])))
    p_idx = np.asarray(p_idx, dtype=int)
    u_ref = np.asarray(u_ref, float)
    has_prior = bool(len(p_idx))
    p_mask = np.zeros(N, dtype=bool)
    if has_prior:
        p_mask[p_idx] = True
    w_p = [None]

    def aug(rv, uv):
        """the data residual with the prior's own rows appended."""
        if not has_prior or w_p[0] is None or rv is None:
            return rv
        return np.concatenate([rv, np.sqrt(w_p[0])
                               * (uv[p_idx] - u_ref) / cap[p_idx]])

    def run(cards, t):
        n_evals[0] += len(cards)
        return evaluate(cards, t)

    r0 = residual(run([card(u)], "%s_start" % tag)[0])
    if r0 is None:
        return {"params": dict(params), "ok": False, "S0": float("nan"),
                "S": float("nan"), "history": [], "n_evals": n_evals[0],
                "stopped": "the starting card could not be evaluated",
                "inert": [], "at_bound": []}
    n_dat = len(r0)
    u_start = u.copy()
    r_dat = r0
    r = aug(r0, u)
    S0 = S = float(r @ r)
    lam = float(lam0)
    hist = [{"it": 0, "S": S, "lam": lam, "u": u.tolist()}]
    say("    LM start: S = %.6g over %d residual entries, %d parameters"
        % (S, len(r), N))
    stopped = "iteration limit"
    small = 0
    inert_names = []
    budget = int(n_iter)
    hard = int(max_iter) if max_iter else (3 * int(n_iter) if extend
                                           else int(n_iter))
    hard = max(hard, budget)
    ex_gain = float(tol if extend_gain is None else extend_gain)
    it = 0
    while True:
        if it >= budget:
            last = hist[-1].get("gain") if hist else None
            if (extend and budget < hard and last is not None
                    and np.isfinite(last) and last >= ex_gain):
                grow = max(1, int(round(0.5 * int(n_iter))))
                budget = min(hard, budget + grow)
                say("    LM: still gaining %.2f%% (the run calls %.2f%%"
                    " converged), so the" % (100.0 * last, 100.0 * ex_gain))
                say("        budget grows %d -> %d  (TCADOpt v1.1.12)"
                    % (it, budget))
            else:
                if extend and it >= hard:
                    stopped = ("iteration limit (already extended to the"
                               " ceiling of %d)" % hard)
                elif extend and last is not None and np.isfinite(last):
                    stopped = ("the budget ran out and the last step gained"
                               " %.2f%%, below the %.2f%% that would have"
                               " extended it" % (100.0 * last,
                                                 100.0 * ex_gain))
                break
        it += 1
        # ---- Jacobian: all 2N perturbed cards in one batch --------------
        h = np.maximum(rel_step * width, 1e-12)
        up = np.minimum(u + h, hi)
        dn = np.maximum(u - h, lo)
        cards, idx = [], []
        for k in range(N):
            if up[k] - dn[k] <= 1e-12 * max(width[k], 1e-30):
                continue
            a, b = u.copy(), u.copy()
            a[k], b[k] = up[k], dn[k]
            cards += [card(a), card(b)]
            idx.append(k)
        res = run(cards, "%s_j%d" % (tag, it))
        J = np.zeros((n_dat, N))
        dead = []
        for j, k in enumerate(idx):
            rp = residual(res[2 * j])
            rm = residual(res[2 * j + 1])
            if rp is None or rm is None or len(rp) != n_dat \
                    or len(rm) != n_dat:
                dead.append(names[k])
                continue
            J[:, k] = (rp - rm) / (up[k] - dn[k])

        # ---- (1) scale every column by its own trust cap and screen -----
        Jz = J * cap                      # one unit of z = one trust cap
        cn = np.sqrt((Jz * Jz).sum(axis=0))
        cmax = float(cn.max()) if N else 0.0
        seen = (cn > col_drop * cmax) if cmax > 0 else np.zeros(N, bool)
        inert_names = [names[k] for k in range(N) if not seen[k]]
        # a column the DATA cannot see still has to be solved for when it has
        # a prior -- that is the only case where the prior decides anything.
        live = np.where(seen | p_mask)[0]
        if len(live) == 0:
            stopped = ("no parameter moves the residual at this card "
                       "(every column is flat)")
            hist.append({"it": it, "S": S, "lam": lam, "flat": True,
                         "inert": list(inert_names)})
            break
        # ---- the prior's weight, fixed once, from the DATA's own curvature
        if has_prior and w_p[0] is None:
            a_dat = float(np.max((Jz * Jz).sum(axis=0))) if N else 1.0
            w_p[0] = float(prior_strength) * max(a_dat, 1e-300)
            r = aug(r_dat, u)
            S = S0 = float(r @ r)
            say("    LM: a prior pulls %d parameter(s) towards the model's"
                " own values," % len(p_idx))
            say("        at %.1e of the data's own strongest curvature."
                " S including it: %.6g" % (float(prior_strength), S))
        if has_prior and w_p[0] is not None:
            P = np.zeros((len(p_idx), N))
            P[np.arange(len(p_idx)), p_idx] = np.sqrt(w_p[0])
            Jz = np.vstack([Jz, P])
        Jl = Jz[:, live]
        g = Jl.T @ r
        A = Jl.T @ Jl
        dg = np.diag(A).copy()
        # ---- (2) the damping floor --------------------------------------
        dg = np.maximum(dg, damp_floor * max(float(dg.max()), 1e-300))

        # ---- (4) the ladder: several lambdas, two step lengths, one batch
        def ladder(lam_now):
            """Every (lambda, step length) pair, as trial points in u."""
            tr, mt = [], []
            for mult in lam_ladder:
                lm_try = max(lam_now * float(mult), 1e-12)
                try:
                    dz = -np.linalg.solve(A + lm_try * np.diag(dg), g)
                except np.linalg.LinAlgError:
                    continue
                # ---- (3) per-component trust clipping -------------------
                dz = np.clip(dz, -1.0, 1.0)
                for a_ in ((1.0,) if mult != 1.0 else tuple(alphas)):
                    step = np.zeros(N)
                    step[live] = a_ * dz
                    z_new = np.clip(u + step * cap, lo, hi)
                    tr.append(z_new)
                    # predicted reduction from the linear model
                    d_used = ((z_new - u) / cap)[live]
                    pred = float(-2.0 * (g @ d_used) - d_used @ (A @ d_used))
                    mt.append({"lam": lm_try, "alpha": a_, "pred": pred})
            return tr, mt

        trials, meta, Ss, kb = [], [], [], -1
        for attempt in range(int(max_retries) + 1):
            trials, meta = ladder(lam)
            if not trials:
                lam = min(lam * 100.0, 1e9)
                continue
            rs = run([card(t_) for t_ in trials],
                     "%s_l%d_%d" % (tag, it, attempt))
            Ss = []
            for rr_, t_ in zip(rs, trials):
                v = residual(rr_)
                if v is None or len(v) != n_dat:
                    Ss.append((float("inf"), None, None))
                    continue
                va = aug(v, t_)
                Ss.append((float(va @ va), va, v))
            kb = int(np.argmin([x[0] for x in Ss]))
            if Ss[kb][0] < S * (1.0 - 1e-12):
                break
            lam = min(lam * 100.0, 1e9)
            say("    LM it %d: no step lowered S (best %.6g); lambda -> %.2g"
                % (it, Ss[kb][0], lam))
        if kb >= 0 and Ss and Ss[kb][0] < S * (1.0 - 1e-12):
            gain = (S - Ss[kb][0]) / S
            act = S - Ss[kb][0]
            pr = meta[kb]["pred"]
            rho = (act / pr) if pr > 0 else float("nan")
            u_prev = u
            u, r, S = trials[kb], Ss[kb][1], Ss[kb][0]
            r_dat = Ss[kb][2]
            lam = float(np.clip(meta[kb]["lam"]
                                * (0.3 if rho > 0.5 else 2.0), 1e-9, 1e9))
            mv = np.abs(u - u_prev) / cap
            top = [names[k] for k in np.argsort(-mv)[:3] if mv[k] > 1e-6]
            say("    LM it %d: S -> %.6g  (-%.2f%%)  lambda %.2g  step x%.2f"
                "  rho %.2f" % (it, S, 100.0 * gain, meta[kb]["lam"],
                                meta[kb]["alpha"], rho))
            if inert_names or dead or top:
                say("             moved most: %s%s%s"
                    % (_fmt_names(top),
                       ("   flat, dropped: %s" % _fmt_names(inert_names))
                       if inert_names else "",
                       ("   no column: %s" % _fmt_names(dead))
                       if dead else ""))
            hist.append({"it": it, "S": S, "lam": lam,
                         "alpha": meta[kb]["alpha"], "lam_used":
                         meta[kb]["lam"], "gain": gain, "rho": rho,
                         "u": u.tolist(), "dead": dead,
                         "inert": list(inert_names)})
        else:
            hist.append({"it": it, "S": S, "lam": lam, "rejected": True,
                         "inert": list(inert_names)})
            stopped = "no step lowers the sum of squares at any damping"
            break

        # ---- stopping: a small gain is a candidate, not a verdict -------
        if hist[-1].get("gain", 1.0) < tol:
            small += 1
        else:
            small = 0
        if small >= int(stall_patience) and it >= int(min_iter):
            stopped = ("converged: %d consecutive steps gained less than "
                       "%.1f%%" % (small, 100.0 * tol))
            break
    at_bound = [names[k] for k in range(N)
                if abs(u[k] - lo[k]) <= 1e-9 * max(abs(width[k]), 1e-30)
                or abs(u[k] - hi[k]) <= 1e-9 * max(abs(width[k]), 1e-30)]
    best = card(u)
    moved = dict((n, (float(params[n]), float(best[n]))) for n in names)
    pr = {}
    if has_prior:
        for j, k in enumerate(p_idx.tolist()):
            span = abs(u_ref[j] - u_start[k])
            frac = (abs(u[k] - u_start[k]) / span) if span > 1e-30 else 0.0
            # v1.1.14: the fraction is NOT clipped at 1. A parameter that
            # sailed past its prior moved because the DATA pushed it, and
            # reporting that as "100% of the way" hid it in Step 16, where
            # PDIBL1 went to 2.68 against a prior of 1.3 and the table said
            # "100%".
            pr[names[k]] = {"from": float(_to_p(u_start[k], md[k])),
                            "to": float(_to_p(u[k], md[k])),
                            "prior": float(_to_p(u_ref[j], md[k])),
                            "frac_moved": float(frac),
                            "overshot": bool(frac > 1.05)}
    return {"params": best, "ok": True, "S0": S0, "S": S, "history": hist,
            "n_evals": n_evals[0], "stopped": stopped, "moved": moved,
            "names": names, "inert": list(inert_names),
            "prior_weight": (None if w_p[0] is None else float(w_p[0])),
            "prior_pull": pr, "at_bound": at_bound}


# ---------------------------------------------------------------------------
#  the v1.1.10 algorithm, kept verbatim so the fault can be reproduced
# ---------------------------------------------------------------------------
def _lm_legacy(evaluate, residual, params, names, ranges, n_iter=6,
               rel_step=0.02, lam0=1.0e-2, alphas=(0.25, 0.5, 1.0, 1.5),
               max_frac=0.25, tol=0.01, max_retries=3, tag="lm", log=None,
               post=None):
    """TCADOpt v1.1.10's aligner, unchanged. Kept ONLY so a regression test
    can run the old code and the new code on the same problem."""
    say = log if log is not None else (lambda *a, **k: None)
    names = [n for n in names if n in ranges and n in params]
    N = len(names)
    lo, hi, md = [], [], []
    for n in names:
        a, b, m = _mode(ranges[n])
        lo.append(_to_u(a, m))
        hi.append(_to_u(b, m))
        md.append(m)
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    width = hi - lo

    def card(u):
        c = dict(params)
        for k, n in enumerate(names):
            c[n] = _to_p(u[k], md[k])
        return post(c) if post is not None else c

    u = np.asarray([_to_u(params[n], md[k]) for k, n in enumerate(names)])
    u = np.clip(u, lo, hi)
    n_evals = [0]

    def run(cards, t):
        n_evals[0] += len(cards)
        return evaluate(cards, t)

    r0 = residual(run([card(u)], "%s_start" % tag)[0])
    if r0 is None:
        return {"params": dict(params), "ok": False, "S0": float("nan"),
                "S": float("nan"), "history": [], "n_evals": n_evals[0],
                "stopped": "the starting card could not be evaluated"}
    r = r0
    S0 = S = float(r @ r)
    lam = float(lam0)
    hist = [{"it": 0, "S": S, "lam": lam, "u": u.tolist()}]
    say("    LM start: S = %.6g over %d residual entries, %d parameters"
        % (S, len(r), N))
    stopped = "iteration limit"
    for it in range(1, int(n_iter) + 1):
        h = np.maximum(rel_step * width, 1e-12)
        up = np.minimum(u + h, hi)
        dn = np.maximum(u - h, lo)
        cards, idx = [], []
        for k in range(N):
            if up[k] - dn[k] <= 1e-12 * max(width[k], 1e-30):
                continue
            a, b = u.copy(), u.copy()
            a[k], b[k] = up[k], dn[k]
            cards += [card(a), card(b)]
            idx.append(k)
        res = run(cards, "%s_j%d" % (tag, it))
        J = np.zeros((len(r), N))
        dead = []
        for j, k in enumerate(idx):
            rp = residual(res[2 * j])
            rm = residual(res[2 * j + 1])
            if rp is None or rm is None or len(rp) != len(r) \
                    or len(rm) != len(r):
                dead.append(names[k])
                continue
            J[:, k] = (rp - rm) / (up[k] - dn[k])
        g = J.T @ r
        A = J.T @ J
        dg = np.diag(A).copy()
        dg = dg + 1e-12 * max(float(dg.max()) if N else 1.0, 1e-30)
        accepted = False
        for attempt in range(int(max_retries) + 1):
            try:
                delta = -np.linalg.solve(A + lam * np.diag(dg), g)
            except np.linalg.LinAlgError:
                lam *= 10.0
                continue
            cap = np.maximum(max_frac * width, 1e-12)
            scale = float(np.max(np.abs(delta) / cap)) if N else 0.0
            if scale > 1.0:
                delta = delta / scale
            trials = [np.clip(u + a * delta, lo, hi) for a in alphas]
            rs = run([card(t) for t in trials],
                     "%s_l%d_%d" % (tag, it, attempt))
            Ss = []
            for rr_ in rs:
                v = residual(rr_)
                Ss.append((float(v @ v), v) if v is not None
                          and len(v) == len(r) else (float("inf"), None))
            kb = int(np.argmin([x[0] for x in Ss]))
            if Ss[kb][0] < S * (1.0 - 1e-9):
                gain = (S - Ss[kb][0]) / S
                u, r, S = trials[kb], Ss[kb][1], Ss[kb][0]
                lam = max(lam * 0.3, 1e-7)
                accepted = True
                say("    LM it %d: S -> %.6g  (-%.2f%%)  step x%.2f  "
                    "lambda %.2g%s"
                    % (it, S, 100.0 * gain, alphas[kb], lam,
                       ("  [no column: %s]" % ", ".join(dead))
                       if dead else ""))
                hist.append({"it": it, "S": S, "lam": lam,
                             "alpha": alphas[kb], "gain": gain,
                             "u": u.tolist(), "dead": dead})
                break
            lam *= 10.0
            say("    LM it %d: no step lowered S (best %.6g); lambda -> %.2g"
                % (it, Ss[kb][0], lam))
        if not accepted:
            stopped = "no step lowers the sum of squares at any damping"
            hist.append({"it": it, "S": S, "lam": lam, "rejected": True})
            break
        if hist[-1].get("gain", 1.0) < tol:
            stopped = "converged: the last step gained less than %.1f%%" \
                % (100.0 * tol)
            break
    best = card(u)
    moved = dict((n, (float(params[n]), float(best[n]))) for n in names)
    return {"params": best, "ok": True, "S0": S0, "S": S, "history": hist,
            "n_evals": n_evals[0], "stopped": stopped, "moved": moved,
            "names": names, "inert": [], "at_bound": []}


# ==========================================================================
#  THE ALIGNER AND THE JUDGE, MINIMISING THE SAME NUMBER   (v1.1.19)
# ==========================================================================
def scorer_residual(targets, curves, i_split, w_sub=1.0, w_on=1.0,
                    floor_iv=1.0e-14, floor_cv=1.0e-21, eps=1.0e-12):
    """A residual whose SUM OF SQUARES *IS* the scorer's total error.

    THREE STAGES DIED OF THIS, ACROSS TWO STEPS, AND THEY ALL DIED THE SAME WAY
    --------------------------------------------------------------------------
    `ratio_residual` gives the aligner a sum of squares to minimise. The gate
    then judges with `CurveResidualScorer`, whose total is

        E = sum_i  w_i * e_i  /  sum_i w_i          e_i = that sweep's RMS

    a weighted mean of ROOT-mean-squares. Those two are not the same function.
    Minimising sum(e_i^2) rewards taking the biggest error down even at the
    cost of doubling a small one; minimising sum(e_i) does not. Measured, on
    the real runs:

      Step 20 PART 5   aligner 6.996 -> 0.0504 (-99.3%)   gate +51.36%  REJECTED
      Step 21 PART 5   aligner 0.0396 -> 0.0371 (-6.4%)   gate +3.50%   REJECTED
      Step 21 PART 6   aligner 0.0404 -> 0.0246 (-39%)    gate +15.35%  REJECTED

    Three real improvements, thrown away, because the optimiser was told to
    climb one hill and then marked on a different one. Step 21's PART 5 is the
    clearest: CGDL took Cgd at Vd = 50 mV from 11.88% to about 10.5% and took
    Cgd at Vd = 0.60 V from 2.57% to about 5.5%. Sum of squares: better. Mean
    of RMS: worse. The gate was right and the aligner was asking the wrong
    question.

    THE FIX, AND WHY IT IS EXACT RATHER THAN A TUNING
    -------------------------------------------------
    For one block of per-point errors u (n points), the scorer uses
    e = ||u|| / sqrt(n). Scale that block by sqrt(w*e)/||u|| and it contributes

        || u * sqrt(w*e)/||u|| ||^2  =  w * e

    to the sum of squares. Do that for every block and the aligner's S is the
    scorer's E, term for term, with nothing left over. The scale depends on
    the current residual, so it is recomputed at every evaluation -- this is
    ordinary iteratively-reweighted least squares, the standard way to put a
    sum of NORMS in front of a Gauss-Newton solver, and its fixed point is the
    minimum of E itself.

    An I-V sweep contributes TWO blocks, because the scorer scores it in two
    halves: log10 decades below `i_split` and relative error above it, added
    as w_sub*e_sub + w_on*e_on. Both halves are weighted here exactly as the
    scorer weights them, so the identity holds for mixed target sets too.

    Returns None on the same conditions `ratio_residual` returns None, so it
    is a drop-in replacement.
    """
    if not targets:
        return None
    wsum = 0.0
    for t in targets:
        wsum += float(t.get("weight", 1.0))
    if wsum <= 0:
        wsum = 1.0
    blocks = []
    for t in targets:
        mc = curves.get(t["name"]) if curves else None
        if mc is None:
            return None
        iq = _interp_model(t["v"], mc[0], mc[1])
        if iq is None:
            return None
        a_ref = np.abs(np.asarray(t["i"], float))
        a_mod = np.abs(np.asarray(iq, float))
        kind = t.get("kind", "iv")
        floor = floor_cv if kind == "cv" else floor_iv
        base = np.isfinite(a_ref) & (a_ref > floor)
        good = base & np.isfinite(a_mod) & (a_mod > 0)
        if int(good.sum()) != int(base.sum()) or int(good.sum()) < 1:
            return None
        ar, am = a_ref[good], a_mod[good]
        w = float(t.get("weight", 1.0)) / wsum
        if kind == "cv":
            parts = [(w * float(w_on), (am - ar) / ar)]
        else:
            sub = ar < float(i_split)
            on = ~sub
            parts = []
            if int(sub.sum()) >= 2:
                parts.append((w * float(w_sub),
                              np.log10(am[sub]) - np.log10(ar[sub])))
            if int(on.sum()) >= 2:
                parts.append((w * float(w_on),
                              (am[on] - ar[on]) / ar[on]))
            if not parts:
                parts = [(w * float(w_on), (am - ar) / ar)]
        for wt, u in parts:
            u = np.asarray(u, float)
            n = float(len(u))
            nrm = float(np.linalg.norm(u))
            if nrm <= eps or n <= 0:
                blocks.append(np.zeros_like(u))
                continue
            e = nrm / np.sqrt(n)            # exactly the scorer's own RMS
            blocks.append(u * np.sqrt(wt * e) / nrm)
    return np.concatenate(blocks) if blocks else None
