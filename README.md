# TCADOpt

**A physics-aware Bayesian optimization engine for semiconductor device simulation, and a compact-model parameter extraction engine.**

TCADOpt does two things with one optimizer core.

**Design optimization.** It drives a TCAD device simulator to automatically discover device designs with the best possible electrical characteristics. You describe the device and the targets in a small YAML file, point the engine at your simulator, and run one command. It then runs an unattended campaign of **many simulations in parallel**, learning from every result to steer the search, guarding against unphysical results, and returning an optimized champion with confidence evidence.

**Parameter extraction.** It fits a compact model's parameters to reference curves from a device you have already simulated, so the model reproduces that device inside a circuit simulator. It fits the **whole curve** rather than a handful of figures of merit, extracts in stages with earlier results frozen so each parameter keeps its physical meaning, and then measures whether the data could determine those parameters at all.

Both paths are vendor-independent: the engine drives whatever tools you configure.

---

> **New here?** Pick the guide for what you are doing:
> - optimizing a device's design, go to **[docs/WORKFLOW.md](docs/WORKFLOW.md)**
> - extracting compact-model parameters, go to **[docs/PARAMETER_EXTRACTION.md](docs/PARAMETER_EXTRACTION.md)**
> - making a compact model for a **gate-all-around** device, go to **[docs/GAA_COMPACT_MODEL.md](docs/GAA_COMPACT_MODEL.md)**
>
> A full documentation map is in **[docs/README.md](docs/README.md)**.

It was built and hardened during a competitive TCAD device optimization challenge, and it encodes a large amount of hard-won practical knowledge about how to make an automated device-optimization loop actually work.

---

## Why this exists

Optimizing a modern transistor means choosing many coupled parameters (doping levels, junction placements, geometry) so that several competing metrics (on-current, off-current leakage, transconductance, subthreshold behavior) all land in a good place at once. Doing this by hand is slow, and a brute-force grid search is impossible because the space is far too large and every point costs a full physics simulation that can take minutes.

Extracting compact-model parameters is the same shape of problem wearing different clothes. There the design is fixed and the unknowns are the model's parameters; the expensive evaluation is a circuit simulation instead of a device simulation; and "better" means the model's curve lies on top of the measured curve rather than the device being fast. The search machinery is identical, which is why one engine does both.

TCADOpt solves this the way a state-of-the-art optimizer should:

- It builds a **surrogate model** of the design space from the simulations it has already run, so it can predict where good designs are likely to be before spending a simulation there.
- It uses **Bayesian optimization** with a trust region, so it balances exploiting known-good regions against exploring the unknown, and it restarts intelligently when it gets stuck.
- It seeds the search using **device physics knowledge**, so it starts in promising regions instead of at random.
- It runs a **physics guard** on every result, so a simulation that violates a physical law (for example, a subthreshold slope steeper than the thermodynamic limit) is quarantined and never poisons the model.
- It **defends every champion** with reproducibility, robustness, and consistency checks, so a reported "best design" comes with evidence, not just a number.
- For extraction it **measures identifiability**, so a reported parameter value comes with an answer to "could this data have determined that number at all?". The fit error cannot answer that, because a degenerate fit fits perfectly.
- For extraction it **proves which parameters cannot affect which measurement**, from the model source and then by measurement, so a whole family can be fitted with the rest of the model held exactly fixed.
- For extraction it **prices a shared parameter** rather than refusing to move it, so a trade-off between two objectives becomes a table a person can choose from instead of a rejected stage.

---

## Key features

- **Describe-and-run.** One YAML file per problem defines the parameters, their fabricable ranges, the objective, and the constraints. No code changes needed to optimize a new device.
- **Multiple objective modes.** Maximize a metric, minimize another, hit a target value, enforce a hard cap, or trace a full multi-objective Pareto front.
- **Parallel simulation batches.** The engine dispatches many simulations at once to use your compute fully.
- **Device-agnostic.** Planar MOSFET, FinFET, gate-all-around nanosheet and nanowire, and more. The engine does not care what the device is; it optimizes whatever simulation deck you connect.
- **Physics knowledge base.** A human-readable file of device-physics rules that the engine uses both to seed the search and to audit results.
- **Champion defense dossier.** A structured, evidence-backed report on why the winning design deserves trust.
- **Whole-curve fitting.** For extraction, the objective is the residual over every bias point, split into a sub-threshold error in decades and an on-state error as a fraction, so both ends of an eight-decade current range are actually being fitted.
- **Staged extraction with freezing.** Parameters are extracted in the bias region where each dominates, with everything already extracted held fixed, so the result is an extraction rather than a curve fit.
- **The full gate row of capacitances.** Cgd, Cgs, Cgb and their sum, read out of the circuit simulator's own operating point with no extra simulation, so a charge-partition error cannot hide inside the total.
- **Scope proof and the frozen gate.** The parameters that provably cannot affect the drain current are listed with the model source line for each, verified by measurement on your own installation, and fitted behind a gate that requires every current sweep to stay bit-identical.
- **Trade curves for shared parameters.** When two objectives want different values of the same parameter, the engine freezes it at each of a ladder of values, completely re-fits the other objective at each one, and reports the measured price. A gate cannot answer that question; a trade curve can.
- **Identifiability measurement.** Which extracted numbers are measurements, which pairs are indistinguishable, and how many independent directions the data really contains.

