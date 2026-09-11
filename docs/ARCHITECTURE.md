# Architecture

TCADOpt is a layered pipeline. Each layer is a Python package under `tcadopt/` with a single responsibility, and data flows from one layer to the next. This document explains what each layer does and how a campaign moves through them.

Since v1.1.0 there are **two** campaigns that move through the same layers: a design optimization and a parameter extraction. They differ in three places and share everything else. Both pictures are below, and the point of showing them together is that the difference really is only three boxes.

---

## The big picture: design optimization

```
        your problem.yaml
               |
        [ l1_spec ]   read problem, build parameter space + scorer
               |
        [ l4_knowledge ]  seed the search with device physics
               |
   +---->  [ l5_opt ]  propose the next batch of candidate designs
   |           |
   |    [ l2_decks + l3_exec ]  render each candidate into a simulator
   |           |                deck, run the simulator in parallel,
   |           |                parse the electrical metrics
   |           |
   |    [ l4_knowledge ]  physics guard: quarantine unphysical results
   |           |
   |    [ l1_spec ]  score each result
   |           |
   |    [ l7_memory ]  store every trial in the database
   |           |
   +-----------+  repeat for several rounds (trust region adapts)
               |
        [ l6_verify ]  certify the champion against fidelity checks
               |
        [ l9_report ]  produce the champion defense dossier
```

The whole loop is driven by the orchestration layer `l8_orch`
(`run_campaign.py`).

## The big picture: parameter extraction

```
   your fit.yaml + targets/*.csv
               |
        [ l3_exec ]   load the reference curves, drop rows the data
               |      itself flags as unusable
               |
        [ l1_spec ]   build the parameter space for THIS STAGE and the
               |      curve-residual scorer over THIS STAGE's sweeps
               |
   +---->  [ l5_opt ]  propose the next batch of parameter sets
   |           |
   |    [ l2_decks ]  render each candidate into a BSIM-CMG model card
   |           |      and one circuit-simulator deck per target sweep
   |           |
   |    [ l3_exec ]  run the circuit simulator in parallel, parse each
   |           |      listing into a curve
   |           |
   |    [ l1_spec ]  score: residual against the reference curve at
   |           |      every bias point
   |           |
   |    [ l7_memory ]  store every attempt in the database
   |           |
   +-----------+  repeat for several rounds (same trust region)
               |
        freeze this stage's parameters -> results/frozen_<spec>.json
               |
        next stage, with everything above held fixed
               |
        [ l6_verify ]  measure identifiability of the extracted set
```

Driven by `l8_orch/run_fit.py`.

## What actually differs

Three things, and only three:

| | Design optimization | Parameter extraction |
|---|---|---|
| **The objective** | `CappedScalarScorer` — a weighted sum over scalar figures of merit, with caps and floors | `CurveResidualScorer` — the residual at every bias point of every target curve |
| **The evaluator** | `TCADEvaluator` — structure tool, then device tool, then parse a DF-ISE `.plt` | `HSpiceEvaluator` — one tool, parse a SPICE listing |
| **The loop shape** | one campaign per cap value | one campaign per stage, with earlier stages frozen |

Everything else — the parameter space, the Gaussian-process surrogate, the
trust-region schedule, the acquisition function, the experiment database, the
convergence-evidence reporting — is the same code running unmodified. That is
not a coincidence; the layer boundaries were drawn so that swapping the
objective and the evaluator would be enough, and the extraction path is the
first time that claim has been tested by something other than a TCAD tool.

---

## The layers

### l1_spec — the specification layer
Reads the problem YAML and turns it into two objects the rest of the engine uses:
- a **parameter space** that knows each tunable parameter, its range, and whether it is searched on a linear or logarithmic scale, and that can encode a design to a normalized vector and decode it back;
- a **scorer** that turns a set of simulated metrics into a single number to maximize, honoring the objective, any hard caps, floors, or target values.

Key modules: `compile.py` (builds everything from the YAML), `paramspace.py` (the parameter space), `scorer.py` (the scoring functions, including the Pareto scorer), `metrics.py` (metric extraction helpers), `curve_scorer.py` (the curve-residual objective used by extraction).

`curve_scorer.py` is worth a note because it is the one genuinely new idea in v1.1.0. Every other scorer reduces a simulation to scalars and combines them; this one keeps the whole curve. It splits the residual at a current threshold and reports two numbers — sub-threshold error in decades, on-state error as a fraction — because drain current spans about eight decades and a single error measure is dominated by whichever end has the larger numbers. Keeping them separate also means that when a fit stalls, the two numbers say which half stalled.

### l2_decks — the deck layer
Turns a candidate into a concrete simulator input. This is the seam where the engine meets your simulator.

For **design optimization** the engine ships the interface; you provide the template deck and the small rendering logic for your specific device, because structure decks are vendor files. See `docs/CONNECTING_A_SIMULATOR.md`.

For **extraction** the layer is implemented, in `cardgen.py`: a compact model card is a standardised text format, so there is nothing device-specific to leave to the user. It renders a candidate into a BSIM-CMG `.model` statement and writes the circuit-simulator decks that exercise it. Two things it enforces rather than trusting the caller with: `VERSION` is always written (LEVEL 72 defaults to a revision with no gate-all-around module, so `GEOMOD=5` is rejected without it), and the first line of every deck is a comment line meant to be the title, because a netlist's first line is the title whatever it contains.

### l3_exec — the execution layer
Runs the simulator on a batch of candidate designs in parallel, then parses the electrical output files into a dictionary of metrics. It is built to never let one failed simulation crash a batch: failures are caught, classified, and reported so the campaign keeps moving.

