# TCADOpt

**A physics-aware Bayesian optimization engine for semiconductor device simulation.**

TCADOpt drives a TCAD device simulator to automatically discover device designs with the best possible electrical characteristics. You describe the device and the targets in a small YAML file, point the engine at your simulator, and run one command. It then runs an unattended campaign of **many simulations in parallel**, learning from every result to steer the search, guarding against unphysical results, and returning an optimized champion with confidence evidence. It is vendor-independent: it drives whatever TCAD tools you configure.

---

> **New here?** Read **[docs/WORKFLOW.md](docs/WORKFLOW.md)** — it is the complete, step-by-step guide from a problem file to an optimized device. Everything else supports it. A full documentation map is in **[docs/README.md](docs/README.md)**.


It was built and hardened during a competitive TCAD device optimization challenge, and it encodes a large amount of hard-won practical knowledge about how to make an automated device-optimization loop actually work.

---

## Why this exists

Optimizing a modern transistor means choosing many coupled parameters (doping levels, junction placements, geometry) so that several competing metrics (on-current, off-current leakage, transconductance, subthreshold behavior) all land in a good place at once. Doing this by hand is slow, and a brute-force grid search is impossible because the space is far too large and every point costs a full physics simulation that can take minutes.

TCADOpt solves this the way a state-of-the-art optimizer should:

- It builds a **surrogate model** of the design space from the simulations it has already run, so it can predict where good designs are likely to be before spending a simulation there.
- It uses **Bayesian optimization** with a trust region, so it balances exploiting known-good regions against exploring the unknown, and it restarts intelligently when it gets stuck.
- It seeds the search using **device physics knowledge**, so it starts in promising regions instead of at random.
- It runs a **physics guard** on every result, so a simulation that violates a physical law (for example, a subthreshold slope steeper than the thermodynamic limit) is quarantined and never poisons the model.
- It **defends every champion** with reproducibility, robustness, and consistency checks, so a reported "best design" comes with evidence, not just a number.

---

## Key features

- **Describe-and-run.** One YAML file per problem defines the parameters, their fabricable ranges, the objective, and the constraints. No code changes needed to optimize a new device.
- **Multiple objective modes.** Maximize a metric, minimize another, hit a target value, enforce a hard cap, or trace a full multi-objective Pareto front.
- **Parallel simulation batches.** The engine dispatches many simulations at once to use your compute fully.
- **Device-agnostic.** Planar MOSFET, FinFET, gate-all-around nanowire, and more. The engine does not care what the device is; it optimizes whatever simulation deck you connect.
- **Physics knowledge base.** A human-readable file of device-physics rules that the engine uses both to seed the search and to audit results.
- **Champion defense dossier.** A structured, evidence-backed report on why the winning design deserves trust.

---

## How it fits together

TCADOpt is organized as a layered pipeline. Each layer has one clear job, and results flow from one to the next.

| Layer | Job |
|-------|-----|
| Spec | Read the YAML problem, build the parameter space and the scoring function |
| Decks | Turn a candidate design into a simulator input (the part you connect to your simulator) |
| Exec | Run the simulator in parallel batches and parse the electrical results |
| Knowledge | Check every result against device-physics laws; seed the search with physics |
| Optimizer | The Bayesian optimization core: surrogate model, trust region, acquisition (two swappable backends, see [docs/OPTIMIZER_BACKENDS.md](docs/OPTIMIZER_BACKENDS.md)) |
| Verify | Certify a design against fidelity checks (mesh, models, constraints) |
| Memory | Store every simulation in a database so nothing is ever lost or repeated |
| Orchestration | Run a full campaign or a Pareto front from start to finish |
| Report | Produce the champion defense dossier |

A full explanation of every layer is in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Important: you need a TCAD simulator