---

## How it fits together

TCADOpt is organized as a layered pipeline. Each layer has one clear job, and results flow from one to the next.

| Layer | Job |
|-------|-----|
| Spec | Read the YAML problem, build the parameter space and the scoring function |
| Decks | Turn a candidate design into a simulator input (the part you connect to your simulator) |
| Exec | Run the simulator in parallel batches and parse the electrical results |
| Knowledge | Check every result against device-physics laws; seed the search with physics; hold what is known about which parameter can affect what |
| Optimizer | The Bayesian optimization core: surrogate model, trust region, acquisition (two swappable backends, see [docs/OPTIMIZER_BACKENDS.md](docs/OPTIMIZER_BACKENDS.md)), plus the local aligner and the trade-curve pricer |
| Verify | Certify a design against fidelity checks (mesh, models, constraints); measure identifiability; gate every extraction stage |
| Memory | Store every simulation in a database so nothing is ever lost or repeated |
| Orchestration | Run a full campaign, a Pareto front, or a staged extraction from start to finish |
| Report | Produce the champion defense dossier, the gate-row comparison, and the per-band error report |

The extraction path reuses the same layers: `l1_spec` builds the parameter space and the curve-residual scorer, `l2_decks` renders the model card and the circuit-simulator decks, `l3_exec` runs them and reads the listings, `l4_knowledge` holds the scope table, `l5_opt` proposes the next candidates and runs the local alignment, `l6_verify` measures identifiability and gates each stage, `l7_memory` stores every attempt, `l8_orch` runs the staged campaign, and `l9_report` puts the model beside the device.

A full explanation of every layer is in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Important: you need a TCAD simulator

TCADOpt is the **optimization brain**, not the simulator. To optimize real devices you connect it to a TCAD simulator of your choice. The engine is **simulator-agnostic**: it invokes two configurable commands, a structure/mesh builder and an electrical device solver, which you point at whatever tools you use. **No simulator files, vendor decks, or vendor documentation are included in this repository**, both for licensing reasons and to keep the engine independent of any one vendor. Instead, [`docs/CONNECTING_A_SIMULATOR.md`](docs/CONNECTING_A_SIMULATOR.md) explains exactly how to write the small adapter that lets the engine drive your simulator.

For extraction you connect a **circuit simulator** instead (PrimeSim HSPICE is what the reference implementation drives, via `TCADOPT_SPICE_TOOL`). Reading an HSPICE listing is built in; other simulators need a small parser, described in [`docs/PARAMETER_EXTRACTION.md`](docs/PARAMETER_EXTRACTION.md).

**You can try both paths with no simulator at all.** [`examples/synthetic_demo`](examples/synthetic_demo) runs the full optimizer against a fast synthetic math function that stands in for a device simulator, and [`examples/extraction_demo`](examples/extraction_demo) runs the full staged extraction against a stand-in transistor with a known answer, so you can watch either pipeline work on any computer in seconds.

---

## Quick start

```bash
# 1. clone and install
git clone https://github.com/rskrishna2004/tcad-optimization-engine.git
cd tcad-optimization-engine
pip install -r requirements.txt
python check_setup.py            # confirms Python + dependencies are ready
```

Then the real workflow, on your own simulators.

**To optimize a device's design:**

```bash
# 2. tell the engine which TCAD tools to run (once)
export TCADOPT_STRUCTURE_TOOL="your_structure_tool"   # builds structure + mesh
export TCADOPT_DEVICE_TOOL="your_device_tool"         # runs the electrical sim

# 3. optimize: engine runs many parallel simulations, unattended
python -m tcadopt.l8_orch.run_campaign problems/your_problem.yaml
```

**To extract compact-model parameters:**

```bash
# 2. tell the engine which circuit simulator to run (once)
export TCADOPT_SPICE_TOOL="hspice"

# 3. extract: engine runs the stages in order, freezing as it goes
python -m tcadopt.l8_orch.run_fit problems/your_fit.yaml
```

