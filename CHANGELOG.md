# Changelog

All notable changes to TCADOpt are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