TCADOpt is the **optimization brain**, not the simulator. To optimize real devices you connect it to a TCAD simulator of your choice. The engine is **simulator-agnostic**: it invokes two configurable commands, a structure/mesh builder and an electrical device solver, which you point at whatever tools you use. **No simulator files, vendor decks, or vendor documentation are included in this repository**, both for licensing reasons and to keep the engine independent of any one vendor. Instead, [`docs/CONNECTING_A_SIMULATOR.md`](docs/CONNECTING_A_SIMULATOR.md) explains exactly how to write the small adapter that lets the engine drive your simulator.

**You can try the engine with no simulator at all.** The [`examples/synthetic_demo`](examples/synthetic_demo) folder runs the full optimizer against a fast synthetic math function that stands in for a simulator, so you can watch the whole pipeline work on any computer in seconds.

---

## Quick start

```bash
# 1. clone and install
git clone https://github.com/rskrishna2004/tcad-optimization-engine.git
cd tcad-optimization-engine
pip install -r requirements.txt
python check_setup.py            # confirms Python + dependencies are ready
```

Then the real workflow, on your own TCAD simulator:

```bash
# 2. tell the engine which TCAD tools to run (once)
export TCADOPT_STRUCTURE_TOOL="your_structure_tool"   # builds structure + mesh
export TCADOPT_DEVICE_TOOL="your_device_tool"         # runs the electrical sim

# 3. optimize: engine runs many parallel simulations, unattended
python -m tcadopt.l8_orch.run_campaign problems/your_problem.yaml
```

The engine runs the whole simulation campaign on its own and prints an optimized champion design. **Read [docs/WORKFLOW.md](docs/WORKFLOW.md) first** — it walks through every step: connecting your simulator, writing the problem file, running, monitoring, and collecting results.

### Verifying your install without a simulator

If you do not have a TCAD simulator on this machine and just want to confirm the optimizer itself installed correctly, there is a tiny self-check that runs the optimization loop against a stand-in math function (it does **not** simulate any device; it only proves the engine imports and runs):

```bash
python examples/synthetic_demo/run_demo.py
```

This is an install sanity check only. The engine's actual purpose is driving your TCAD simulator, described in [docs/WORKFLOW.md](docs/WORKFLOW.md).

---

## Documentation

Read them roughly in this order:

- **[Workflow](docs/WORKFLOW.md)** — the complete start-to-finish guide: problem file in, one command, parallel simulations, optimized device out. **Start here.**
- [Getting started](docs/GETTING_STARTED.md) — install and verify your environment
- [Connecting a simulator](docs/CONNECTING_A_SIMULATOR.md) — point the engine at your TCAD tools (do this once)
- [Writing a problem file](docs/WRITING_A_PROBLEM.md) — the YAML format, every field explained
- [Tuning](docs/TUNING.md) — how to set parallelism and budget for your machine and your problem
- [Architecture](docs/ARCHITECTURE.md) — how every layer of the engine works
- [Optimizer backends](docs/OPTIMIZER_BACKENDS.md) — the default backend vs the optional BoTorch backend, and when to use which
- [The physics knowledge base](docs/PHYSICS_KNOWLEDGE.md) — how physics seeding and the guard work
- [Case study](docs/CASE_STUDY.md) — a real nanowire optimization, including the lessons learned

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

This is **version 1.0.1**. The engine is functional and has been used on real device optimization campaigns. It is under active development and new capabilities will be added over time. See [`CHANGELOG.md`](CHANGELOG.md).

Feedback, issues, and contributions are welcome. See [`CONTRIBUTING.md`](CONTRIBUTING.md).

---

## License

Released under the MIT License. See [`LICENSE`](LICENSE). You are free to use, modify, and build on this, including commercially, as long as you keep the copyright notice.

Third-party components used by the optional optimizer backend are credited in [`NOTICE`](NOTICE).

---

## Citation

If this engine helps your work, a citation or a link back is appreciated:

```
R. Sri Krishna, "TCADOpt: A physics-aware Bayesian optimization engine for
semiconductor device simulation," 2026. https://github.com/rskrishna2004/tcad-optimization-engine
```
