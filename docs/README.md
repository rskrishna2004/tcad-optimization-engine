# TCADOpt Documentation

New here? Start with what you are trying to do. The paths share an engine but
they are different jobs, and reading the wrong guide first is confusing.

**I want to find a better device design.** You have a simulator and a device,
and you want the engine to search the geometry and doping for the best
electricals.

**I want a compact model of a device I already have.** You have reference
curves from a device that is already simulated or measured, and you want a
model card that reproduces them in a circuit simulator.

**I built a gate-all-around device and I want a compact model of it.** Same as
above, but there is a lot that is specific to a nanosheet or nanowire device,
and there is a route built for exactly that.

## Start (both paths)
1. **[GETTING_STARTED.md](GETTING_STARTED.md)** - install and verify your environment (5 minutes).

## Path A. Design optimization
2. **[WORKFLOW.md](WORKFLOW.md)** - the complete picture: problem file in, one command, many parallel simulations, optimized device out. **This is the main guide for this path.**
3. [CONNECTING_A_SIMULATOR.md](CONNECTING_A_SIMULATOR.md) - point the engine at your TCAD tools and decks. Vendor-independent. Do this once.
4. [WRITING_A_PROBLEM.md](WRITING_A_PROBLEM.md) - the problem YAML format, every field.
5. [TUNING.md](TUNING.md) - set parallelism and budget for your machine and problem.

## Path B. Parameter extraction
2. **[PARAMETER_EXTRACTION.md](PARAMETER_EXTRACTION.md)** - the complete picture: reference curves in, staged fit, extracted model card out. **This is the main guide for this path.**
3. **[EXTRACTION_TUTORIAL.md](EXTRACTION_TUTORIAL.md)** - your first extraction, one command at a time, with every printed line explained. Read this second.
4. [CONNECTING_A_SIMULATOR.md](CONNECTING_A_SIMULATOR.md) - the circuit-simulator half is at the end. Do this once.
5. [WRITING_A_PROBLEM.md](WRITING_A_PROBLEM.md) - the `fit:` and `stages:` blocks, every field.

## Path C. A compact model for a gate-all-around device

You built a nanosheet or nanowire device in TCAD, it simulates, and you want a
BSIM-CMG card for it. This is Path B with everything that is specific to a
gate-all-around device filled in: which sweeps to run, how to build the
reference data, the parts of the model card that are easy to get wrong, and
what to do about the charge.

Read them in this order. Each one links to the next.

2. **[GAA_COMPACT_MODEL.md](GAA_COMPACT_MODEL.md)** - the route map. **Start here for this path** and read it all the way down before opening anything else.
3. [GAA_WHAT_YOU_NEED.md](GAA_WHAT_YOU_NEED.md) - the TCAD runs to have in hand, how to tell one really finished, the structure numbers to write down.
4. [GAA_REFERENCE_DATA.md](GAA_REFERENCE_DATA.md) - the two CSV files, the gate row, and why the total capacitance is not enough.
5. [GAA_MODEL_CARD.md](GAA_MODEL_CARD.md) - LEVEL 72, VERSION, GEOMOD 5, the five-node element, and the netlist rules.
6. [GAA_FIRST_RUN.md](GAA_FIRST_RUN.md) - one command at a time, with what every printed line means.
7. [GAA_EXTRACTION_ORDER.md](GAA_EXTRACTION_ORDER.md) - which parameters come out in which stage, and why that order.
8. [GAA_FREE_ZONE.md](GAA_FREE_ZONE.md) - the parameters that cannot change the drain current, proved and then measured.
9. [GAA_CHARGE_PARTITION.md](GAA_CHARGE_PARTITION.md) - the gate row, pinch-off, and the parameter the current and the charge have to share.
10. [GAA_CHECKING_RESULTS.md](GAA_CHECKING_RESULTS.md) - identifiability, physicality, and what finished looks like.
11. [GAA_TROUBLESHOOTING.md](GAA_TROUBLESHOOTING.md) - every failure this project hit, the message it printed, and the fix.

## Understand it deeper (optional, all paths)
- **[ARCHITECTURE.md](ARCHITECTURE.md)** - how each layer works, and how one optimizer core serves two jobs.
- [OPTIMIZER_BACKENDS.md](OPTIMIZER_BACKENDS.md) - the default backend vs the optional BoTorch backend.
- [PHYSICS_KNOWLEDGE.md](PHYSICS_KNOWLEDGE.md) - how physics guides the search and guards the results.
- [CASE_STUDY.md](CASE_STUDY.md) - a real optimization, with the mistakes and lessons.

## The things you ever edit

For design optimization:

- `problems/<name>.yaml` - what to optimize (parameters, objective, budget)
- `decks.yaml` - which deck files the engine runs for each device
- environment variables - which TCAD tools it calls (see WORKFLOW.md)

For extraction:

- `problems/<name>_fit.yaml` - what to fit (`fit:` targets, `stages:` schedule)
- `targets/*.csv` - your reference curves
- environment variables - which circuit simulator it calls (see PARAMETER_EXTRACTION.md)

You never edit engine source code to run your own optimizations or extractions.
