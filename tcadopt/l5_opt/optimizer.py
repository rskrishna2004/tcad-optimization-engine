"""l5_opt.optimizer -- optimization facade.

Wraps the proven scipy GP (gp.py: GP + propose_batch, analytic-gradient, constant-
liar batching) behind a stable interface so the orchestrator never imports gp.py
directly. This is THE swap point: a BoTorch backend can implement the same
propose()/floor_detected() signatures and be dropped in with no orchestrator change.

Encoding convention: everything here is in encoded [0,1]^dim space (ParamSpace
handles encode/decode), exactly what propose_batch expects.

$Id: optimizer.py, v2.0 2026/07/05 [YOUR NAME] - INTELLIGENCE UPGRADE: stateful trust-region schedule (expand x1.6 after 2 improving rounds, shrink x0.6 after 2 stalls, restart from perturbed incumbent on collapse; auto-reset when campaign history restarts); feasibility-data plumbing (constraints_data -> feasibility GPs -> constrained EI); floor policy: restart-then-stop via exhausted(). v1: facade over gp.py. $
"""
import os
import sys

import numpy as np

_DEF_LEGACY = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "optimizer")


def _load_gp(legacy_dir=None):
    legacy_dir = legacy_dir or os.environ.get("TCADOPT_LEGACY", _DEF_LEGACY)
    if legacy_dir not in sys.path:
        sys.path.insert(0, legacy_dir)
    import gp  # noqa: E402  (the proven scipy GP)
    return gp


class TrustRegion(object):
    """TuRBO-style schedule. Success = campaign best improved since last
    propose; expand after `succ_tol` successes, shrink after `fail_tol`
    stalls, and on collapse (L < L_min) restart from a perturbed incumbent.
    restarts are counted so the orchestrator can stop after budget.

    WHAT CHANGED IN v1.1.4, AND WHAT THE MEASUREMENT ACTUALLY SHOWED
    ----------------------------------------------------------------
    `MEANINGFUL_EPS` was a single ABSOLUTE number, 5e-3 in score units: the
    smallest improvement that counts as progress. Below it a round is a stall,
    and one stall halves L.

    5e-3 was tuned for DESIGN optimization, where the score is a weighted sum
    of log10 figures of merit. For EXTRACTION the score is minus a residual,
    and the residual shrinks as the fit improves -- so a threshold fixed in
    absolute terms becomes a larger and larger fraction of what is left to
    gain. That is a real argument and it is why the option exists:

        eps(y) = max(eps_abs, eps_rel * |y_best|)

    with eps_abs = 5e-3 and eps_rel = 0.0 as defaults, which reproduces the
    pre-1.1.4 behaviour EXACTLY and leaves every existing design campaign
    untouched.

    AND NOW THE HONEST PART, because it was measured rather than assumed.
    A two-parameter sub-threshold fit was isolated on an analytic surface --
    the optimizer and the ParamSpace and nothing else -- with the brute-force
    optimum known to be 0.029559. Three random seeds each, median of three:

        budget  80 (16 init + 16 rounds x 4)   old eps   0.05575
        budget  80 (16 init + 16 rounds x 4)   new eps   0.05575   IDENTICAL
        budget 216 (24 init + 48 rounds x 4)   new eps   0.03110   converged

    The threshold change made NO DIFFERENCE on that surface -- the two runs
    agreed to every printed digit. What mattered was the budget: eighty
    evaluations land a factor of 1.9 off the optimum, and two hundred and
    sixteen land on it. The narrow diagonal valley a correlated parameter pair
    produces is not a trust-region problem; it is simply a surface that needs
    more points than a two-dimensional problem looks like it should.

    So this option is kept because its reasoning is sound for residuals far
    below 5e-3, where an absolute threshold really does stop the search dead --
    but it is NOT the fix for a slow 2-D fit, and the thing to reach for there
    is the evaluation budget. Recording a change that turned out not to matter
    is more useful than quietly deleting it.

    The measured HSPICE noise floor is what makes a small eps_abs safe at all:
    l6_verify found it to be EXACTLY 0.000000e+00 on both .dc and .ac analyses,
    so there is no simulator noise for a small threshold to chase. Where that
    is not true, raise eps_abs to the noise floor and no further.
    """

    L0, L_MIN, L_MAX = 0.4, 0.045, 1.0
    MEANINGFUL_EPS = 5e-3            # default absolute delta counting as progress

    def __init__(self, eps_abs=None, eps_rel=0.0, l0=None, l_min=None):
        self.eps_abs = (self.MEANINGFUL_EPS if eps_abs is None
                        else float(eps_abs))
        self.eps_rel = float(eps_rel)
        self._l0 = self.L0 if l0 is None else float(l0)
        self._l_min = self.L_MIN if l_min is None else float(l_min)
        self.reset()

    def eps(self, y_best):
        """The improvement that counts as progress, at this score level."""
        return max(self.eps_abs, self.eps_rel * abs(float(y_best)))

    def reset(self):
        self.L = self._l0
        self.succ = 0
        self.fail = 0
        self.restarts = 0
        self.prev_best = None
        self.jitter_seed = 0

    def update(self, y_best):
        """Feed the current campaign best BEFORE proposing; adapts L.
        Gauntlet-tuned schedule: with q~24 parallel points per round in 20-D,
        one whole stalled ROUND is strong evidence the region is mined out, so
        shrink on every stall (TuRBO fail-tolerance ~ d/q = 1) and by 0.5 --
        the old (2-stall, x0.6) schedule could not collapse-and-restart inside
        a realistic 6-10 round budget, which left the deceptive-basin escape
        mechanism unreachable (0/3 escapes in the audit gauntlet)."""
        # MEANINGFUL improvement only: asymptotic creep (deltas below ~0.005
        # score units, i.e. ~1% in the linear metric) is a stall, not success.
        # Audit gauntlet: a decoy basin fed 1e-3/round improvements forever,
        # which the old 1e-6 threshold counted as progress -> the TR never
        # collapsed and the restart machinery was dead code.
        if self.prev_best is not None:
            if y_best > self.prev_best + self.eps(y_best):
                self.succ += 1
                self.fail = 0
                if self.succ >= 2:
                    self.L = min(self.L * 1.6, self.L_MAX)
                    self.succ = 0
            else:
                self.fail += 1
                self.succ = 0
                if self.fail >= 1:
                    self.L = self.L * 0.5
                    self.fail = 0
        self.prev_best = max(y_best, self.prev_best) if self.prev_best is not None else y_best

    def collapsed(self):
        return self.L < self._l_min

    def restart(self):
        self.L = self._l0
        self.succ = self.fail = 0
        self.restarts += 1
        self.jitter_seed += 1


