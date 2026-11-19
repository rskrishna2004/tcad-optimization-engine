# Changelog

All notable changes to TCADOpt are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Releases 1.1.1 through 1.2.0 all came out of one long piece of work: a full
compact model extraction for a 4 sheet gate-all-around nanosheet nFET, fitted
against Sentaurus TCAD reference data through PrimeSim HSPICE. Every one of
them exists because the extraction hit something the engine could not do or
got something wrong. The measured numbers quoted below are from that work.
That extraction is complete as of 1.2.0, and the limit it ran into is a
property of BSIM-CMG rather than of the engine. It is quoted with a number.

The design optimization path is untouched throughout. The Gaussian process
surrogate, the trust region schedule, the acquisition functions, both
backends, the physics guard, the knowledge seeding and the experiment database
behave exactly as in 1.1.0, and every existing campaign reproduces.

## [1.2.0] - 2026-11-18

The extraction this changelog has been tracking since 1.1.1 is finished. This
release carries the modules it needed and, more importantly, the method it
settled on, because three of the four expensive failures in that work were not
bugs in the engine. They were the engine being pointed at the wrong number.

Against the card 1.1.19 shipped, on the same device and the same sixteen
reference curves, measured through PrimeSim HSPICE:

```
                                       1.1.19        1.2.0      change
  the eight drain current sweeps      0.014114     0.014114      0.00 %
  the eight capacitance, mean of rms  0.026916     0.024302     -9.71 %
  the eight capacitance, POOLED       0.032142     0.027146    -15.54 %
  the sixteen curve total             0.024116     0.020996    -12.94 %
  the eight capacitance, total in aF  2.617306     2.204624    -15.77 %
```

The drain current is identical to the last digit printed. Every capacitance
step used only parameters the dependency walk proves cannot reach the current,
and then measured that the current had not moved rather than assuming it.

The design optimization path is untouched, as in every release since 1.1.0.
The Gaussian process surrogate, the trust region schedule, the acquisition
functions, both backends, the physics guard, the knowledge seeding and the
experiment database behave exactly as before and every existing campaign
reproduces.

### Added

- `tcadopt/l6_verify/floor.py` -- a per curve survey of where the error lives,
  with `rel_ss` as the pooled building block, plus `stale_weights`, which
  compares a stored weight set against the curves as they are now and reports
  the weights that no longer describe anything.

  This exists because of the most expensive failure in the whole extraction. A
  weighted objective was built from one card's residuals, and the card then
  changed underneath it. A curve sitting at 0.184 per cent had drawn a weight
  of 0.02, which an optimiser correctly reads as "this curve does not matter",
  and it was free to rise to 0.667. The step shipped a card whose weighted
  score had improved 16.8 per cent and whose pooled error was 8.17 per cent
  worse than the card it started from, and the log reported success.

- `tcadopt/l1_spec/guard.py` -- `CurveGuard`, which refuses a card on a per
  curve basis rather than on a total, and `curve_pct` for reading one curve's
  error against its target.

- `tcadopt/l1_spec/achievable.py` -- `share_weights` and `apply_weights`, for
  the cases where a weighted objective is genuinely wanted, together with
  `live` and `capped` so a weight that cannot reach anything is visible.
  Documented with the warning above attached.

- `tcadopt/l1_spec/bias_pair.py` -- `pair`, `probe_row`, `need`, `verdict` and
  `channel_total`. Measures what a parameter does to two drain biases
  separately, so a knob that moves them in opposite directions can be found.
  On the finished device exactly one parameter in the charge model did that,
  and it turned out to be clamped.

- `tcadopt/l5_opt/price.py` -- `scan`, `ladder`, `absolute`, `pick` and
  `format_price`. Prices a parameter that two objectives disagree about
  instead of gating it. The shared saturation voltage on this device closes 80
  per cent of the high bias charge gap and costs 38 per cent of drain current
  error with all seventeen current parameters free to repair the damage. That
  is a refusal with a number attached, which a reader can disagree with and
  cannot dispute.

