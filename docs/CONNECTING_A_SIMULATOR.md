# Connecting a Simulator

TCADOpt is the optimization brain. To do real work it needs to drive a simulator. Which simulator depends on the job:

- **Design optimization** drives a TCAD simulator: a structure/mesh builder and an electrical device solver. Sections 1 to 6 below.
- **Parameter extraction** drives a circuit simulator: one tool, one command. Section 7 below, and it is much shorter, because a SPICE netlist and a compact model card are standardised formats where a TCAD structure deck is not.

This document explains the adapter you write in each case. This is the only integration work required.

**No simulator files are included in this repository.** Vendor decks, input files, and vendor documentation are copyrighted and are intentionally absent. What follows describes the interface in general terms so you can connect any simulator.

---

## Part 1 - Connecting a TCAD simulator (design optimization)

---

## The idea

The engine proposes a candidate design as a dictionary of parameter values, for example:

```python
{"NSD": 3.1e20, "LEXT": 0.012, "OFFSET": 0.002}
```

Your job is to provide a function that:

1. takes such a dictionary,
2. writes it into a simulator input deck,
3. runs the simulator,
4. reads the electrical results,
5. returns them as a dictionary of metrics, for example:

```python
{"ION_A": 1.1e-5, "IOFF_A": 4.7e-11, "gm_peak_S": 3.1e-5}
```

Everything else, the surrogate model, the search, the physics guard, the scoring, is handled by the engine.

---

## Configuring which tools get invoked

The engine runs two commands per candidate design:

```
structure step :  <STRUCTURE_TOOL> <STRUCTURE_ARGS...> <structure_file>
device step    :  <DEVICE_TOOL>    <DEVICE_ARGS...>    <device_file>
```

The structure step builds the geometry and mesh. The device step runs the
electrical simulation and writes a results file. Neither tool name is
hardcoded. Set them with environment variables:

```bash
export TCADOPT_STRUCTURE_TOOL="my_structure_builder"
export TCADOPT_STRUCTURE_ARGS="-batch -input"
export TCADOPT_DEVICE_TOOL="my_device_solver"
export TCADOPT_DEVICE_ARGS=""
export TCADOPT_STRUCTURE_TIMEOUT=900
export TCADOPT_DEVICE_TIMEOUT=5400
```

Check the current configuration at any time:

```bash
python -m tcadopt.l0_runtime.config
```

The defaults live in `tcadopt/l0_runtime/config.py`.

---

## The three pieces you provide

### 1. A parameterized deck template

Your simulator deck (the structure-building script and the electrical-simulation input) with the tunable quantities marked so they can be substituted per candidate.

The reference approach used during development keeps the structure-building parameters in a tiny separate include file that the structure script reads. The engine writes that include file for each candidate, then runs the structure builder and the electrical simulation. For example the structure script reads a value like a doping concentration or a junction offset from the include file, and everything else in the deck is fixed.

A robust alternative, which produces a fully self-contained single deck (useful for final submission or sharing), is to write the parameter values directly into the deck as constants and drop the include file entirely. Both approaches work; the include-file approach is more convenient during optimization because only the small include file changes between runs.

**Design your deck so that all tunable parameters are isolated and easy to substitute.** Keep everything else, geometry that is fixed, physics models, solver settings, constant.

### 2. A render-and-run step

A small piece of logic that, given a candidate dictionary:
- writes the parameter values into the include file (or into the deck),
- invokes the structure builder,
- invokes the electrical simulation,
- points at the correct deck for the requested `device_class` and `measurement`.

In the reference implementation this lives in the runner and dispatcher. The runner knows, for a given device class and measurement, which deck files to use. The dispatcher runs a whole batch of candidates in parallel, each in its own working directory, so many simulations proceed at once.

### 3. A results parser

A function that reads the simulator's electrical output file and extracts the metrics your problem file refers to (on-current, off-current, transconductance, and so on). The parser should:
- read the swept electrode voltage and the terminal current,
- de-duplicate any repeated points so numerical derivatives are safe,
- compute derived metrics such as peak transconductance (the derivative of current with respect to gate voltage) and the subthreshold slope,
- return everything as a plain dictionary keyed by the metric names your problem file uses.

The reference plot parser handles all of this and is a good model to follow for your simulator's output format.

---

## Wiring it into the engine

The execution layer `l3_exec` exposes a batch evaluator. It is constructed with the information needed to run your simulator (which deck, which output file to read, how many parallel workers), and it exposes a method that takes a list of candidate dictionaries and returns a list of result dictionaries. The orchestration layer calls this evaluator each round.

Concretely, to connect your simulator you:

1. Put your deck template files somewhere the runner can find them.
2. Teach the runner which deck files correspond to each `device_class` and `measurement` (a small mapping).
3. Adapt the results parser to your simulator's output format so it returns the metric names your problem files use.
4. Confirm the metric names in your parser match the metric names in your problem YAML objectives.

Once these line up, a campaign runs with:

