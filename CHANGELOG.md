# Changelog

All notable changes to TCADOpt are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Releases 1.1.1 through 1.1.19 all came out of one long piece of work: a full
compact-model extraction for a 4-sheet gate-all-around nanosheet nFET, fitted
against Sentaurus TCAD reference data through PrimeSim HSPICE. Every one of
them exists because the extraction hit something the engine could not do or
got something wrong. The measured numbers quoted below are from that work.

The design-optimization path is untouched throughout. The Gaussian-process
surrogate, the trust-region schedule, the acquisition functions, both
backends, the physics guard, the knowledge seeding and the experiment database
behave exactly as in 1.1.0, and every existing campaign reproduces.

## [1.1.19] - 2026-09-29

The optimizer and the judge now minimise the same function, and a shared
parameter can be priced instead of gated.

### Added

- `tcadopt/l5_opt/lm_align.scorer_residual` -- a residual whose sum of squares
  IS the scorer's total error, term for term.

  The local aligner minimises a sum of squares. `CurveResidualScorer` totals a
  weighted mean of root-mean-squares. Those are different functions and they
  disagree in a predictable direction: squaring makes a large error worth far
  more than a small one, so minimising the sum of squares will happily double
  a small error to halve a big one, and the gate, counting errors at face
  value, correctly refuses. Three extraction stages across two steps found
  real improvements of 99.3 %, 6.4 % and 39 % and every one was thrown away by
  this mismatch.

  The fix is exact rather than a tuning. For one block of per-point errors `u`
  over `n` points the scorer uses `e = norm(u)/sqrt(n)`. Scaling that block by
  `sqrt(w*e)/norm(u)` makes its contribution to the sum of squares exactly
  `w*e`, which is the term the scorer adds. Summed over every block the two
  numbers are identical. The scale depends on the current residual and is
  recomputed at every evaluation, which is ordinary iteratively-reweighted
  least squares, and its fixed point is the minimum of the scorer's own total.
  Verified to machine precision on the project's own ten sweeps and six gate-row
  curves: scorer total 0.033149419049, residual norm squared 0.033149419049,
  difference 0.000e+00.

  It is a drop-in replacement for `ratio_residual` and returns `None` on the
  same conditions.

- `tcadopt/l5_opt/trade.py` -- pricing a parameter that two objectives disagree
  about, rather than gating it.

  A no-regression gate answers "keep or revert". For a parameter that both the
  current and the charge read, the honest answer is almost always "revert", and
  the run learns nothing about whether the trade was worth making. This module
  does not gate. It freezes the shared parameter at each of a ladder of values,
  completely re-fits the other objective on its own sweeps alone at each value,
  and tabulates what both sides end up with. The re-fit is what makes it
  honest: without it a ladder measures "the card was not built for this value",
  which is true and useless.

  `trade_curve` runs the ladder. `format_curve` tabulates it against the
  device's own targets. `knee` reports the best exchange rate and the best rung
  inside a cost cap. `pick_under_cap` applies that rule at one cap and
  `cap_ladder` applies it at several, so it is visible whether the cap or the
  physics made the choice. Every comparison filters non-finite readings first,
  because a share is a division and a card that destroys the channel charge has
  no share to report, and in Python a NaN reaching a `min` or a `max` first is
  returned unchallenged.

### Measured

On the project device, `KSATIV` sets the current's saturation voltage at
`bsimcmg_body.include` line 1901 and the charge's at line 2089, and the two
sides want different values. Sweeping it takes the drain's share of the
channel charge from 0.02 % to 43.4 % against the device's 48.2 %, and at
`KSATIV` near 1 the total gate capacitance in saturation lands within 0.08 %
of the device. The current fit put it at 0.26. BSIM-CMG 112.1.0 gives the
charge private copies of `VSAT`, `U0`, `UA`, `UC`, `UD` and `ETA0` and no
private copy of `KSATIV`, so the trade curve is the measured price of that
omission.

## [1.1.18] - 2026-09-29

The scope of a parameter becomes something the engine knows, states with a
source line, and then measures.

### Added

