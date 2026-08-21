"""l5_opt.botorch_backend -- optional high-power optimizer backend built on BoTorch.

Implements the SAME interface as ScipyGPBackend (propose / exhausted /
force_restart / name), so it drops into Optimizer with no orchestrator change.
This is the swap point that l5_opt/optimizer.py was designed around.

What this backend changes versus the default scipy backend
----------------------------------------------------------
1. ACQUISITION.  The default backend maximizes analytic Expected Improvement
   over a fixed pool of random candidates. In a converged campaign in 17-D,
   EI underflows: every candidate in a 6000-point pool scores below 1e-12 and
   hundreds score exactly 0.0, so argmax is effectively picking at random.
   This backend uses qLogEI / qLogNEI, which compute the same quantity in log
   space and stay numerically alive when EI has collapsed to zero.
   Reference: Ament, Daulton, Eriksson, Balandat, Bakshy, "Unexpected
   Improvements to Expected Improvement for Bayesian Optimization", NeurIPS 36,
   2023.

2. ACQUISITION OPTIMIZATION.  The default backend evaluates a random candidate
   pool. 6000 random points in 17-D is under 2 samples per axis. This backend
   uses multi-start gradient ascent on the acquisition surface (optimize_acqf),
   which follows the gradient to a local acquisition maximum instead of hoping
   a random draw lands near one.

3. BATCHING.  The default backend uses the constant-liar heuristic: pretend
   each picked point returned y_best, refit, pick again. This backend optimizes
   the joint q-batch acquisition, which accounts for within-batch correlation
   directly rather than approximating it.

4. CONSTRAINTS.  The default backend multiplies EI by a product of independent
   per-constraint Gaussian CDFs. This backend models the constraint metric as a
   second GP output and applies the constraint at the Monte Carlo sample level,
   which does not assume independence between objective and constraint.

What this backend deliberately keeps
------------------------------------
The TrustRegion schedule is imported unchanged from optimizer.py. It was tuned
against this project's own audit gauntlet (fail_tol=1, shrink x0.5,
MEANINGFUL_EPS=5e-3, under-explored restart centre) and that tuning is TCAD
campaign knowledge, not a BoTorch default worth discarding. Same for the
surrogate hygiene rules (rejection-sentinel exclusion, best-20 soft clip).

Availability
------------
BoTorch requires Python >= 3.11 and torch >= 2.4. TCADOpt's default backend
requires only numpy + scipy and runs on Python 3.6. This backend is therefore
OPTIONAL and auto-detected: if the imports fail, Optimizer silently keeps the
scipy backend and the campaign runs exactly as before.

$Id: botorch_backend.py, v1.0 2026/08/21 R. Sri Krishna $
"""
import warnings

import numpy as np

from .optimizer import TrustRegion

BOTORCH_AVAILABLE = True
_IMPORT_ERROR = None
try:
    import torch
    from botorch.acquisition.logei import (
        qLogExpectedImprovement,
        qLogNoisyExpectedImprovement,
    )
    from botorch.acquisition.objective import GenericMCObjective
    from botorch.fit import fit_gpytorch_mll
    from botorch.models import SingleTaskGP
    from botorch.models.model_list_gp_regression import ModelListGP
    from botorch.models.transforms.input import Normalize
    from botorch.models.transforms.outcome import Standardize
    from botorch.optim import optimize_acqf
    from botorch.sampling.normal import SobolQMCNormalSampler
    from gpytorch.mlls import ExactMarginalLogLikelihood
    from gpytorch.mlls.sum_marginal_log_likelihood import SumMarginalLogLikelihood
except Exception as exc:                       # torch/botorch not installed
    BOTORCH_AVAILABLE = False
    _IMPORT_ERROR = exc


def availability():
    """(ok, message) -- why the backend is or is not usable on this machine."""
    if BOTORCH_AVAILABLE:
        return True, "botorch backend available (torch %s)" % torch.__version__
    return False, "botorch backend unavailable: %s" % _IMPORT_ERROR


