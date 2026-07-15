# TCADOpt Documentation

New here? Read in this order. Each doc says when to read it.

## Start
1. **[GETTING_STARTED.md](GETTING_STARTED.md)** — install and verify your environment (5 minutes).
2. **[WORKFLOW.md](WORKFLOW.md)** — the complete picture: problem file in, one command, many parallel simulations, optimized device out. **This is the main guide.**

## Set up your simulator (once)
3. **[CONNECTING_A_SIMULATOR.md](CONNECTING_A_SIMULATOR.md)** — point the engine at your TCAD tools and decks. Vendor-independent.

## Run your own optimizations
4. **[WRITING_A_PROBLEM.md](WRITING_A_PROBLEM.md)** — the problem YAML format, every field.
5. **[TUNING.md](TUNING.md)** — set parallelism and budget for your machine and problem.

## Understand it deeper (optional)
6. **[ARCHITECTURE.md](ARCHITECTURE.md)** — how each layer of the engine works.
7. **[PHYSICS_KNOWLEDGE.md](PHYSICS_KNOWLEDGE.md)** — how physics guides the search and guards the results.
8. **[CASE_STUDY.md](CASE_STUDY.md)** — a real optimization, with the mistakes and lessons.

## The three things you ever edit
- `problems/<name>.yaml` — what to optimize (parameters, objective, budget)
- `decks.yaml` — which deck files the engine runs for each device
- environment variables — which TCAD tools it calls (see WORKFLOW.md)

You never edit engine source code to run your own optimizations.
