# Writing a Problem File

Every job in TCADOpt is described by one YAML file. This document explains every field. Once you understand this file, you can optimize any device, or extract any model, without touching engine code.

There are two shapes of problem file, and they share their vocabulary:

- **A design problem** has identity, operating point, parameters, constraints, objectives, models, fidelity and budget. Part 1 below.
- **A fit problem** has identity, operating point, a `fit:` block naming the reference curves, and a `stages:` list. Part 2 below.

Real examples of both live in the `problems/` folder.

---

# Part 1 — A design problem

---

## Minimal example

```yaml
problem_id: my_device_ion
device_class: planar_nmos
measurement: idvg

operating:
  T_K: 300
  supplies: {VDD: 0.7, VB: 0.0}

parameters:
  NSD:  [1.0e20, 4.5e20, log, cm-3]
  LEXT: [0.005, 0.020, lin, um]

constraints:
  hard:
    - NSD <= 4.5e20
  coupled: []

objectives:
  - {metric: ION, sense: max}
  - {metric: IOFF, cap: 1.0e-10}

budget: {max_evals: 400, parallel: 64}
```

---

## Section by section

### Identity

```yaml
problem_id: my_device_ion
device_class: planar_nmos
measurement: idvg
```

- **problem_id**: a unique name for this problem. All results are stored under this name in the database.
- **device_class**: a label for the device family. Your simulator adapter uses this to choose the right deck. The engine also uses it to route physics knowledge.
- **measurement**: which simulation sweep to run (for example an gate-voltage sweep). Your adapter maps this to the correct deck.

### Operating point

```yaml
operating:
  T_K: 300
  supplies: {VDD: 0.7, VB: 0.0}
  sweep: {electrode: gate, from: 0.0, to: 0.7, drain_at: 0.7}
  bias_sign: n
```

- **T_K**: temperature in Kelvin. Also used by the physics guard (the subthreshold slope limit depends on temperature).
- **supplies**: the supply voltages, such as the drain supply VDD and the body bias VB.
- **sweep**: descriptive metadata about the voltage sweep. The actual sweep is defined in your simulator deck.
- **bias_sign**: n for an n-type device, p for a p-type device.

### Parameters

This is the design space the engine searches. Each entry is one tunable parameter.

```yaml
parameters:
  NSD:  [1.0e20, 4.5e20, log, cm-3]
  LEXT: [0.005, 0.020, lin, um]
  OFFSET: [-0.002, 0.004, lin, um]
  TIL:  {fixed: 0.0005, unit: um}
```

Each free parameter is a list of four items: **[low, high, scale, unit]**.
- **low, high**: the fabricable range. The engine never proposes a value outside this range. Choose these to be manufacturable.
- **scale**: `log` for quantities that span orders of magnitude (doping concentrations), `lin` for quantities that vary linearly (lengths, offsets).
- **unit**: a label for your reference, such as cm-3 or um.

A **fixed** parameter uses `{fixed: value, unit: ...}`. It is passed to the simulator but never searched. Use this to hold something constant while still having it appear in the deck.

The number of free parameters is the dimensionality of the search. Fewer, well-chosen parameters converge faster and more reliably.

### Constraints

```yaml
constraints:
  hard:
    - NSD <= 4.5e20
    - gate_material == metal_wf
  coupled:
    - NCH >= 1.15 * NSUB
```

- **hard**: simple bounds and equalities the champion must satisfy. These are checked during certification.
- **coupled**: relationships between parameters that must hold. The parameter space enforces coupled constraints when it decodes a design, so proposed designs always respect them.

### Objectives

This is what you are optimizing. There are two modes.

**Scalar / capped mode** (a list of objective entries):

```yaml
objectives:
  - {metric: ION, sense: max, weight: 1.0}
  - {metric: IOFF, sense: min, weight: 0.4}
  - {metric: IOFF, cap: 1.0e-10}
```

- **sense: max** rewards a larger metric; **sense: min** rewards a smaller one.
- **weight** sets the relative importance of each term.
- **cap** enforces a ceiling: designs above the cap are penalized. Use this for a leakage limit.
- You can also use **floor** for a minimum (for example, keep drive current above a threshold) and **target** to hit a specific value.

**Pareto mode** (a mapping with `mode: pareto`):

```yaml
objectives:
  mode: pareto
  front:
    - {metric: ION, sense: max}
    - {metric: IOFF, sense: min}
  report: [gm_peak, SS]
```

This traces the full trade-off front between the front metrics, so you can see the whole set of best compromises and pick the point you want. The report metrics are recorded alongside but not optimized.

### Models, fidelity, budget

```yaml
models:
  mobility: [DopingDependence, HighFieldSaturation]
  # ... descriptive notes about the physics models your deck uses

fidelity:
  search_mesh: standard
  verify_mesh_refine: 2.0
  verify_thresholds: {mesh_shift_pct: 12}

budget:
  max_evals: 400
  parallel: 64
  wall_clock_h: 8
```

- **models**: descriptive record of the physics models enabled in your deck. Documentation for you and for the report; the actual models live in the deck.
- **fidelity**: settings for the verification layer, such as how much to refine the mesh when certifying the champion and how large a metric shift is tolerated.
- **budget**: how hard to search. **parallel** is how many simulations run at once (set this to what your machine can handle). **max_evals** is the simulation budget. **wall_clock_h** is an optional time guide.

---

## Tips for good design problem files

