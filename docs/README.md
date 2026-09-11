# TCADOpt Documentation

New here? Start with what you are trying to do. The two paths share an engine
but they are different jobs, and reading the wrong guide first is confusing.

**I want to find a better device design.** You have a simulator and a device,
and you want the engine to search the geometry and doping for the best
electricals.

**I want a compact model of a device I already have.** You have reference
curves from a device that is already simulated or measured, and you want a
model card that reproduces them in a circuit simulator.

## Start (both paths)
1. **[GETTING_STARTED.md](GETTING_STARTED.md)** — install and verify your environment (5 minutes).

## Path A · Design optimization
2. **[WORKFLOW.md](WORKFLOW.md)** — the complete picture: problem file in, one command, many parallel simulations, optimized device out. **This is the main guide for this path.**
3. [CONNECTING_A_SIMULATOR.md](CONNECTING_A_SIMULATOR.md) — point the engine at your TCAD tools and decks. Vendor-independent. Do this once.
4. [WRITING_A_PROBLEM.md](WRITING_A_PROBLEM.md) — the problem YAML format, every field.
5. [TUNING.md](TUNING.md) — set parallelism and budget for your machine and problem.

## Path B · Parameter extraction
2. **[PARAMETER_EXTRACTION.md](PARAMETER_EXTRACTION.md)** — the complete picture: reference curves in, staged fit, extracted model card out. **This is the main guide for this path.**
3. **[EXTRACTION_TUTORIAL.md](EXTRACTION_TUTORIAL.md)** — your first extraction, one command at a time, with every printed line explained. Read this second.
4. [CONNECTING_A_SIMULATOR.md](CONNECTING_A_SIMULATOR.md) — the circuit-simulator half is at the end. Do this once.
5. [WRITING_A_PROBLEM.md](WRITING_A_PROBLEM.md) — the `fit:` and `stages:` blocks, every field.

## Understand it deeper (optional, both paths)
6. **[ARCHITECTURE.md](ARCHITECTURE.md)** — how each layer works, and how one optimizer core serves two jobs.
7. [OPTIMIZER_BACKENDS.md](OPTIMIZER_BACKENDS.md) — the default backend vs the optional BoTorch backend.
8. [PHYSICS_KNOWLEDGE.md](PHYSICS_KNOWLEDGE.md) — how physics guides the search and guards the results.
9. [CASE_STUDY.md](CASE_STUDY.md) — a real optimization, with the mistakes and lessons.

## The things you ever edit

For design optimization:

- `problems/<name>.yaml` — what to optimize (parameters, objective, budget)
- `decks.yaml` — which deck files the engine runs for each device
- environment variables — which TCAD tools it calls (see WORKFLOW.md)

For extraction:

- `problems/<name>_fit.yaml` — what to fit (`fit:` targets, `stages:` schedule)
- `targets/*.csv` — your reference curves
- environment variables — which circuit simulator it calls (see PARAMETER_EXTRACTION.md)

You never edit engine source code to run your own optimizations or extractions.
