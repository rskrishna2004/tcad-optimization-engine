# Changelog

All notable changes to TCADOpt are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-09-10

Compact-model parameter extraction. The engine gains a second thing it can do:
instead of searching a device's geometry for the best electrical
characteristics, it can fit a compact model's parameters to reference curves
from a device you have already simulated. Both paths share one optimizer core.

The optimizer itself is untouched. The Gaussian-process surrogate, the
trust-region schedule, the acquisition functions, both backends, the physics
guard, the knowledge seeding and the experiment database are all byte-identical
to v1.0.1, and every existing campaign reproduces exactly.

This is a minor version rather than a patch because it adds a capability, a new
entry point (`run_fit`), a new problem-file shape (`fit:` / `stages:`), and a
second worked example -- while remaining fully backward compatible.

### Added

- `tcadopt/l1_spec/curve_scorer.py` -- `CurveResidualScorer`, the objective for
  fitting a whole curve rather than a handful of scalar figures of merit.
  Every existing scorer reduces a simulation to scalars and combines them, which
  is right for design and wrong for extraction. Measured on this repository's
  own test: a candidate whose threshold voltage is 10 mV wrong changes I_ON by
  **0.02 %**, which a scalar scorer cannot see, while the curve residual reports
  **4.85 %**. The residual is split at a current threshold and reported as two
  numbers -- sub-threshold error in decades, on-state error as a fraction --
  because one measure cannot serve eight decades of current, and because when a
  fit stalls the two numbers say which half stalled.

- `tcadopt/l3_exec/hspice_parser.py` -- reads HSPICE `.lis` listings into
  curves. Parses the `.print` tables, which carry their own column headers, so
  the parser learns the layout from the file rather than assuming a vendor byte
  layout. Handles both scientific and SPICE engineering-suffix numbers
  (`2.8979e-12` and `2.8979p`), stitches a sweep split across printed pages back
  into one block, and drops the `1e30` end-of-data sentinel.

- `tcadopt/l3_exec/spice_exec.py` -- `HSpiceEvaluator`, a single-tool evaluator
  presenting the same `evaluate_batch(param_dicts, tag)` interface as
  `TCADEvaluator`. The existing runner requires two steps and abandons a run
  whose mesh file never appears (`optimizer/runner.py` lines 118-126); a circuit
  simulator has no mesh, so that check can never pass. Rather than weaken a code
  path the TCAD side depends on, extraction gets its own evaluator and reaches
  the optimizer, the database and the campaign loop unchanged.

- `tcadopt/l3_exec/targets.py` -- loads reference curves from CSV and groups
  them into named sweeps. Honours a `usable` column so rows the reference data
  itself flags as untrustworthy are excluded at load time and the count is
  printed rather than hidden.

- `tcadopt/l2_decks/cardgen.py` -- renders a candidate into a BSIM-CMG `.model`
  card and the HSPICE decks that exercise it. This fills what was an empty
  interface stub. Two things are enforced rather than left to the caller:
  `VERSION` is always written (LEVEL 72 defaults to 106.1, which has no
  gate-all-around module, so `GEOMOD=5` is rejected outright without it), and
  every generated deck's first line is a comment line that is *meant* to be the
  title, because a netlist's first line is the title whatever it contains.

- `tcadopt/l8_orch/run_fit.py` -- staged extraction with parameter freezing.
  A compact model has hundreds of parameters and most are degenerate with one
  another, so releasing them together produces a set that matches the data and
  means nothing. Each stage runs on the bias region where its own parameters
  dominate, with everything already extracted held frozen and persisted to
  `results/frozen_<spec>.json`. A stage that fails to converge freezes nothing.

- `tcadopt/l6_verify/identifiability.py` -- measures whether the data can
  determine the parameters at all. Builds the Jacobian of the residual around
  the extracted point and reports per-parameter sensitivity, pairwise
  collinearity, and the effective rank against the number of free parameters.
  A degenerate fit *fits perfectly*, so this cannot be seen in the fit error and
  has to be measured separately. Validated against a stand-in model with
  deliberately built-in degeneracies: it found all of them, and the effective
  rank of 7 out of 9 was exactly the two lost directions.

- `examples/extraction_demo/` -- extraction self-check that runs the complete
  staged pipeline with no circuit simulator, against a stand-in transistor with
  a known answer and known degeneracies.

- `problems/nsfet_gaa_fit.yaml` -- a complete five-stage extraction spec for a
  4-sheet gate-all-around nanosheet FET.

- `docs/PARAMETER_EXTRACTION.md` -- the complete extraction guide.
- `docs/EXTRACTION_TUTORIAL.md` -- a first extraction, start to finish.

- `tcadopt/__init__.py` -- the package now reports `__version__`.
  `check_setup.py` prints it, and also reports which simulator tools are
  configured for each of the two paths.

### Fixed

Three live defects found by a file-by-file audit of the whole repository, each
reproduced by running it rather than asserted.

- **The physics guard never fired.** `physics_guard._DEF_KB` resolved to
  `<repo_root>/knowledge/physics_rules.yaml`; the knowledge base ships beside
  the module at `tcadopt/l4_knowledge/physics_rules.yaml`. `load_kb()` swallows a
  missing file and returns an empty knowledge base, so the failure was silent:
  `validate()` passed **every** trial -- including one with SS = 20 mV/dec at
  350 K, well below the Boltzmann floor of 69.4, and leakage a thousand times
  the drive current -- and `physics_seeds()` returned `[]` on every campaign, so
  the `[physics-seed]` line the documentation promises never appeared. Both
  advertised physics-aware features were inert. The lookup now tries the shipped
  location first and falls back to the legacy one, so an installation that
  really does keep a top-level `knowledge/` still works.

- **The failure classifier read log files nothing writes.**
  `l3_exec/failures.py` looked for `tool_sde.log` and `tool_sdevice.log`;
  `runner.run_one` writes `tool_structure.log` and `tool_device.log`, and
  `certify.py` writes `sde.log` and `sdev.log`. Every real failure therefore fell
  through to `unknown_fail` and `ACTION_HINTS` never fired. It now reads every
  name any producer in the repository actually emits.

- **The runtime metrics module was missing the guard its twin had.**
  `l1_spec/metrics.py` and `l3_exec/metrics.py` are near-duplicates; only the l1
  copy had the strictly-increasing-x guard, and `l3_exec/execute.py` imports the
  l3 copy. A repeated bias point -- which every `DoZero`/ramp deck produces at
  the sweep ends -- made `np.gradient` divide by zero, so `gm` came back `nan`
  and `SS` came back `inf`, and the scorer then rejected a perfectly good
  simulation with `-1e9`. On the same input the runtime module returned `nan`
  where its twin returned 4.000e-04.

### Changed

- `check_setup.py` reports the engine version and the configured tools for both
  paths, not just the three Python packages.
- Every document has been revised for the two-path engine. `docs/README.md` now
  routes by what you are trying to do rather than listing files in one order.

### Compatibility

Fully backward compatible. No existing problem file, deck configuration,
environment variable or command changes. `run_campaign` and `run_pareto` behave
exactly as in v1.0.1; the three fixes above only ever turn a wrong answer into a
right one. The extraction path is additive and requires no new dependency: it
uses the same numpy, scipy and PyYAML.

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