class ScipyGPBackend(object):
    """Default optimizer backend: gp.py v4 + stateful trust region +
    optional feasibility-aware (constrained) EI."""

    name = "scipy_gp_v4_tr"   # v2.2: fast-collapse TR + under-explored restarts

    def __init__(self, space, legacy_dir=None, n_cand=6000, anchors=10,
                 tr_kw=None):
        self.space = space
        self.gp = _load_gp(legacy_dir)
        self.n_cand = n_cand
        self.anchors = anchors
        self.tr = TrustRegion(**(tr_kw or {}))
        self._hist_len = 0

    def _feas_gps(self, constraints_data):
        """constraints_data: list of (Xc, c_vals, bound, sense) in encoded/
        transformed space (e.g. c_vals = log10(IOFF), bound = log10(cap)).
        Returns gp.propose_batch-ready constraint triples."""
        out = []
        for (Xc, cv, bound, sense) in (constraints_data or []):
            Xc = np.asarray(Xc, float)
            cv = np.asarray(cv, float)
            if len(cv) >= 3 and np.std(cv) > 0:
                out.append((self.gp.GP(Xc, cv), float(bound), sense))
        return out

    def propose(self, history_X, history_y, n, mode="bo_round", seed=0,
                constraints_data=None):
        """modes: lhs_init | random_init | bo_round | local_refine."""
        if mode in ("lhs_init", "random_init"):
            pts = (self.space.lhs(n, seed=seed) if mode == "lhs_init"
                   else self.space.random(n, seed=seed))
            return [self.space.encode(p) for p in pts]

        X = np.asarray(history_X, float)
        y = np.asarray(history_y, float)
        # SURROGATE HYGIENE: (a) rejection sentinels (<= -1e8) would set the
        # standardization scale to ~1e9 and flatten all real variation -> the
        # GP goes blind; exclude them. (b) soft-clip huge finite penalties to
        # best-20 so one catastrophic point cannot dominate the fit while its
        # 'this direction is bad' gradient survives. (c) drop non-finite.
        m = np.isfinite(y) & (y > -1e8)
        X, y = X[m], y[m]
        if len(y) >= 3:
            y = np.maximum(y, float(np.max(y)) - 20.0)
        if len(y) < 3:
            pts = self.space.lhs(n, seed=seed)
            return [self.space.encode(p) for p in pts]

        # detect a fresh campaign (history restarted) -> reset the TR state
        if len(y) < self._hist_len:
            self.tr.reset()
        self._hist_len = len(y)

        y_best = float(np.max(y))
        self.tr.update(y_best)
        if self.tr.collapsed():
            self.tr.restart()

        gp = self.gp.GP(X, y)
        k = min(self.anchors, len(y))
        anchor = X[np.argsort(y)[::-1][:k]]
        if mode == "local_refine":
            anchor = X[np.argsort(y)[::-1][:min(3, len(y))]]

        # trust-region center: the incumbent normally; after a restart, the
        # MOST UNDER-EXPLORED point (max-min-distance to all history) -- a
        # restart that just jitters near the incumbent re-attacks the same
        # basin (audit gauntlet (a): 0/3 decoy escapes with local restarts).
        center = np.array(X[int(np.argmax(y))], float)
        if self.tr.jitter_seed:
            rj = np.random.RandomState(1000 + self.tr.jitter_seed + seed)
            probe = rj.rand(4000, self.space.dim)
            d2 = np.min(np.sum((probe[:, None, :] - X[None, :, :]) ** 2, -1), 1)
            center = probe[int(np.argmax(d2))]

        cons = self._feas_gps(constraints_data)
        U = self.gp.propose_batch(
            gp, y_best, n, self.space.dim, n_cand=self.n_cand, seed=seed,
            X_anchor=anchor, tr_center=center, tr_length=self.tr.L,
            constraints=cons if cons else None)
        return [[float(v) for v in u] for u in U]

    def exhausted(self, max_restarts=2):
        """True once the TR has collapsed+restarted more than max_restarts:
        the local landscape is mined out in every attacked direction."""
        return self.tr.restarts > max_restarts

    def force_restart(self):
        """Campaign-level floor detected -> restart NOW (fresh region, full
        L0), regardless of the internal shrink schedule. This is the wiring
        that makes 'floor -> restart' deterministic; the audit found the old
        loop only printed the intention while the backend kept its state."""
        self.tr.restart()