- `tcadopt/l4_knowledge/cv_scope.py` -- the free-zone table. Thirty five
  BSIM-CMG parameters that are read only inside the charge calculation and
  therefore cannot change the drain current, each with the line of
  `bsimcmg_body.include` that proves it, plus the nine that additionally need
  `CVMOD=1` to be read at all, plus four that look free from their names and
  are not (`KSATIV`, `MEXP`, `ETA1`, `QMFACTORCV`).

  `verify_scope` measures the claim instead of asserting it: it compares every
  current sweep point by point before and after a parameter is pushed, at a
  tolerance of one part in a billion, and reports the worst difference and
  where. Twenty six of the listed parameters were pushed on the real simulator
  and every one left all eight current sweeps bit-identical, reported as
  0.000e+00, twenty six times out of twenty six. The two deliberate controls,
  `KSATIV` and `MEXP`, moved the current by 4.678e-01 and 1.739e-01.

- `tcadopt/l6_verify/gate.FrozenGate` -- a gate for a stage inside the free
  zone. It accepts only if the capacitance improved AND no current sweep moved
  at all. Because the parameters provably cannot touch the current,
  bit-identical is a prediction rather than a tolerance, and a current sweep
  that does move means the scope claim is wrong for that model version, which
  the run says out loud before rolling back.

- `tcadopt/l6_verify/response.switch_compare` -- a per-parameter verdict across
  a mode switch. The previous version summed several parameters' effects, and
  on this project that hid `VSATCV`, whose grip on the drain's share of the
  channel charge goes from 0.03 points at `CVMOD=0` to 6.45 at `CVMOD=1`, a
  factor of two hundred, behind another parameter that acted at both settings.

- `tcadopt/l9_report/gaterow.floor_solve` -- an exact, iterated, clip-aware
  solve for the parasitic capacitance floor from the three measured off-state
  terminal values. Solves, clips anything that went out of bounds, drops the
  clipped knobs and re-solves with the remainder, rather than clipping without
  recomputing. Also `floor_of` and `best_constant`, which reports the single
  best constant for a term the model holds constant, weighted so the relative
  error is what is minimised.

### Fixed

- The parasitic floor solve in the previous release was gated on the ten-sweep
  total, which contains only the summed gate capacitance. A sum cannot see a
  floor being redistributed between three terminals, so a solve that took one
  terminal's error from 84.5 % to 38.4 % with the drain current unchanged was
  rolled back because the total rose by 0.0008.

- A move cap and a clip-at-zero were being applied to the floor solve without
  re-solving for the remaining terms, which bound one parameter to 9.08e-11
  when the answer was about 1.45e-10.

## [1.1.17] - 2026-09-28

The full gate row of capacitances, for free, from a print the engine was
already producing.

### Added

- `tcadopt/l3_exec/hspice_parser.op_records` and `op_gate_row` -- read the gate
  row out of the simulator's own operating-point print. With `.option list node`
  in the deck, every MOSFET block already ends with `cgs`, `cgd`, `cbtot` and
  `cgtot`, and `cgs + cgd + cbtot` equals `cgtot` exactly at every bias. Those
  four numbers had been in every listing this project ever produced. No deck
  change, no AC analysis, no extra simulation.

- `tcadopt/l3_exec/hspice_parser._merge_split_tables` -- stitches the tables a
  simulator splits when a `.print` asks for more than four columns. This is the
  bug that killed the previous release's run, below.

- `tcadopt/l3_exec/spice_exec` attaches the row to every capacitance result as
  derived curves named `<sweep>#cgd`, `#cgs` and `#cgb`, which need no deck and
  no extra run, with a fallback to the operating-point total if the AC table
  ever fails.

- `tcadopt/l3_exec/targets.load_cv_row_targets` -- turns `Cgd_F`, `Cgs_F` and
  `Cgb_F` into fit targets, behind a `cv_row_weight` setting.

- `tcadopt/l9_report/gaterow` gains `model_row`, `row_table`, `rms_by_term` and
  `split`. `split` reports the drain's share of the intrinsic channel charge
  with each terminal's own parasitic floor removed, which is the single most
  informative number on the charge side: at zero drain bias it must be about
  50 %, and in saturation the drain's share must collapse.

### Fixed