The engine runs the whole campaign on its own and prints an optimized champion design, or an extracted parameter set with its per-stage errors. **Read [docs/WORKFLOW.md](docs/WORKFLOW.md)** for design optimization and **[docs/PARAMETER_EXTRACTION.md](docs/PARAMETER_EXTRACTION.md)** for extraction. Each walks through every step: connecting your simulator, writing the problem file, running, monitoring, and collecting results.

If your device is a gate-all-around nanosheet or nanowire, **[docs/GAA_COMPACT_MODEL.md](docs/GAA_COMPACT_MODEL.md)** is a route built for that case specifically, from the TCAD runs you need through to what a finished card looks like.

### Verifying your install without a simulator

If you do not have a TCAD simulator on this machine and just want to confirm the optimizer itself installed correctly, there is a tiny self-check that runs the optimization loop against a stand-in math function (it does **not** simulate any device; it only proves the engine imports and runs):

```bash
python examples/synthetic_demo/run_demo.py       # the design-optimization path
python examples/extraction_demo/run_demo.py      # the extraction path
```

These are install sanity checks only. The engine's actual purpose is driving your own simulators, described in [docs/WORKFLOW.md](docs/WORKFLOW.md) and [docs/PARAMETER_EXTRACTION.md](docs/PARAMETER_EXTRACTION.md).

---

## Documentation

Read them roughly in this order:

- [Getting started](docs/GETTING_STARTED.md) - install and verify your environment. **Start here** whichever path you are on.
- **[Workflow](docs/WORKFLOW.md)** - design optimization, start to finish: problem file in, one command, parallel simulations, optimized device out.
- **[Parameter extraction](docs/PARAMETER_EXTRACTION.md)** - extraction, start to finish: reference curves in, staged fit, extracted model card out.
- **[A compact model for a GAA device](docs/GAA_COMPACT_MODEL.md)** - the route map for nanosheet and nanowire devices, and the head of a nine-page chain that covers the whole job.
- [Extraction tutorial](docs/EXTRACTION_TUTORIAL.md) - your first extraction, one command at a time, with what every printed line means
- [Connecting a simulator](docs/CONNECTING_A_SIMULATOR.md) - point the engine at your tools, TCAD or circuit (do this once)
- [Writing a problem file](docs/WRITING_A_PROBLEM.md) - the YAML format for both kinds of problem, every field explained
- [Tuning](docs/TUNING.md) - how to set parallelism and budget for your machine and your problem
- [Architecture](docs/ARCHITECTURE.md) - how every layer of the engine works, and how one core serves two jobs
- [Optimizer backends](docs/OPTIMIZER_BACKENDS.md) - the default backend vs the optional BoTorch backend, and when to use which
- [The physics knowledge base](docs/PHYSICS_KNOWLEDGE.md) - how physics seeding and the guard work
- [Case study](docs/CASE_STUDY.md) - a real nanowire optimization, including the lessons learned

---

## Optional: the high-power optimizer backend

The optimization core has two interchangeable backends. The default needs only
numpy and scipy and runs on Python 3.6, which matters because TCAD solver hosts
are often locked to an old interpreter. An optional backend built on
[BoTorch](https://github.com/meta-pytorch/botorch) uses a log-space acquisition
and gradient-based acquisition optimization, and is selected automatically when
its dependencies are present:

```bash
pip install -r requirements-botorch.txt    # needs Python 3.11+
```

No BoTorch source is copied into this repository; it is called as a dependency.
See [`NOTICE`](NOTICE) for attribution and [`docs/OPTIMIZER_BACKENDS.md`](docs/OPTIMIZER_BACKENDS.md)
for what changes and the measured comparison.

---

## Project status

This is **version 1.1.19**. The engine is functional and has been used on real device optimization campaigns. The extraction path is being hardened on a real 4-sheet gate-all-around nanosheet nFET against Sentaurus TCAD reference data, and every release since 1.1.0 has come out of something that extraction found. See [`CHANGELOG.md`](CHANGELOG.md).

What works today, and what does not, is stated plainly at the end of [`docs/GAA_COMPACT_MODEL.md`](docs/GAA_COMPACT_MODEL.md). The short version is that the current side runs end to end from one problem file, and the charge side is still driven by staged scripts while the method is being settled. It is under active development.

Feedback, issues, and contributions are welcome. See [`CONTRIBUTING.md`](CONTRIBUTING.md).

---

## License

Released under the MIT License. See [`LICENSE`](LICENSE). You are free to use, modify, and build on this, including commercially, as long as you keep the copyright notice.

Third-party components used by the optional optimizer backend are credited in [`NOTICE`](NOTICE).

---

## Citation

If this engine helps your work, a citation or a link back is appreciated:

```
R. Sri Krishna, "TCADOpt: A physics-aware Bayesian optimization and compact-model
extraction engine for semiconductor device simulation," 2026. https://github.com/rskrishna2004/tcad-optimization-engine
```