- `tcadopt/l6_verify/seed.py` -- `choose` and `ladder`. A derived seed is a
  candidate measured against the model's own default, and if it loses, the
  default goes on and the run carries on.

  A seed computed correctly from the bottom dielectric isolation plug's plate
  capacitance put the bias dependent Cgb ceiling at 3.04 attofarads on a
  device whose Cgb never exceeds 1.93, because the model multiplies that
  parameter by `NFINtotal * LeffCV`. The fit came out at 79.8 per cent, and
  the run exited instead of carrying on.

- `tcadopt/l4_knowledge/cgb_overlap.py` -- the gate to substrate charge in
  closed form, `presolve`, and `accumulation_risk`, which reports how much of
  a gate sweep sits below flatband and how large the model's dormant
  accumulation branch would be if it opened.

  A closed form solve promised Cgb could reach 1.39 per cent and the simulator
  measured 1262 per cent on the card it proposed. The arithmetic was right
  about its own term; there were two terms. BSIM-CMG puts the channel's
  accumulation charge on the body node, it is dormant while the channel is
  inverted, and the parameter the solve chose put 98 per cent of the sweep
  below flatband. That branch is worth up to 61 attofarads against a measured
  Cgb of 1.93.

- `tcadopt/l4_knowledge/overlap.py` -- the drain and source overlap charge in
  closed form, with `joint_presolve` for both sides at once because `vfbsdcv`
  is shared, and `structure_bound`, which caps an overlap length at what the
  spacer and the ungated channel allow.

- `tcadopt/l4_knowledge/depgraph.py` -- builds the dependency table from the
  model source and answers, per parameter, whether it can reach the drain
  current at a given set of switches. `verify` then measures the answer rather
  than trusting it.

- `tcadopt/l4_knowledge/depgraph_bsimcmg_112.json` and
  `depgraph_bsimcmg_112_bulk1.json` -- the dependency data the module above
  reads, one file for the BSIM-CMG 112 parameter set and one for the bulk
  model. These are data and not code, and `depgraph.py` does nothing without
  them, so they are tracked in the repository rather than generated. They are
  the only two non Python files this release adds to the package, which is why
  eighteen files land in `tcadopt/` and not the sixteen modules listed here.

- `tcadopt/l4_knowledge/structure.py` -- checks a card against the structure
  it is supposed to describe, including `implied_eps_hk` and `weff_geomod5`,
  and names the structural facts the model does not represent.

- `tcadopt/l4_knowledge/switch_scope.py` and `census.py` -- what a model
  switch newly makes live, and a census of which parameters move which curves.

- `tcadopt/l6_verify/determinacy.py` -- `coord_jacobian`, `determinacy`,
  `measured_interval` and `format_intervals`. An honest error bar per fitted
  parameter and a list of the pairs the data cannot tell apart.

  One parameter on the finished device was successively fitted to 0.0686, then
  9.02, then 0.617, then 2.865 across four steps, moving by factors of a
  hundred while the error changed by fractions of a per cent. It belongs in
  the card and it does not belong in a results table as though it had been
  measured.

- `tcadopt/l9_report/overlay.py` and `tradeoff.py` -- figure generation for
  model against reference, per curve error tables, and Pareto fronts.

- `tcadopt/l1_spec/fom_objective.py` -- figures of merit as residual terms, so
  threshold voltage, subthreshold slope and DIBL can be fitted alongside
  curves rather than only checked afterwards.

- Five new documents in the gate-all-around route, which is now fourteen pages
  and still reads in order:

  - `docs/GAA_THE_OBJECTIVE.md` -- the three different numbers that get called
    the error, which one to minimise, and why a stored weight is a trap.
  - `docs/GAA_THE_RULE.md` -- the acceptance rule, written before the run,
    with every threshold read off the baseline rather than chosen.
  - `docs/GAA_THE_JOINT_FIT.md` -- what a one at a time scan cannot find, the
    aligner's calling convention written out exactly, and how to read its
    convergence.
  - `docs/GAA_WHEN_TO_STOP.md` -- the ledger. Close every direction the card
    could still move in, each with a measurement, including how to find out
    whether a bound belongs to the model or to your own range.
  - `docs/GAA_CASE_STUDY_NFET.md` -- the whole extraction with real numbers,
    including the eight mistakes and what each one cost.