- **The previous release's extraction run failed in five minutes instead of
  running for two hours, and it was a parser bug.** A simulator prints at most
  four data columns per table. The deck asked for eight, the simulator split
  them across two tables under one bias heading, and the parser joined tables
  only when their column lists were identical. Ninety one biases became 182
  one-row blocks, the column reader returned a one-point curve, it was rejected
  as too short, and a downstream mask was built from `None`. The run's status
  stayed `partial` because the eight current sweeps were perfect, so the
  built-in fallback never fired.

- **The dry run could not have caught it**, because it replaced the parser
  itself with a stand-in. From this release on, a dry run replaces only the
  process launcher, and every line downstream of it is the shipping code. On
  the same stand-in listing the old parser gives 182 blocks and a one-point
  curve, the new one gives 1 block and 91 points.

- `identifiability.region_masks` no longer raises when handed a `None` mask.

### Changed

- Documented, because it is a real trap: driving the gate and reading the other
  three branch currents measures the gate COLUMN, and reference capacitance
  targets hold the gate ROW. Both sum to the total, so a closure check passes
  for either and cannot tell them apart. Measured on one bias of this project's
  own listing: column 23.95 / 26.27 / 0.27 aF, row 16.36 / 33.87 / 0.27 aF.
  Same total, 7.6 aF different split.

## [1.1.16] - 2026-09-28

### Added

- `tcadopt/l2_decks/cardgen` -- the capacitance deck now prints the whole gate
  row, the real and imaginary parts of the drain, source and body currents
  alongside the gate, at no extra simulation cost.
- `tcadopt/l3_exec/hspice_parser.cv_gate_row` -- returns all four capacitances
  with a closure check.
- `tcadopt/l9_report/gaterow.py` (new) -- `reference_row`, `compare`,
  `intrinsic` and `collapse`. Reads `Cgd_F`, `Cgs_F` and `Cgb_F` out of the
  reference CSV and puts the model beside the device with the parasitic floor
  removed.

### Fixed

- `hspice_parser.cv_columns` took the LAST real and imaginary pair in a table
  rather than the first. With four pairs present it would have silently
  returned the gate-to-body capacitance where the total was expected.
- `identifiability.box_audit` refused to widen a box around a parameter below
  the swing cut, and refuses to widen a mode switch at all. The previous
  version had widened an integer mode switch to -0.5, and had widened three
  capacitance parameters on the strength of scan bests worth about 3e-05 of
  residual.

### Measured

Why fitting the summed gate capacitance could never have worked on this device.
Between the two drain biases the device's total falls 24.1 %, its gate-to-drain
falls 49.5 %, and its gate-to-source falls 0.9 %. With each terminal's own
off-state floor removed, the drain end keeps 4.2 % of its channel charge and
the source end keeps 96.9 %. That is pinch-off, and the model's total fell only
4 % across the same change. The model was not mis-parameterised; it was putting
the channel charge in the wrong place, and the sum cannot see that because the
two errors partly cancel in it.

## [1.1.15] - 2026-09-27

### Added

- `tcadopt/l5_opt/pair_solve.py` (new) -- picks the pair of parameters whose
  measured effects point in the most different directions and solves the two by
  two. On this project it predicted the best available pair would move the two
  curve errors to -13.30 and +9.36; the run measured -13.29 and +9.41.
- `tcadopt/l6_verify/response` gains `map_signed` and `format_signed` for
  signed per-curve readings, and `refine`, which returns a parabolic minimum
  rather than the best grid point, with a blow-up guard.
- `tcadopt/l6_verify/gate.seed_greedy` -- applies proposed seeds one at a time
  and keeps only the ones that measure better.
- `tcadopt/l9_report/where` gains `band_vector` and `band_probe`.

### Fixed

- `inventory.raw_block` and `read_model_params` read only the first 400 lines
  of the simulator's parameter table. The block is 1878 lines and holds 1865
  parameters; 1469 of them were being reported as absent. Among the invisible
  ones were the entire set of private capacitance parameters that the charge
  equations use, which means every fit up to this point had been moving the
  charge's velocity saturation, mobility and DIBL as a silent side effect of
  fitting the current.
