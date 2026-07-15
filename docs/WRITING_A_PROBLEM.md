# Writing a Problem File

Every optimization in TCADOpt is described by one YAML file. This document explains every field. Once you understand this file, you can optimize any device without touching engine code.

A problem file has these sections: identity, operating point, parameters, constraints, objectives, models, fidelity, and budget. Real examples live in the `problems/` folder.

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

## Tips for good problem files

- **Keep the parameter count small and meaningful.** Every parameter multiplies the search difficulty. Pick the ones with real physical leverage.
- **Set ranges to what can actually be fabricated.** The optimizer will push to the edges of whatever you allow, so if a range includes an unmanufacturable value, you may get an unmanufacturable champion.
- **Use log scale for concentrations, linear for geometry.**
- **Reward what you actually care about.** If two metrics both matter, either weight them together or use Pareto mode. Do not optimize only one and hope the other follows.
- **Match parallel to your hardware.** Larger batches use your compute better and let each optimization round learn from more data.