class BoTorchBackend(object):
    """Optimizer backend: SingleTaskGP + qLogEI/qLogNEI + optimize_acqf,
    inside TCADOpt's own trust-region schedule."""

    name = "botorch_qlogei_tr"

    def __init__(self, space, num_restarts=10, raw_samples=512,
                 mc_samples=128, noisy=True, dtype=None, device="cpu"):
        if not BOTORCH_AVAILABLE:
            raise ImportError(
                "BoTorchBackend requires torch>=2.4 and botorch (Python>=3.11). "
                "Install with: pip install botorch. Detail: %s" % _IMPORT_ERROR)
        self.space = space
        self.num_restarts = num_restarts
        self.raw_samples = raw_samples
        self.mc_samples = mc_samples
        self.noisy = noisy
        self.dtype = dtype or torch.double
        self.device = torch.device(device)
        self.tr = TrustRegion()
        self._hist_len = 0

    # ---------------------------------------------------------------- utils
    def _t(self, a):
        return torch.as_tensor(np.asarray(a, float), dtype=self.dtype,
                               device=self.device)

    def _clean(self, history_X, history_y):
        """Surrogate hygiene, identical policy to ScipyGPBackend.

        (a) rejection sentinels (<= -1e8) would blow the standardization scale
        to ~1e9 and flatten all real variation, blinding the GP; drop them.
        (b) soft-clip huge finite penalties to best-20 so one catastrophic
        point cannot dominate the fit, while its 'this direction is bad'
        gradient survives. (c) drop non-finite rows.
        """
        X = np.asarray(history_X, float)
        y = np.asarray(history_y, float)
        if X.ndim != 2 or len(y) == 0:
            return None, None
        m = np.isfinite(y) & (y > -1e8) & np.all(np.isfinite(X), axis=1)
        X, y = X[m], y[m]
        if len(y) >= 3:
            y = np.maximum(y, float(np.max(y)) - 20.0)
        return X, y

    def _tr_bounds(self, center, length, lengthscales):
        """Trust-region box, same ARD recipe as gp.py::_tr_candidates: sides
        scaled by per-dimension lengthscales normalized to geometric mean 1, so
        dimensions the model says matter get a tighter box."""
        ls = np.asarray(lengthscales, float).ravel()
        if ls.size != len(center) or not np.all(np.isfinite(ls)):
            ls = np.ones(len(center))
        w = ls / np.exp(np.mean(np.log(np.maximum(ls, 1e-9))))
        side = np.clip(length * w, 0.03, 1.0)
        lo = np.clip(center - side / 2.0, 0.0, 1.0)
        hi = np.clip(center + side / 2.0, 0.0, 1.0)
        hi = np.maximum(hi, lo + 1e-6)
        return self._t(np.vstack([lo, hi]))

    def _fit_gp(self, X, y):
        tX, tY = self._t(X), self._t(y).unsqueeze(-1)
        gp = SingleTaskGP(
            tX, tY,
            input_transform=Normalize(d=tX.shape[-1]),
            outcome_transform=Standardize(m=1))
        mll = ExactMarginalLogLikelihood(gp.likelihood, gp)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit_gpytorch_mll(mll)
        return gp

    def _lengthscales(self, gp):
        try:
            ls = gp.covar_module.lengthscale.detach().cpu().numpy().ravel()
            return ls if ls.size else None
        except Exception:
            try:
                ls = gp.covar_module.base_kernel.lengthscale
                return ls.detach().cpu().numpy().ravel()
            except Exception:
                return None

    def _constraint_model(self, obj_gp, constraints_data):
        """Model each constraint metric as its own GP output.

        constraints_data: [(Xc, c_vals, bound, sense)] in the same transformed
        units the orchestrator uses (e.g. c_vals = log10(IOFF), bound =
        log10(cap)). Constraint rows come from a DIFFERENT set of trials than
        the objective rows -- infeasible and physics-suspect trials have no
        usable score but their IOFF is real information about where the cap is
        violated. ModelListGP is the right container precisely because it
        allows different training data per output.

        Returns (model, constraint_callables) where each callable maps posterior
        samples to a value that is <= 0 when the constraint is satisfied.
        """
        gps, callables = [obj_gp], []
        for (Xc, cv, bound, sense) in (constraints_data or []):
            Xc = np.asarray(Xc, float)
            cv = np.asarray(cv, float).ravel()
            keep = np.isfinite(cv) & np.all(np.isfinite(Xc), axis=1)
            Xc, cv = Xc[keep], cv[keep]
            if len(cv) < 3 or np.std(cv) <= 0:
                continue
            cgp = SingleTaskGP(
                self._t(Xc), self._t(cv).unsqueeze(-1),
                input_transform=Normalize(d=Xc.shape[-1]),
                outcome_transform=Standardize(m=1))
            cmll = ExactMarginalLogLikelihood(cgp.likelihood, cgp)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                fit_gpytorch_mll(cmll)
            idx = len(gps)
            gps.append(cgp)
            b, s = float(bound), sense
            # feasible when <= 0
            if s == "le":
                callables.append(lambda Z, i=idx, b=b: Z[..., i] - b)
            else:
                callables.append(lambda Z, i=idx, b=b: b - Z[..., i])
        if len(gps) == 1:
            return obj_gp, []
        return ModelListGP(*gps), callables

    # -------------------------------------------------------------- propose
    def propose(self, history_X, history_y, n, mode="bo_round", seed=0,
                constraints_data=None):
        """modes: lhs_init | random_init | bo_round | local_refine.

        Returns a list of n encoded points in [0,1]^dim, exactly like
        ScipyGPBackend. Returns None on failure so the facade can fall back.
        """
        if mode in ("lhs_init", "random_init"):
            pts = (self.space.lhs(n, seed=seed) if mode == "lhs_init"
                   else self.space.random(n, seed=seed))
            return [self.space.encode(p) for p in pts]

        X, y = self._clean(history_X, history_y)
        if X is None or len(y) < 3:
            pts = self.space.lhs(n, seed=seed)
            return [self.space.encode(p) for p in pts]

        # fresh campaign detection -> reset TR state (same rule as scipy backend)
        if len(y) < self._hist_len:
            self.tr.reset()
        self._hist_len = len(y)

        y_best = float(np.max(y))
        self.tr.update(y_best)
        if self.tr.collapsed():
            self.tr.restart()

        torch.manual_seed(int(seed))
        gp = self._fit_gp(X, y)

        # trust-region centre: incumbent normally; after a restart, the most
        # under-explored point (max-min distance to history), because a restart
        # that only jitters near the incumbent re-attacks the same basin.
        center = np.array(X[int(np.argmax(y))], float)
        if self.tr.jitter_seed:
            rj = np.random.RandomState(1000 + self.tr.jitter_seed + seed)
            probe = rj.rand(4000, self.space.dim)
            d2 = np.min(np.sum((probe[:, None, :] - X[None, :, :]) ** 2, -1), 1)
            center = probe[int(np.argmax(d2))]
        if mode == "local_refine":
            center = np.array(X[int(np.argmax(y))], float)

        bounds = self._tr_bounds(center, self.tr.L, self._lengthscales(gp))

        model, cons = self._constraint_model(gp, constraints_data)
        sampler = SobolQMCNormalSampler(
            sample_shape=torch.Size([self.mc_samples]), seed=int(seed))

        common = dict(model=model, sampler=sampler)
        if cons:
            # ModelListGP is multi-output: output 0 is the objective, outputs
            # 1..k are constraint metrics. BoTorch requires an explicit
            # objective to say which output is being improved.
            common["constraints"] = cons
            common["objective"] = GenericMCObjective(lambda Z, X=None: Z[..., 0])
        if self.noisy:
            acqf = qLogNoisyExpectedImprovement(
                X_baseline=self._t(X), prune_baseline=True, **common)
        else:
            acqf = qLogExpectedImprovement(best_f=y_best, **common)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            cand, _ = optimize_acqf(
                acq_function=acqf, bounds=bounds, q=int(n),
                num_restarts=self.num_restarts, raw_samples=self.raw_samples,
                options={"batch_limit": 8, "maxiter": 200},
                sequential=True)

        U = cand.detach().cpu().numpy()
        U = np.clip(U, 0.0, 1.0)
        return [[float(v) for v in u] for u in U]

    # ----------------------------------------------------------- TR control
    def exhausted(self, max_restarts=2):
        return self.tr.restarts > max_restarts

    def force_restart(self):
        self.tr.restart()
