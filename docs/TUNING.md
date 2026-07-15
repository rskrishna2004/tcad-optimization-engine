# Tuning the Engine for Your Machine and Your Problem

TCADOpt runs many simulations in parallel. How many, and how many in total, are the two settings you must choose for your own hardware and your own simulator. Getting them right is the difference between using your machine fully and either overloading it or wasting it. This guide explains every user-adjustable setting, what it does, and how to choose it.

All of these live in the `budget:` section of your problem YAML, and every one can be overridden from the command line.

---

## The two settings that matter most

### `parallel` — how many simulations run at the same time

```yaml
budget:
  parallel: 16
```

The engine launches this many simulations simultaneously, each in its own working directory, each running your structure and device tools. This is the single biggest lever on how fast a campaign finishes and how hard your machine works.

**How to choose it.** It is bounded by three things at once, and you take the smallest:

1. **CPU cores.** Each simulation uses at least one core, and many TCAD device solvers themselves use several threads per run. If your device solver uses 4 threads internally and your machine has 32 cores, you can run about 32 / 4 = 8 simulations in parallel before you oversubscribe the CPU. If your solver runs single-threaded, you can run closer to one simulation per core.

2. **Memory.** Each simulation holds its mesh and solution in RAM. Find out how much one simulation uses (run one and watch peak memory), then divide your total RAM by that, and leave headroom. If one run uses 2 GB and you have 16 GB, keep parallel at or below about 6 to 7.

3. **Simulator licenses.** Many commercial TCAD tools check out a license per running instance, and per parallel-solver feature. You cannot run more simultaneous simulations than you have licenses for. This is often the real limit. Count your available licenses for both the structure tool and the device tool, and do not exceed the smaller count.

**Take the smallest of the three.** If your CPU allows 8, your memory allows 6, and you have 4 licenses, set `parallel: 4`.

**Examples:**
- A laptop with 8 cores, 16 GB RAM, a solver that uses 4 threads, one license: `parallel: 1` to `2`. It will be slow, but it will work.
- A workstation with 32 cores, 128 GB RAM, and 16 licenses, solver using 4 threads each: `parallel: 8` (CPU-bound) unless licenses cap it lower.
- A large server or cluster node with many cores, plenty of RAM, and ample licenses: `parallel: 32` to `64` or more.

Start conservative. Run a small campaign, watch your machine's CPU and memory, and raise `parallel` only if there is clear headroom.

### `max_evals` — how many simulations in total

```yaml
budget:
  max_evals: 300
```

The total simulation budget for the whole campaign. When the engine has run this many simulations, it stops (it may stop earlier if the search clearly converges).

**How to choose it.** More parameters need more simulations to search well. A rough starting guide:

- 3 to 4 parameters: 150 to 300 total.
- 5 to 7 parameters: 300 to 500 total.
- 8 to 12 parameters: 500 to 800 total.

Also do the time arithmetic. If one simulation takes 5 minutes and you run 16 in parallel, you complete about 16 simulations per 5 minutes, so 300 simulations take roughly 300 / 16 x 5 minutes, a bit over an hour and a half. Make sure your chosen budget finishes in a time you can wait, given your parallelism and your per-simulation runtime.

If a full search would need more simulations than you have time for, it is better to reduce the number of parameters (search a smaller, well-chosen space thoroughly) than to under-budget a large space (search a big space badly).

---

## The rest of the adjustable settings

### `round_n` — simulations per learning round

By default this equals `parallel`, so each round runs exactly one full parallel batch, which is the efficient choice. You rarely need to set it. If you do set it, keep it a multiple of `parallel` so batches stay full.

### `init_n` — the size of the initial exploration

Before the engine starts learning, it samples the space broadly. By default this is sized automatically from your parallelism. A larger initial sample explores more before committing, which helps on spaces you suspect have many separate good regions, at the cost of more up-front simulations. If you do not set it, the automatic value is sensible.

### `max_restarts` — how persistently to escape local optima

When the search plateaus, the engine restarts from an unexplored region rather than stopping. This setting caps how many times it will do that before concluding it is done. The default is a good balance. Raise it if you specifically suspect a deceptive space with many local optima and you have simulation budget to spare.

### Timeouts — how long to allow each simulation

Set with environment variables, not in the YAML:

```bash
export TCADOPT_STRUCTURE_TIMEOUT=900      # seconds for the structure/mesh step
export TCADOPT_DEVICE_TIMEOUT=5400        # seconds for the device simulation step
```

A simulation that exceeds its timeout is killed and counted as a failure, so the campaign is never held up by one stuck run. Set these a bit above how long a normal run of your device takes, so a genuinely slow-but-valid run is not killed, but a hung run does not block the batch forever. If your devices are large and slow, raise these. If they are small and fast, lower them so failures are detected quickly.

---

## Matching the settings to your problem

- **A quick exploratory run** to see if the setup works and roughly where good designs are: small `max_evals` (for example 100), whatever `parallel` your machine allows. You are not looking for the final answer, just confirming the loop runs and the trend is sensible.

- **A serious optimization run** for a design you will actually use: `max_evals` sized to your parameter count from the table above, `parallel` set to fully use your machine, and then run it a few times with different seeds (see WORKFLOW.md, Step 7) to confirm the champion is global.

- **A machine much smaller than the problem:** reduce the parameter count first. Five well-chosen parameters searched thoroughly beat twelve searched shallowly. Fix the parameters with the least physical leverage and optimize the rest.

---

## A first-run recipe

If you are not sure where to start, use this for your first real campaign, then adjust:

```yaml
budget:
  parallel: 4        # raise toward your core/memory/license limit once verified
  max_evals: 200     # raise toward the table value for your parameter count
```

Run it, watch CPU, memory, and the "batch done: N/M ok" line. If your machine has clear headroom and simulations are succeeding, raise `parallel`. If simulations are failing often, fix your deck and ranges before raising anything. Once a single run behaves well, scale `max_evals` up to a proper search and run multiple seeds.