### Changed

Five engine files change rather than being added. Before any of them went in,
the import graph of the released 1.1.19 package was walked from every entry
point to measure what depends on them, rather than assuming it. The result:
`l8_orch/run_campaign.py` and `l8_orch/run_pareto.py`, the two entry points of
the design optimization path, reach twelve and eleven modules respectively, and
not one of these five is among them. The package `__init__.py` imports nothing
at all, so importing TCADOpt pulls in no submodule. Nothing on the design
optimization path can reach any of this code, which is why that path is
unaffected by it.

- `tcadopt/l6_verify/gate.py` grows from 26827 to 52383 bytes, and carries four
  of the six fixes listed below: the pooled objective replacing the per curve
  mean, weights no longer being stored between cards, the acceptance rule being
  applied to every candidate rather than only to fits, and a rejected stage
  reverting to the card it started from. Nothing in the package imports it. The
  staged scripts import it directly.

- `tcadopt/l5_opt/lm_align.py` grows from 37258 to 40204 bytes. It now
  minimises the pooled residual, and its starting sum of squares equals the
  point count times the pooled error squared, which is the self check that the
  aligner and the reported number are the same function. It takes the card
  dictionary as `params`, a list of names to free, and a dictionary of ranges
  keyed by name, and it returns a result dictionary with the card under
  `params`. That convention is documented in `docs/GAA_THE_JOINT_FIT.md`
  because getting it wrong costs a run.

- `tcadopt/l9_report/where.py` grows from 9917 to 16484 bytes, reporting signed
  error per band per curve, which is how the charge partition limit was located
  rather than guessed at.

- `tcadopt/l4_knowledge/cv_scope.py` grows from 10594 to 14156 bytes. It is the
  free zone, the parameters that cannot change the drain current, and it is the
  only one of these five that anything in the package imports: `gate.py` reads
  it.

- `tcadopt/l3_exec/hspice_parser.py` changes without changing size, 36739 bytes
  before and after. This is the module that reads the gate row out of the
  simulator's own operating point print, and that stitches back together the
  tables HSPICE splits when a print asks for more than four columns. Nothing on
  the design optimization path reads an HSPICE listing at all.

- `docs/GAA_CHARGE_PARTITION.md` now ends with the measurement that ends the
  extraction. At the top of each gate sweep the device gives the source 0.5077
  of the channel charge at the low drain bias and 0.6693 at the high one,
  which are the textbook values of one half and two thirds to within 0.008.
  BSIM-CMG gives 0.5459 and 0.6946 and no parameter on the card moves it.

  Hold the model's own total charge and give it the device's split and the
  worst curve goes from 14.18 per cent out to 6.96, so roughly half of the
  largest single error in the extraction is this. On the finished card that
  curve is 42 per cent of everything left, and Cgs at the high drain bias,
  where the same error lands instead because the drain end is pinched off, is
  another 19.

  The page also now documents the symptom that appears before the cause is
  understood. The fit breaks a symmetry the device has: `cgdl` and `cgsl`
  finished a factor of 2.55 apart on a device whose own overlap floors are 1.5
  per cent apart. Forcing them equal costs 23.55 per cent of pooled error, so
  the asymmetry is load bearing and not an artefact.

- `docs/GAA_TROUBLESHOOTING.md` gains six sections: a step that reports success
  while shipping a worse card, a card that entered the pipeline unguarded, a
  revert that went to the wrong card, a reproduce check where only the
  capacitance moved, a parameter that will not go below a round number, and
  the aligner refusing to run or running and appearing to do nothing.

- `docs/GAA_COMPACT_MODEL.md` route map renumbered to fourteen steps, with the
  two pages that decide what better means placed before the extraction order
  rather than after it.

- `check_docs.py` chain extended to all fifteen pages of the route.

### Fixed