- **Keep the parameter count small and meaningful.** Every parameter multiplies the search difficulty. Pick the ones with real physical leverage.
- **Set ranges to what can actually be fabricated.** The optimizer will push to the edges of whatever you allow, so if a range includes an unmanufacturable value, you may get an unmanufacturable champion.
- **Use log scale for concentrations, linear for geometry.**
- **Reward what you actually care about.** If two metrics both matter, either weight them together or use Pareto mode. Do not optimize only one and hope the other follows.
- **Match parallel to your hardware.** Larger batches use your compute better and let each optimization round learn from more data.

---

# Part 2 — A fit problem

A fit problem answers a different question. The device is fixed; the unknowns
are a compact model's parameters, and "better" means the model's curve lies on
top of the reference curve.

## Minimal example

```yaml
problem_id: my_device_extraction
device_class: nanosheet_gaa
measurement: fit

operating:
  T_K: 300.0
  supplies: {VDD: 0.6}

fit:
  iv_targets: targets/iv_targets.csv
  cv_targets: targets/cv_targets.csv
  models: {nsfet_n: nsfet_n}
  nf: 1
  i_split_A_per_um: 1.0e-7
  w_subthreshold: 1.0
  w_on_state: 1.0
  structures:
    nsfet_n: {version: 111.21, geomod: 5, ngaa: 4, l: 12.0e-9}

budget: {parallel: 8, max_evals: 160}

stages:
  - name: s1_electrostatics
    sweeps: [nsfet_n_IdVg_0.05]
    parameters:
      phig: [4.35, 4.65, lin, eV]
```

## The `fit:` block

```yaml
fit:
  iv_targets: targets/iv_targets.csv
  cv_targets: targets/cv_targets.csv
  devices: [nsfet_n]
  models:  {nsfet_n: nsfet_n, nsfet_p: nsfet_p}
  nf: 1

  i_split_A_per_um: 1.0e-7
  w_subthreshold: 1.0
  w_on_state: 1.0
  current_noise_floor_A: 1.0e-14

  structures:
    nsfet_n: {...}
```

- **iv_targets / cv_targets**: paths to your reference-curve CSVs, relative to the repository root. Either may be omitted.
- **devices**: optional whitelist. Omit it to use every device in the files.
- **models**: maps a device name in your CSV to the model name written into the card and the element line.
- **nf**: number of fingers. This is an *instance* parameter, so it goes on the element line and never inside the model card. The engine puts it in the right place.
- **i_split_A_per_um**: the current that separates "sub-threshold" from "on state" in the residual. Set it to the same constant-current level you use to define threshold voltage, so the word keeps one meaning across your whole project.
- **w_subthreshold / w_on_state**: the relative weight of the two halves of the residual. Equal weights are a sensible default; raise `w_subthreshold` if leakage accuracy matters more than drive accuracy for your application.
- **current_noise_floor_A**: reference currents below this are treated as noise and skipped. Fitting to a simulator's numerical floor teaches the model to reproduce a rounding error.
- **structures**: the fixed structural parameters written into every model card, per device. These are measurements of the device you simulated. **The optimizer never touches them**, and that is the point: letting it move a dimension lets it hide a current error by quietly resizing the transistor.

## The `stages:` list

Each entry is one full campaign.

```yaml
stages:
  - name: s2_short_channel
    sweeps: [nsfet_n_IdVg_0.05, nsfet_n_IdVg_0.60]
    sweep_weights: {nsfet_n_IdVg_0.05: 1.0, nsfet_n_IdVg_0.60: 2.0}
    budget: {parallel: 8, max_evals: 140, init_n: 30, max_restarts: 2}
    parameters:
      dvt0:  [0.0, 5.0, lin, "-"]
      dvt1:  [0.1, 2.0, lin, "-"]
      eta0:  [0.0, 0.5, lin, "-"]
    coupled: []
```

- **name**: the campaign label. It names this stage's rows in the database and its entry in the frozen-parameters file, so make it descriptive.
- **sweeps**: which target curves this stage is scored on. Names are built as `<device>_<sweep>_<|bias|>`, for example `nsfet_n_IdVg_0.60`. Omit `sweeps` to score on everything, which you rarely want.
- **sweep_weights**: optional per-sweep weights, if one curve matters more.
- **budget**: as for a design problem, and overrides the top-level `budget` for this stage only.
- **parameters**: exactly the same `[low, high, scale, unit]` format as a design problem. These are the only parameters this stage may move.
- **coupled**: optional coupled constraints, same syntax as a design problem.

Everything extracted by an earlier stage is held **frozen** and written into
every card this stage generates. Freezing persists to
`results/frozen_<spec>.json` between stages, so any stage can be re-run on its
own without repeating the ones before it.

## Tips for good fit problem files

- **Order the stages by which bias region determines what.** Threshold and swing from a low-drain transfer curve; drain-induced effects from *two* drain biases, because the effect is by definition the difference between them; transport from the on state; capacitance from C–V, which the DC fit never saw at all.
- **Free only what that region can determine.** A stage with more free parameters than the data has independent directions will produce confident numbers that mean nothing. Run the identifiability check to find out how many directions you actually have.
- **Never free a structural dimension.** If a dimension is genuinely uncertain, that is a measurement problem, and fitting it hides the problem instead of solving it.
- **Bound narrowly where you already have a measurement.** Parasitic capacitances you measured belong in a tight range, so the stage refines a measurement rather than inventing one.
- **Give each stage a small budget first.** A stage with four free parameters and one sweep is cheap and will expose an integration problem before you spend a real budget on stage 3.
