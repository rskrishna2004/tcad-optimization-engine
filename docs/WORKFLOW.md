# The Complete Workflow: From Problem to Optimized Device

This is the main guide. It walks through exactly what you do to optimize a real device, start to finish, with your own TCAD simulator. This is what TCADOpt is for: you provide a problem description and a simulator deck, run one command, and the engine runs many simulations in parallel, learns from them, and returns an optimized design with no further input from you.

If you have not yet confirmed your install works, do that first with `python check_setup.py` (see GETTING_STARTED.md).

---

## What actually happens when you run a campaign

When you start a campaign, the engine does this loop automatically, with no human intervention, until the budget is spent or the search converges:

1. It reads your problem file and builds the design space and the scoring function.
2. It creates an initial set of candidate designs (some guided by device physics, the rest space-filling).
3. **For each candidate, it launches your simulator.** It creates a separate working directory for that candidate, writes the candidate's parameter values into your deck, runs your structure/mesh builder, then runs your electrical device solver, then reads the results file and extracts the electrical metrics.
4. It runs many of these simulations **at the same time**, as many in parallel as you configure.
5. It checks every result against device-physics laws and discards physically impossible ones.
6. It fits a surrogate model to all valid results and chooses the next batch of candidates intelligently.
7. It repeats from step 3 for successive rounds, improving each round.
8. When it stops, it reports the champion design and its metrics, and stores every simulation in a database.

You start it and you come back to an optimized device. That is the point.

---

## Step 1: Connect your simulator (one time)

TCADOpt is vendor-independent. It does not know or care which TCAD tools you use. It invokes two commands that you configure: a **structure/mesh build step** and an **electrical device simulation step**. These map to whatever your toolchain calls them (for example a structure editor and a device solver, or a process simulator and a device solver).

Set them with environment variables before running:

```bash
# the tool that builds the device structure and mesh
export TCADOPT_STRUCTURE_TOOL="your_structure_tool"
export TCADOPT_STRUCTURE_ARGS="your -batch -flags"

# the tool that runs the electrical simulation
export TCADOPT_DEVICE_TOOL="your_device_tool"
export TCADOPT_DEVICE_ARGS=""

# how long to allow each step before giving up (seconds)
export TCADOPT_STRUCTURE_TIMEOUT=900
export TCADOPT_DEVICE_TIMEOUT=5400
```

Confirm what the engine will call:

```bash
python -m tcadopt.l0_runtime.config
```

The engine works with any simulator whose structure step and device step can be run from the command line on an input file. Whether your structure comes from a geometric structure editor or from a process simulation flow does not matter to the engine, as long as the command you give it produces the mesh that the device step consumes. Full details, including the deck template and the results parser you provide, are in [CONNECTING_A_SIMULATOR.md](CONNECTING_A_SIMULATOR.md). Do that guide once, then everything below just works.

---

## Step 2: Write your problem file

One YAML file describes what to optimize. Here is the shape of it; every field is explained in [WRITING_A_PROBLEM.md](WRITING_A_PROBLEM.md).

```yaml
problem_id: my_device_ion
device_class: my_nanowire
measurement: idvg

operating:
  T_K: 300
  supplies: {VDD: 0.7}

parameters:                       # what the engine is allowed to tune
  NSD:     [1.0e20, 4.5e20, log, cm-3]
  LEXT:    [0.0,    0.010,  lin, um]
  NPOCKET: [1.0e15, 8.0e19, log, cm-3]

constraints:
  hard:
    - NSD <= 4.5e20

objectives:                       # what "better" means
  - {metric: ION,  sense: max}
  - {metric: IOFF, cap: 1.0e-10}

budget:                           # how hard to search, and how parallel
  parallel: 16
  max_evals: 300
```

Two things in this file directly control the run:

- **parameters**: the design space. Set each range to what your process can actually fabricate. The optimizer will push to the edges of whatever you allow, so an unfabricable bound produces an unfabricable champion.
- **budget.parallel** and **budget.max_evals**: how many simulations run at once and how many in total. These depend on your machine and your simulator. How to choose them is the whole of [TUNING.md](TUNING.md); read it before your first real run.

Put your problem file in the `problems/` folder next to the examples already there.

---

## Step 3: Run the campaign

There are two ways to optimize, and you choose based on what you want.

### Option A: single-objective campaign (one best design)

