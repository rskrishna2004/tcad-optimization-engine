# Architecture

TCADOpt is a layered pipeline. Each layer is a Python package under `tcadopt/` with a single responsibility, and data flows from one layer to the next. This document explains what each layer does and how a single optimization campaign moves through them.

---

## The big picture

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

The whole loop is driven by the orchestration layer `l8_orch`.

---

## The layers

### l1_spec — the specification layer
Reads the problem YAML and turns it into two objects the rest of the engine uses:
- a **parameter space** that knows each tunable parameter, its range, and whether it is searched on a linear or logarithmic scale, and that can encode a design to a normalized vector and decode it back;
- a **scorer** that turns a set of simulated metrics into a single number to maximize, honoring the objective, any hard caps, floors, or target values.

Key modules: `compile.py` (builds everything from the YAML), `paramspace.py` (the parameter space), `scorer.py` (the scoring functions, including the Pareto scorer), `metrics.py` (metric extraction helpers).

### l2_decks — the deck layer
Turns a candidate design into a concrete simulator input. This is the seam where the engine meets your simulator. The engine ships the interface; you provide the template deck and the small rendering logic for your specific device. See `docs/CONNECTING_A_SIMULATOR.md`.

### l3_exec — the execution layer
Runs the simulator on a batch of candidate designs in parallel, then parses the electrical output files into a dictionary of metrics. It is built to never let one failed simulation crash a batch: failures are caught, classified, and reported so the campaign keeps moving.

Key modules: `execute.py` (the batch evaluator), `failures.py` (failure classification), `metrics.py` (result parsing).

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
Certifies a design against fidelity checks: does the result hold up on a finer mesh, are the physics models self-consistent, are all constraints satisfied. Used to confirm that a champion is trustworthy and not a numerical artifact of a coarse mesh.

Key module: `certify.py`.

### l7_memory — the memory layer
Stores every simulation ever run in a local database: the design, the encoded vector, the metrics, the score, and metadata. Nothing is lost, nothing is repeated, and a campaign can be analyzed or resumed later. It also holds warm-start seeds.

Key modules: `experiment_db.py` (the database), `seeds.py` (seed management).

### l8_orch — the orchestration layer
Runs a complete campaign end to end: seeding, initial sampling, the round-by-round optimization loop, trust-region restarts, and the final champion selection with a convergence-evidence report. It also runs a Pareto front tracer for multi-objective problems.

Key modules: `run_campaign.py` (single-objective or capped campaign), `run_pareto.py` (multi-objective Pareto front).

### l9_report — the reporting layer
Produces the champion defense dossier: reproducibility, robustness under small perturbations, consistency with the surrogate, constraint margins, physics compliance, and dominance statistics, ending in a trust verdict.

The defense logic is in `tools/defend_champion.py`.

---

## A note on where some files live

For historical reasons a few core modules live in a top-level `optimizer/` folder rather than inside the `tcadopt/` package tree: the Gaussian process surrogate (`gp.py`), the parallel dispatcher (`dispatch.py`), the simulator runner (`runner.py`), the parameter space used by the standalone tools (`space.py`), and the plot parser (`plt_parser.py`). The engine imports them from there. If you reorganize, update the import paths accordingly. This is documented so the layout is not surprising.

---

## Design principles

- **One YAML describes a problem.** Optimizing a new device needs no engine code changes, only a new problem file and a simulator adapter.
- **Never trust an unchecked number.** Every result passes the physics guard; every champion is defended with evidence.
- **Never crash a campaign.** Failures are caught and classified; the loop keeps running and the best result so far is always safe in the database.
- **Learn from every simulation.** The surrogate uses all valid data; the memory layer keeps everything.