def make_backend(space, prefer="auto", legacy_dir=None, **kw):
    """Choose an optimizer backend.

    prefer='auto'    -- use BoTorch if torch/botorch import, else scipy (default)
    prefer='botorch' -- require BoTorch; raise if unavailable
    prefer='scipy'   -- always the dependency-light scipy backend

    Override at runtime without editing code:  export TCADOPT_BACKEND=scipy
    BoTorch needs Python>=3.11 + torch; the scipy backend needs only numpy and
    scipy and runs on Python 3.6, which is why 'auto' degrades silently instead
    of failing. A campaign is never blocked by a missing optional dependency.
    """
    prefer = os.environ.get("TCADOPT_BACKEND", prefer).lower()
    tr_kw = kw.pop("tr_kw", None)
    if prefer == "scipy":
        return ScipyGPBackend(space, legacy_dir=legacy_dir, tr_kw=tr_kw)
    try:
        from .botorch_backend import BoTorchBackend
        return BoTorchBackend(space, **kw)
    except Exception as exc:
        if prefer == "botorch":
            raise
        if os.environ.get("TCADOPT_VERBOSE_BACKEND"):
            print("    [backend] botorch unavailable (%s) -> scipy backend"
                  % type(exc).__name__)
        return ScipyGPBackend(space, legacy_dir=legacy_dir, tr_kw=tr_kw)


class Optimizer(object):
    """Front door used by the orchestrator. Backend is swappable."""

    def __init__(self, space, backend=None, legacy_dir=None, prefer="auto",
                 tr_kw=None):
        """`tr_kw` is handed to the trust region: {eps_abs, eps_rel, l0, l_min}.
        Omitted, the schedule is exactly the one the design gauntlet was tuned
        against. An extraction stage passes eps_rel so that "progress" is a
        fraction of the residual still left rather than a fixed number of score
        units -- see TrustRegion's docstring for the measurement that made this
        necessary."""
        self.space = space
        self.backend = backend or make_backend(space, prefer=prefer,
                                               legacy_dir=legacy_dir,
                                               tr_kw=tr_kw)

    def propose(self, history_X, history_y, n, mode="bo_round", seed=0,
                constraints_data=None):
        try:
            return self.backend.propose(history_X, history_y, n, mode=mode,
                                        seed=seed,
                                        constraints_data=constraints_data)
        except TypeError:      # legacy backend without the new kwarg
            return self.backend.propose(history_X, history_y, n, mode=mode,
                                        seed=seed)

    def exhausted(self, max_restarts=2):
        fn = getattr(self.backend, "exhausted", None)
        return fn(max_restarts) if fn else True

    def force_restart(self):
        fn = getattr(self.backend, "force_restart", None)
        if fn:
            fn()

    # -- floor detection: the "local-exhaustion certificate" -------------
    @staticmethod
    def floor_detected(best_score_history, patience=2, eps=1e-3):
        """True if the best score has not improved by > eps for `patience`
        consecutive rounds -> we are at a local optimum / physics floor.
        Encodes the empirical stop signal we observed across every campaign:
        when BO rounds stop beating the incumbent, more search is wasted budget."""
        if len(best_score_history) <= patience:
            return False
        recent = best_score_history[-(patience + 1):]
        return (recent[-1] - recent[0]) <= eps

    @property
    def backend_name(self):
        return getattr(self.backend, "name", "unknown")

    @property
    def tr(self):
        """Expose the backend's trust region on the facade.

        BUGFIX v1.0.1: run_campaign._convergence_report does
        getattr(getattr(opt, "tr", None), "restarts", 0) where `opt` is this
        Optimizer, not the backend. Optimizer had no `tr`, so the getattr
        chain always fell through to the default and every campaign printed
        'basin restarts: 0' no matter how many trust-region restarts actually
        happened. The restart machinery was working; the report was blind
        to it.
        """
        return getattr(self.backend, "tr", None)