Use this when you have one thing to maximize or minimize, optionally with caps
and floors on other metrics (for example: maximize on-current, keep leakage
under a limit). It returns a single champion design.

```bash
python -m tcadopt.l8_orch.run_campaign problems/my_device_ion.yaml
```

The objective in the problem file looks like this:

```yaml
objectives:
  - {metric: ION,  sense: max}          # the thing to maximize
  - {metric: IOFF, cap: 1.0e-10}        # a ceiling on leakage
```

### Option B: Pareto front (the whole trade-off curve)

Use this when two goals genuinely compete and you want to see the full set of
best compromises rather than commit to one balance up front (for example:
on-current versus leakage). It returns a **front** of designs, each one the
best achievable for its own balance of the two goals, so you can look at the
whole curve and pick the point you want.

```bash
python -m tcadopt.l8_orch.run_pareto problems/my_device_pareto.yaml
```

The objective in the problem file switches to Pareto mode:

```yaml
objectives:
  mode: pareto
  front:
    - {metric: ION,  sense: max}        # one axis of the trade-off
    - {metric: IOFF, sense: min}        # the other axis
  report: [gm_peak, SS]                 # recorded for each design, not optimized
```

The front is written to `results/pareto_front.json`. Each entry is a design
with its metrics; you scan the curve and choose the knee point or whichever
balance suits you. This is exactly how you decide between, say, a
high-drive-higher-leakage design and a low-leakage-lower-drive one: you see
both ends and everything between, measured.

### Overriding settings from the command line

Either campaign type accepts overrides without editing the YAML, useful for a
quick test at reduced budget:

```bash
python -c "from tcadopt.l8_orch.run_campaign import run_campaign; run_campaign('problems/my_device_ion.yaml', parallel=8, max_evals=200)"

python -c "from tcadopt.l8_orch.run_pareto import run_pareto; run_pareto('problems/my_device_pareto.yaml', parallel=8)"
```

---

## Step 4: What to watch while it runs

The engine prints its progress. Here is how to read it and what is healthy.

```
CAMPAIGN my_device_ion  parallel=16
  init_n=48 round_n=16 max_rounds=16
  [physics-seed] knowledge-guided init points
  batch done: 46/48 ok            <- 46 of 48 simulations succeeded
    init best score = ...
  round 0 best = ...               <- best after the first learning round
  round 1 best = ...               <- should improve or hold
  ...
  [physics_guard] ... excluded     <- an unphysical result was discarded (healthy)
  floor-detected -> restart        <- search plateaued, jumping to a new region
  CHAMPION ...                      <- the final answer
```

What to keep an eye on:

- **The "batch done: N/M ok" line.** M is your batch size (your parallelism). N is how many simulations succeeded. If N is much smaller than M every round, many simulations are failing to converge. That is almost always a deck or a parameter-range problem, not an engine problem: some corner of your design space produces a structure your simulator cannot solve. Tighten the ranges or make your deck more robust. A few failures per batch is normal and harmless.
- **The best score improving over rounds.** It should climb and then flatten. Flattening is expected; it means the search is converging.
- **physics_guard exclusions.** These are healthy. The guard caught a physically impossible result and kept it out of the model.
- **floor-detected restarts.** Also healthy. The search stalled and is deliberately jumping to unexplored regions to make sure it did not stop in a local optimum.

If the very first batch produces almost no successes, stop and check your simulator connection: run one simulation by hand at the middle of your parameter ranges and make sure your deck and parser work before letting the engine launch hundreds.

---

## Step 5: Where the results go

Everything is written under the `results/` folder:

- **`results/experiments.db`**: a database containing every single simulation the engine ran, with its design, its metrics, its score, and metadata. Nothing is ever lost.
- **`results/master*.csv`**: a flat table of all trials, easy to open in a spreadsheet.
- For a Pareto run, **`results/pareto_front.json`**: the full trade-off front.

Each individual simulation also leaves its working directory under `runs/run_<id>/`, containing the exact deck that was run and the raw simulator output. If you want to inspect precisely what the engine simulated for any design, it is all there.

---

## Step 6: Read the champion and the confidence evidence

At the end, the engine prints the champion design and its metrics, followed by a short block of convergence evidence:

```
CHAMPION  score=...
  ION = ...   IOFF = ...   gm = ...
  design: NSD=...  LEXT=...  NPOCKET=...
  ---- convergence evidence ----
  designs evaluated : ...
  gap to runner-up  : ...
  top-5 scores      : ...
```