- `check_docs.py` crashed on Python 2 instead of checking anything, and had
  done so since 1.1.19 while its own docstring claimed it ran on 2.7. Python
  2's `chr()` refuses any code point above 255, and the table of banned
  characters is built from sixteen code points above it, so the file raised
  `ValueError: chr() arg not in range(256)` while being read, before it
  checked a single document. The table is now built through a helper that
  spells the code point as an escape and lets the codec read it, which needs
  no version test at all and was verified to return characters identical to
  `chr()` for all seventeen entries. `tools/plain_text_md.py` had the same
  fault on the same kind of table and is fixed the same way, and its docstring
  no longer claims it needs Python 3.6.

- `check_docs.py` would also have crashed on the one path that only runs when
  it finds something, because it echoed the offending line, and a terminal
  that cannot print that character raises rather than prints. The snippet is
  now reduced to ASCII before it is reported, so a failure reports instead of
  raising.

- `check_setup.py` reported a Python as too old without mentioning that a new
  enough interpreter usually sits beside it under another name, which is the
  normal state of a simulator host. It now looks for `python3` and the
  versioned names, and if it finds one it prints its version and the exact
  command to use instead. It installs nothing and changes nothing.

- A guard that wrapped only the local fit. A ladder, a scan or a closed form
  solve can each produce a card, and on this project the ladder's pick fed the
  rest of the step without ever passing the guard. Its Cgd at the high drain
  bias was 262 per cent worse than the baseline on a guard that allows 10. The
  rule is now a function that every candidate passes, from every source.

- A revert that went to whatever the previous part left rather than to the card
  the step started with. When a later part was correctly refused, the revert
  put the unguarded pick back, and three subsequent parts each reported a
  sensible improvement measured against a card that had already regressed.

- A baseline identified by the name of a constant. `CARDnn` in the extraction
  scripts means the card step nn started from, not the card it produced, and a
  step loaded one seven versions too old. The repair is to simulate every
  candidate baseline and keep the one that matches the numbers the earlier log
  printed, which is now printed as a table at the start of a run.

- An explicit value written for a parameter whose declared default is a
  reference to another parameter. `vfbsdcv` defaults to `vfbsd`, declared 0.0,
  but the model assigns `vfbsdcv_v = vfbsd_v`, a computed variable holding the
  flatband voltage of the source and drain, about +0.43 V on this device.
  Writing 0.0 moved the capacitance from 0.026916 to 0.075682 while the drain
  current did not move at all.

- `sys.exit` reachable from a measurement. A probe pushes a parameter to the
  end of its range on purpose, and some of those cards make the simulator fail
  to converge or the model reject the card. Both are results. One run of two
  and a half hours was lost to treating them as accidents. Runs now count
  their own exits and print the count before anything is simulated.

- A per curve acceptance threshold chosen by hand. An earlier draft capped the
  rise in any curve at 0.35 attofarads, a number with no derivation, and the
  best card available asked for 0.3232. It passed by five thousandths of an
  attofarad. Both caps are now read off the baseline card, so the rule reads
  "no curve may end up worse than the worst curve already was".

### Known limits, measured

- BSIM-CMG 112.1.0 has no charge partition parameter. BSIM4 and BSIM-BULK
  expose this as XPART, documented in the BSIM4 manual chapter 7 section
  7.2.4. This is about 40 per cent of the error left on the finished card and
  no amount of fitting reaches it.

- `ckappad`, `ckappas` and `ckappab` are clamped by the model at 0.02. Twelve
  cards at 0.01, 0.005, 0.001 and 1e-5 returned curves identical to the 0.02
  card to 0.0000e+00 attofarads. `ckappad` was the only parameter in the
  charge model whose two drain biases move in opposite directions, which was
  the shape of the remaining error, so this clamp is the limit that closed the
  search.

- The capacitance side is still driven by staged scripts rather than by one
  problem file. The current side runs end to end.

- The p-type card is extracted by running the whole thing again. There is no
  shared n and p extraction yet.

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

The optimizer itself is untouched. The Gaussian process surrogate, the
trust region schedule, the acquisition functions, both backends, the physics
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