- `inventory` gains `core_names`, `variants`, and `twins` with `format_twins`,
  which find the parameters that silently track their DC namesakes and print
  them beside the card.

## [1.1.14] - 2026-09-26

### Added

- `tcadopt/l6_verify/response.py` (new) -- a one-dimensional response map that
  sweeps one parameter across its whole declared range and scores every curve
  separately, with an agree-or-conflict verdict and a joint best. This exists
  because a local optimizer cannot move a parameter whose local slope is zero,
  and two separate identifiability checks had disagreed about one such
  parameter with both of them correct.
- `tcadopt/l6_verify/inventory.py` (new) -- reads the complete model parameter
  table that the simulator already echoes into every listing under
  `.option list node`, and diffs it against the card. The card says what you
  asked for; the listing says what the model actually has.
- `tcadopt/l9_report.contrast` -- the split between two sweeps.

### Fixed

- The prior report no longer clips "towards its default" at 100 %.
- A crash on the last line of a run, `TypeError: key (...) is not a string`,
  which half-wrote the results file. Every key is stringified before dumping.

## [1.1.13] - 2026-09-24

### Added

- `tcadopt/l5_opt/lm_align` gains `prior`, a regularising pull towards the
  model's own declared default values, weighted at `prior_strength` times the
  data's own largest curvature. Measured on this project: rejected at 1e-4
  (5.02 % worse), accepted at 1e-5 (8.00 % better), moving three parameters
  from far-from-default back towards their declared values without losing fit.
- `identifiability.null_directions` and `format_null_directions` -- names the
  parameter combinations the data cannot determine, rather than only the
  individual parameters.
- `tcadopt/l9_report/where.py` (new) -- splits every sweep into bands and gives
  the signed error in each. Filling a layer that had been an empty stub.

## [1.1.12] - 2026-09-23

### Added

- `tcadopt/l6_verify/gate.py` (new) -- the scope rule and `StageGate`, the
  ordinary no-regression gate. A stage is scored on the sweeps it owns, and the
  gate then checks the whole objective did not get worse.
- `tcadopt/l5_opt/lm_align` gains `extend`, so a fit stops when it stops
  gaining rather than at a fixed iteration count.

### Fixed

- A stage script had fitted one capacitance parameter against a single
  capacitance sweep alone and halved every drain current. The scope rule and
  the no-regression gate make that structurally impossible rather than relying
  on the script being written correctly.

## [1.1.11] - 2026-09-23

### Added

- `tcadopt/l6_verify/connectivity.py` (new) -- a parameter-connectivity probe.

### Fixed

- `tcadopt/l5_opt/lm_align.py` rewritten: column screening, a damping floor,
  per-component trust clipping and a lambda ladder, with `legacy=True` kept so
  the old algorithm can be re-run for regression. The previous version scaled
  the whole step by its worst column, and three mobility parameters whose term
  is switched off in this configuration have almost zero Jacobian column, so
  the step size collapsed and the resulting card was railed and unphysical.
- `plausibility.fitted_but_inert` is judged on swing rather than on raw column
  norms.

## [1.1.1] through [1.1.10] - 2026-09-11 to 2026-09-22

The first ten releases of the extraction hardening, grouped because they were
one continuous piece of work on the same four modules.

### Added

- `tcadopt/l6_verify/identifiability.py` grew `scan_swing`, which reports how
  much of the residual a parameter's whole declared range is worth, and
  `box_adequacy`, which reports whether a parameter's box was wide enough for
  the fit to have found its own answer inside it.
- `tcadopt/l6_verify/physicality.py` (new) -- checks a result against physical
  invariants that cannot be violated, rather than against expectations.
- `tcadopt/l6_verify/plausibility.py` (new) -- checks a card against the
  model's own declared defaults and flags what has travelled far, plus
  `inert_scope`, which names parameters that were fitted and do nothing.
- `tcadopt/l8_orch/run_fit.py` gains tie support, for parameters the model
  defaults to each other, and rail reporting, for parameters that finish
  against the end of their box.
- `tcadopt/l1_spec/paramspace.py` and `tcadopt/l1_spec/curve_scorer.py`
  extended for the staged extraction schedule.

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