```bash
python -m tcadopt.l8_orch.run_campaign path/to/your_problem.yaml
```

---

## Metric name matching

This is the single most common source of confusion, so it deserves emphasis. The names your parser returns must exactly match the names your problem file and the physics knowledge base use. If your problem objective says `metric: ION` and your parser returns `ION_A`, add an alias or make them identical. When a metric the scorer expects is missing from the parser output, the design is treated as failed. Keep the names consistent end to end.

---

## Practical advice from real use

- **Make the structure robust across the whole parameter range.** The optimizer will try designs at the edges and corners of your ranges. If some corner produces a mesh the simulator cannot solve, either tighten the range or make the structure script handle it. A design that fails to converge is wasted compute.
- **Choose a solver that suits the problem dimensionality.** For small two-dimensional structures a direct linear solver is often more robust than an iterative one; for large three-dimensional structures an iterative solver is usually necessary. A mismatched solver is a frequent cause of convergence failures at the first bias step.
- **Ramp gently.** Bring carriers onto a converged electrostatic and quantum solution before fully coupling all equations, and ramp bias in small steps. This avoids the large first-step residual that makes a solve diverge.
- **Return partial results gracefully.** If a sweep completes far enough to define the metrics but not to the very end, still return what you have; the engine can use it.
- **Keep every run in its own directory.** Parallel batches must not overwrite each other's files.

---

## Part 2 - Connecting a circuit simulator (parameter extraction)

This half is deliberately short. A compact model card is a standardised
`.model` statement and a netlist is standardised SPICE, so unlike a TCAD
structure deck there is nothing device-specific for you to write. The engine
generates both.

### Configuring which tool gets invoked

One command per candidate per target sweep:

```
<SPICE_TOOL> <SPICE_ARGS...> -i <deck.sp> -o <basename>
```

Set it with environment variables:

```bash
export TCADOPT_SPICE_TOOL="hspice"
export TCADOPT_SPICE_ARGS=""            # optional extra flags
export TCADOPT_SPICE_TIMEOUT=300        # seconds per deck
export TCADOPT_FIT_RUNS="/path/to/runs" # optional; default is ./runs_fit
```

Use the full path if the tool is not on your `PATH`:

```bash
export TCADOPT_SPICE_TOOL="/opt/synopsys/hspice/bin/hspice"
```

Confirm what will be called:

```bash
python check_setup.py
```

### What the engine generates for you

Per candidate, in its own run directory:

- **one model card per device polarity** - a `.model ... level = 72` statement
  with `VERSION` first, then the fixed structural parameters, then the
  parameters this stage is fitting;
- **one deck per target sweep** - `.include` the card, set the bias sources,
  place the element, `.dc` or `.ac` sweep it at exactly the reference bias
  points, and `.print` the result.

The sweep grid is copied from your reference data rather than chosen, because
comparing a model curve to a reference curve on a different grid is how a fit
quietly becomes an interpolation artefact.

### What you provide

Only two things.

**1. Your reference curves, as CSV.** One row per bias point. The I-V file
needs `device`, `sweep` (`IdVg` or `IdVd`), `bias`, `vg`, `vd`, and a current
column. The C-V file needs `device`, `vd`, `vg`, `Cgg_F`. Both may carry a
`usable` column; rows marked otherwise are excluded at load time and the count
is printed. Full column lists are in
[PARAMETER_EXTRACTION.md](PARAMETER_EXTRACTION.md).

**2. Your device's fixed structural parameters**, in the `fit.structures:`
block of your spec. These are measurements of the device you simulated, and the
optimizer is never allowed to move them - letting it would let a current error
be hidden by quietly resizing the transistor.

### If your simulator is not HSPICE

Reading an HSPICE `.lis` listing is built in. Another simulator needs a small
parser returning `(voltage_array, current_array)` for one sweep. Follow
`tcadopt/l3_exec/hspice_parser.py`: it parses the `.print` tables rather than
the binary sweep file, precisely so the format does not have to be assumed -
a printed table carries its own column headers. Do the same for yours and the
rest of the engine is unchanged.

If your simulator's element line or model syntax differs, the deck templates are
plain format strings at the bottom of `tcadopt/l2_decks/cardgen.py`.

### Practical advice from real use

- **Write `VERSION` explicitly and check it landed.** A compact model defaults
  to an old revision that may not support your geometry at all. Worse, the log
  will tell you what it actually used - so grep for it before trusting a run.
  One C-V run in this project's own history burned eleven hours of wall clock
  producing clean, complete, useless data because a stale copy of the deck was
  in the run directory and the log said `Metal Workfunction = 4.72` when the
  intended value was 4.791.
- **The first line of a netlist is the title, whatever it contains.** A comment
  banner above the intended title silently becomes the title and shifts the
  whole deck down one line. The generated decks handle this; hand-written ones
  often do not.
- **Fit both polarities or say that you did not.** An n-type-only card is a
  perfectly valid deliverable as long as its scope is stated.