- **design**: the actual parameter values of the best device. These are what you feed back into your deck to reproduce the champion, or hand to whoever fabricates it.
- **gap to runner-up**: how far ahead the champion is. A large gap with tightly clustered top designs means a sharp, well-separated optimum. A near-zero gap means many near-equal designs exist, and any of them is an equally valid answer.

To reproduce the champion exactly, take its parameter values, put them into your deck, and run your simulator once by hand. The design is also in the database and in the CSV.

---

## Step 7: Confirm the optimum is global (recommended)

Bayesian optimization cannot prove mathematically that it found the global best on a black-box function. The practical way to gain confidence is to run the whole campaign a few times with different random seeds and check the champions agree:

```bash
python -c "from tcadopt.l8_orch.run_campaign import run_campaign; run_campaign('problems/my_device_ion.yaml', seed=0)"
python -c "from tcadopt.l8_orch.run_campaign import run_campaign; run_campaign('problems/my_device_ion.yaml', seed=1)"
python -c "from tcadopt.l8_orch.run_campaign import run_campaign; run_campaign('problems/my_device_ion.yaml', seed=2)"
```

If independent seeds land on the same design, that agreement is your evidence of a global optimum. If one seed finds something clearly better, you just escaped a local optimum the others fell into. This is the honest, standard way to trust an optimization result, and it is worth the extra runs for a design you intend to commit to.

---

## Optional: certify and defend the champion

If your problem file defines verification checks, you can re-simulate the champion on a finer mesh and audit it against physics and robustness, producing an evidence dossier:

```bash
python tools/defend_champion.py problems/my_device_ion.yaml
```

This tells you whether the champion holds up under a finer mesh and under small manufacturing-tolerance perturbations, which is exactly what you want to know before trusting a design.

---

## Everything you can adjust (and where)

There are only three places you ever change anything. You never edit engine
source code.

**1. Your problem file** `problems/<name>.yaml` — what to optimize:
- `parameters` — the design variables and their fabricable ranges
- `objectives` — what "better" means (single-objective or Pareto)
- `constraints` — hard bounds and relationships the design must satisfy
- `budget.parallel` — how many simulations run at once (see TUNING.md)
- `budget.max_evals` — total simulation budget (see TUNING.md)

**2. Your deck configuration** `decks.yaml` — which deck files the engine runs:
- one entry per `device_class`, giving the structure file, device file, the
  mesh file it produces, and the results file it writes
- these are all your own filenames; edit them to match your decks
- this replaces what used to be hardcoded, so a new device is a new YAML entry,
  never a code change

**3. Environment variables** — which tools the engine calls and for how long:

```bash
export TCADOPT_STRUCTURE_TOOL="your_structure_tool"   # required
export TCADOPT_STRUCTURE_ARGS="your -flags"           # optional
export TCADOPT_DEVICE_TOOL="your_device_tool"         # required
export TCADOPT_DEVICE_ARGS=""                         # optional
export TCADOPT_PARAM_FILE="params.txt"                # name of the tuned-values
                                                      # file your deck reads
export TCADOPT_STRUCTURE_TIMEOUT=900                  # seconds per structure step
export TCADOPT_DEVICE_TIMEOUT=5400                    # seconds per device step
export TCADOPT_DECKS="/path/to/decks.yaml"            # optional, if not in root
```

Check your configuration at any time:

```bash
python -m tcadopt.l0_runtime.config
```

It prints CONFIGURED or NOT CONFIGURED and shows exactly which commands the
engine will run. If it says NOT CONFIGURED, set the two required tool variables
above.

To make these settings permanent instead of typing them each session, add the
`export` lines to your shell startup file (`~/.bashrc` on Linux), or on Windows
set them under System Properties, Environment Variables.

---

## Summary of the whole flow

```
connect your simulator (once)   ->  set two environment variables
write problems/<name>.yaml      ->  parameters, objective, budget
run one command                 ->  python -m tcadopt.l8_orch.run_campaign problems/<name>.yaml
                                    engine runs hundreds of parallel simulations, unattended
watch batch success + score     ->  results appear under results/
read the champion + evidence     ->  design values are your optimized device
run a few seeds to confirm       ->  agreement = global-optimum confidence
```

That is the engine. You describe the device and the goal; it does the simulation campaign and hands you the optimized design.
