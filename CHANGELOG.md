# Changelog

All notable changes to TCADOpt are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.1] - 2026-08-21

Optimizer core upgrade. The engine gains an optional high-power optimization
backend built on BoTorch, selected automatically when available. Nothing about
the TCAD layers changed: the problem-file format, the physics guard, the
knowledge seeding, the experiment database, certification, and the defense
dossier are all untouched. Existing campaigns reproduce exactly on the default
backend.

### Added
- `tcadopt/l5_opt/botorch_backend.py` -- optional `BoTorchBackend` implementing
  the existing optimizer interface (`propose` / `exhausted` / `force_restart`),
  so it drops into `Optimizer` with no orchestrator change:
  - **qLogEI / qLogNEI** acquisition instead of analytic EI. Measured on this
    engine's own GP at dim=17 with a converged 400-trial history, every one of
    6000 candidates scored EI < 1e-12 and up to 2201 of them scored exactly
    0.0, so the argmax was selecting arbitrarily among numerically identical
    zeros. The log-space formulation stays informative in that regime.
  - **Gradient-based acquisition optimization** (`optimize_acqf`, multi-start
    L-BFGS-B) instead of argmax over a fixed random candidate pool. A
    6000-point pool resolves fewer than 2 samples per axis in 17-D.
  - **Joint q-batch optimization** instead of the constant-liar heuristic.
  - **Sample-level outcome constraints** via a `ModelListGP` second output,
    replacing the independent-product-of-CDFs feasibility approximation.
    Constraint rows may come from trials the objective cannot use (infeasible
    or physics-suspect), which is why the per-output training sets differ.
- `make_backend(space, prefer=...)` backend selector with `auto` / `botorch` /
  `scipy` modes, overridable at runtime via `TCADOPT_BACKEND`.
- `NOTICE` -- third-party attribution and academic citations.
- `requirements-botorch.txt` -- optional dependencies, kept separate so the
  base install stays numpy + scipy + PyYAML.
- `docs/OPTIMIZER_BACKENDS.md` -- what each backend does, when to use which,
  and the measured comparison.

### Fixed
- Convergence report always printed `basin restarts: 0`. `_convergence_report`
  reads `getattr(getattr(opt, "tr", None), "restarts", 0)`, but `tr` lives on
  the backend and `Optimizer` had no such attribute, so the lookup silently
  fell through to the default on every campaign. The trust-region restarts
  were happening; the report could not see them. `Optimizer.tr` now forwards
  to the backend.

### Changed
- `Optimizer.__init__` takes `prefer=` and auto-selects a backend. Default
  behaviour on a machine without torch is unchanged.

### Compatibility
- The default backend is still `scipy_gp_v4_tr`: numpy + scipy only,
  Python 3.6. BoTorch requires Python >= 3.11, so the upgrade is opt-in by
  environment, never forced. If torch is absent the engine degrades silently
  and runs exactly as v1.0.0.

### Measured
On a 17-D TCAD-like landscape (broad bowl + ridge coupling + a local trap),
budget 36 initial + 6 rounds x 10, 3 seeds: mean gap to the optimum fell from
0.3835 to 0.1235, closing 67.8% of the remaining gap, winning on every seed.
Optimizer overhead rose from ~6 s to ~82 s per 96 proposals -- against TCAD
simulations costing minutes each, that is well under 1% of campaign wall time.

## [1.0.0] - 2026-07-11

First public release.

### Added
- Layered optimization pipeline (spec, decks, exec, knowledge, optimizer,
  verify, memory, orchestration, report).
- Gaussian process surrogate with trust-region Bayesian optimization,
  constrained expected improvement, and restart-on-stall.
- Physics-guided seeding: knowledge-based initial designs, device-agnostic
  via physical-role aliasing.
- Physics guard: quarantines results that violate physical invariants
  (subthreshold slope limit, on/off ordering, sign consistency).
- Parallel batch dispatch with device-agnostic result ledger.
- Experiment database: every trial stored, nothing lost or repeated.
- Single-objective and capped campaigns (`run_campaign`).
- Multi-objective Pareto front tracing via ParEGO (`run_pareto`).
- Champion certification and defense dossier (reproducibility, robustness,
  surrogate consistency, constraint margins, physics, dominance).
- Convergence evidence report for judging global-optimum confidence.
- Problem corpus: example YAML problem files for several device classes.
- Synthetic demo that runs the full pipeline with no simulator required.
- Documentation: getting started, architecture, problem-file format,
  simulator connection guide, physics knowledge base, and a case study.