Key modules: `execute.py` (the TCAD batch evaluator), `spice_exec.py` (the circuit-simulator batch evaluator), `failures.py` (failure classification), `metrics.py` (result parsing), `hspice_parser.py` (reading SPICE listings), `targets.py` (loading reference curves).

`spice_exec.py` exists rather than a flag on `execute.py` because the existing runner requires two steps and abandons a run whose mesh file never appears. A circuit simulator has no mesh, so that check can never pass, and weakening it would weaken a code path the TCAD side depends on. The two evaluators present the identical `evaluate_batch(param_dicts, tag)` interface, which is what lets the rest of the engine not care which one is running.

`hspice_parser.py` reads the `.print` tables inside a `.lis` listing rather than the `.sw0` sweep file. That is deliberate: a printed table carries its own column headers, so the parser learns the layout from the file, where a `.sw0` is a fixed-field vendor format whose layout would have to be assumed. It handles both scientific and SPICE engineering-suffix numbers, and stitches a sweep split across printed pages back into one block.

### l4_knowledge — the physics knowledge layer
Two jobs:
- **Seeding.** Before random sampling, it pushes the tunable parameters in the directions that device physics says will improve the objective, giving the surrogate a few high-value starting points. It is device-agnostic: it maps parameter roles across device families, so the same physics rules apply whether the device is a planar MOSFET or a nanowire.
- **Guarding.** After every simulation, it checks the result against a set of physical invariants (for example, the subthreshold slope cannot be steeper than the room-temperature thermodynamic limit, on-current must exceed off-current, transconductance must be positive). A result that violates an invariant is flagged and excluded from the surrogate, so the model never learns from a solver artifact or a parsing error.

Key module: `physics_guard.py`. The rules themselves live in a human-readable knowledge file described in `docs/PHYSICS_KNOWLEDGE.md`.

### l5_opt — the optimizer core
The Bayesian optimization brain. It fits a Gaussian process surrogate to all valid simulations so far, then chooses the next batch of designs by maximizing an acquisition function that trades off predicted value against uncertainty. It runs inside a trust region that shrinks when progress stalls and restarts from unexplored regions when the region collapses, which protects against getting stuck in a local optimum. It supports feasibility-aware search, so for capped problems it models where the cap is likely to be violated and avoids wasting simulations there.

Key module: `optimizer.py` (the trust-region schedule, the backend selector, and the optimizer facade). The default backend's surrogate is in `gp.py` (see note on file locations below).

The backend is swappable behind `Optimizer`. `ScipyGPBackend` is the default and needs only numpy and scipy. `BoTorchBackend` (`botorch_backend.py`) is optional and needs Python 3.11+; it replaces the acquisition and the acquisition search while keeping the same trust-region schedule. Both implement the same `propose` / `exhausted` / `force_restart` interface, so the orchestrator is unchanged either way. See `docs/OPTIMIZER_BACKENDS.md`.

### l6_verify — the verification layer
Refuses to trust a result until something other than the score that produced it has checked it.

For a **design champion** that means fidelity: does the result hold up on a finer mesh, are the physics models self-consistent, are all constraints satisfied. `certify.py`.

For an **extracted parameter set** it means identifiability: could this data have determined these numbers at all? `identifiability.py` perturbs each free parameter around the extracted point, builds the Jacobian of the residual, and reports per-parameter sensitivity, pairwise collinearity, and the effective rank against the number of free parameters. This is a separate measurement rather than a property of the fit because a degenerate fit *fits perfectly* — the failure is invisible in the error.

Key modules: `certify.py`, `identifiability.py`.

### l7_memory — the memory layer
Stores every simulation ever run in a local database: the design, the encoded vector, the metrics, the score, and metadata. Nothing is lost, nothing is repeated, and a campaign can be analyzed or resumed later. It also holds warm-start seeds.

Key modules: `experiment_db.py` (the database), `seeds.py` (seed management).

### l8_orch — the orchestration layer
Runs a complete campaign end to end: seeding, initial sampling, the round-by-round optimization loop, trust-region restarts, and the final champion selection with a convergence-evidence report. It also runs a Pareto front tracer for multi-objective problems.

It also runs staged parameter extraction: each stage is a full campaign over its own free parameters and its own target sweeps, with everything already extracted held frozen and persisted between stages, so a stage can be re-run alone. A stage that fails to converge freezes nothing, because a bad stage must not contaminate the next.

Key modules: `run_campaign.py` (single-objective or capped campaign), `run_pareto.py` (multi-objective Pareto front), `run_fit.py` (staged extraction).

### l9_report — the reporting layer
Produces the champion defense dossier: reproducibility, robustness under small perturbations, consistency with the surrogate, constraint margins, physics compliance, and dominance statistics, ending in a trust verdict.

The defense logic is in `tools/defend_champion.py`.

---

## A note on where some files live

For historical reasons a few core modules live in a top-level `optimizer/` folder rather than inside the `tcadopt/` package tree: the Gaussian process surrogate (`gp.py`), the parallel dispatcher (`dispatch.py`), the simulator runner (`runner.py`), the parameter space used by the standalone tools (`space.py`), and the plot parser (`plt_parser.py`). The engine imports them from there. If you reorganize, update the import paths accordingly. This is documented so the layout is not surprising.

---

## Design principles

- **One YAML describes a problem.** Optimizing a new device, or extracting a new model, needs no engine code changes — only a new problem file and a simulator adapter.
- **One core, two jobs.** The surrogate, the trust region and the memory do not know whether they are searching a geometry or a parameter set. Adding extraction meant adding an objective and an evaluator, not forking the engine.
- **Never trust an unchecked number.** Every result passes the physics guard; every champion is defended with evidence.
- **Never crash a campaign.** Failures are caught and classified; the loop keeps running and the best result so far is always safe in the database.
- **Learn from every simulation.** The surrogate uses all valid data; the memory layer keeps everything.
