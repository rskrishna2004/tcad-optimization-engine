# Compact-Model Parameter Extraction

TCADOpt was built to answer "what device geometry gives the best electricals?"
This document covers the second thing it does, added in v1.1.0: **"what
compact-model parameters reproduce a device I have already simulated?"**

They sound similar. They are not, and the difference is the whole design of
this subsystem.

> **Want to run it rather than understand it?**
> [EXTRACTION_TUTORIAL.md](EXTRACTION_TUTORIAL.md) is the run-along: every
> command in order, with what you should see and what it means. Read that one
> first if you are in a hurry; come back here for why each piece is the way it
> is.

---

## 1. Why the existing engine could not do this unchanged

Three things had to be added, and they are exactly three.

### 1.1 The objective was the wrong shape

Every scorer in `l1_spec/scorer.py` reduces a simulation to scalars and
combines them:

```
score = sum_i w_i * log10(metric_i)  -  penalties
```

with `metric_i` drawn from `METRIC_KEYS`: `ION_A_per_um`, `SS_mV_per_dec`,
`Vt_V`, `DIBL_mV_per_V`, and so on.

For device design that is right. "Maximise drive, keep leakage under a cap" is
genuinely a statement about four numbers.

For extraction it is wrong, and the failure is not subtle. Here is a measured
demonstration from this repository's own test:

| | reference | candidate with V_th 10 mV off |
|---|---|---|
| I_ON | 1.6205e-4 A/um | 1.6208e-4 A/um |
| difference the SCALAR scorer sees | | **0.02 %** |
| difference the CURVE scorer sees | | **4.85 %** |

A scalar scorer is essentially blind to a 10 mV threshold error, because the
threshold error hides in the shape of the curve rather than in its endpoints.
A model card carrying that error would be handed to a circuit designer and
would mis-predict every delay it was used for.

So `l1_spec/curve_scorer.py` adds the missing objective: a residual over the
whole curve, at every bias point.

### 1.2 The result parser only spoke DF-ISE

`optimizer/plt_parser.py` reads the `.plt` files a TCAD device solver writes.
HSPICE writes a `.lis` listing. `l3_exec/hspice_parser.py` reads that.

It parses the **`.print` tables**, not the `.sw0` sweep file, on purpose. A
printed table carries its own column headers, so the parser learns the layout
from the file. A `.sw0` is a fixed-field vendor format whose layout would have
to be assumed. Assuming a file format is how you build a parser that reads
numbers confidently out of the wrong columns, so it is not done here.

### 1.3 The runner insisted on two tools

`optimizer/runner.run_one` runs the structure tool, checks the mesh file
appeared, then runs the device tool. HSPICE is one tool with no mesh, so that
check can never pass.

Rather than weaken a proven code path that the TCAD side depends on,
`l3_exec/spice_exec.py` is a second evaluator presenting the **same interface**:
`evaluate_batch(param_dicts, tag) -> results`. That is precisely the
interchangeability the layered architecture was designed for, and this is the
first time it has been exercised by something that is not a TCAD tool.

---

## 2. What is reused unchanged

This matters, because it is what makes this the same engine rather than a new
one wearing its name:

* **`ParamSpace`** -- bounds, log/linear scaling, `[0,1]^d` encode/decode,
  coupled-constraint clamps, Latin-hypercube sampling. BSIM-CMG parameters have
  exactly this shape. Not one line changed.
* **The optimizer core** -- the ARD-RBF GP with its analytic marginal-likelihood
  gradient, the TuRBO trust-region schedule, constrained expected improvement,
  and the optional BoTorch qLogEI backend. Not one line changed.
* **`ExperimentDB`** -- every fit attempt stored with its parameters, its
  encoded vector, its per-sweep errors, its score and its provenance. This is
  what turns "I adjusted some parameters until it looked right" into an
  extraction record somebody else can audit.
* **The campaign loop's structure** -- initial sample, rounds, floor detection,
  trust-region restart.

---

## 3. The residual, and why it has two halves

Drain current spans about eight decades. One error measure cannot serve both
ends of that.

A plain relative error is dominated by the on-state; sub-threshold contributes
nothing and is free to be wrong by a factor of ten. A plain log error treats
every decade equally, which is right below threshold but stops discriminating
above it, where 3 % is only 0.013 decades.

So the residual is split at a current threshold:

```
E_sub = RMS of  log10( |Id_model| / |Id_ref| )      below I_split   [decades]
E_on  = RMS of  (Id_model - Id_ref) / Id_ref        at/above        [fraction]

total = w_sub * E_sub + w_on * E_on          score = -total
```

`I_split` defaults to the same constant-current level that defines V_th
everywhere else in the project, so "sub-threshold" keeps one meaning throughout
rather than becoming a second arbitrary line.

Keeping the halves separate is not cosmetic. When a fit stalls, the two numbers
say **which half** stalled, and therefore which parameters to unfreeze. A single
blended number cannot tell you that.

Capacitance is scored as one relative error over every point, because
capacitance spans well under a decade and the split would be meaningless.

---

## 4. Staging, and why extraction is not one big search

BSIM-CMG has hundreds of parameters. Fitting them all at once is not a harder
version of the same problem; it is a meaningless question, because most of them
are degenerate with each other. A threshold shift can come from the gate work
function, from body doping, or from a short-channel coefficient. A drive-current
error can be absorbed by mobility or by series resistance.

Fit them together and the optimizer will find *some* set that matches the curve.
That set will be wrong in every way that matters: it will not extrapolate to a
geometry or temperature it was not fitted at, and the parameters will not mean
what their names say.

So extraction runs in stages, each on the bias region where its parameters
dominate, with everything already extracted **frozen**:

| Stage | Parameters | Scored on | Why there |
|---|---|---|---|
| 1 electrostatics | `PHIG`, `CIT`, `CDSC`, `NFACTOR` | IdVg at low V_d | Threshold and swing are set by gate and body; mobility and series resistance barely matter here. BSIM-CMG is a surface-potential model with **no `VTH0`** -- the threshold is moved by the gate work function. |
| 2 short channel | `DVT0`, `DVT1`, `ETA0`, `DSUB`, `CDSCD` | IdVg at **both** V_d | DIBL is by definition the difference between two drain biases. One sweep cannot determine these no matter how well it is fitted. |
| 3 transport | `U0`, `UA`, `UD`, `EU`, `VSAT`, `RDSW`, `RDSWMIN`, `PCLM` | on-state IdVg + IdVd | They dominate here, and the electrostatics are already settled so they cannot absorb a threshold error. |
| 4 capacitance | `CGSP`, `CGDP`, `CGBO`, `CFS`, `CFD` | C-V | The DC fit never saw a capacitance. Without this stage these are defaults pretending to be measurements. |
| 5 polish | a subset of all of the above | everything | Removes residual interaction inside a trust region that cannot wander far from a point that is already physically meaningful. |

Freezing is what makes this an **extraction** rather than a curve fit. For every
parameter you can say which measurement determined it and what was held fixed
while it was found. That is the sentence an examiner is actually asking for.

Frozen values persist to `results/frozen_<spec>.json` between stages, so a stage
can be re-run on its own without repeating the ones before it. A stage that
fails to converge freezes nothing -- a bad stage must not contaminate the next.

---

## 5. Identifiability: proving the numbers mean something

An extraction produces a number for every parameter. That is not the same as
*determining* every parameter.

If two parameters change the simulated curve in the same way, infinitely many
pairs fit equally well, and the pair reported is one arbitrary choice out of an
infinite set. This is a **degeneracy**, and it is the most common way a compact
model extraction is quietly wrong. It cannot be caught by looking at the fit
error, because a degenerate fit fits perfectly.

`l6_verify/identifiability.py` measures it directly. It perturbs each free
parameter around the extracted point, builds the Jacobian of the residual, and
reports three things:

* **sensitivity** -- a near-zero column means the data do not respond to that
  parameter at all, so its reported value is a starting guess, not a result;
* **collinearity** -- a pair at `|r|` near 1 changes the curve identically, so
  only their combination is determined;
* **condition number and effective rank** -- how many independent directions the
  measurement actually constrains, versus how many parameters were freed.

This was validated against a stand-in model with **known, deliberately built-in**
degeneracies. The diagnostic found every one of them:

```
free parameters : 9
effective rank  : 7   (independent directions the data constrains)
-> 2 parameter(s) MORE than the data can determine.

NOT MEASURED by this data: vsat

degenerate pairs (only their combination is determined):
   cit    ~ cdsc      r = +1.0000   DEGENERATE
   cdsc   ~ nfactor   r = +1.0000   DEGENERATE
   cit    ~ nfactor   r = +1.0000   DEGENERATE
   eta0   ~ dsub      r = -0.9969   DEGENERATE
   vsat   ~ rdswmin   r = -0.9043   strongly coupled
```

The stand-in model was constructed so that `CIT`, `CDSC` and `NFACTOR` enter
only through one sum, and `ETA0` and `DSUB` only through one product. Those are
exactly the pairs reported, and the effective rank of 7 out of 9 is exactly the
2 lost directions. The diagnostic is measuring the right thing.

The same test also confirmed the recovered combinations are correct even when the
individual parameters are not:

```
swing group  n = 1 + 0.25*NFACTOR + 60*CIT + 25*CDSC   error 2.69 %
DIBL  group  d = ETA0 * exp(-DSUB)                     error 0.16 %
```

The optimizer did not fail. It found the right answer to the question the data
can actually answer, and the diagnostic says which question that was.

---

## 6. Running it

```bash
export TCADOPT_SPICE_TOOL=hspice        # or the full path to your binary
export TCADOPT_SPICE_TIMEOUT=300

# every stage in order
python -m tcadopt.l8_orch.run_fit problems/nsfet_gaa_fit.yaml

# or one stage at a time (frozen values carry forward automatically)
python -m tcadopt.l8_orch.run_fit problems/nsfet_gaa_fit.yaml --stage 1
```

Outputs:

* `results/extraction.db` -- every fit attempt, queryable
* `results/frozen_nsfet_gaa_fit.json` -- the extracted card so far
* `runs_fit/fit_<id>/` -- the exact model card, decks and listings of each attempt

Before any of that, run the self-check, which needs no simulator:

```bash
python examples/extraction_demo/run_demo.py
```

It runs the complete staged pipeline against a stand-in transistor with a known
answer and known degeneracies, so it proves the loop **recovers** something
rather than merely running without crashing.

For budgets and parallelism, see [TUNING.md](TUNING.md), section "Tuning an
extraction" -- the arithmetic differs from a design campaign because each
evaluation is one simulator run *per target sweep*.

---

## 7. Two facts baked into the deck generator, both learned the hard way

**`VERSION` must be written explicitly.** LEVEL 72 defaults to VERSION 106.1,
which has no gate-all-around module, so `GEOMOD=5` is rejected with
`Out of range from [0:3]`. Writing `VERSION = 111.21` is what makes `GEOMOD=5`
and `NGAA=4` legal. This was found by a deck that failed, not by reading ahead.

**Line 1 of a netlist is the title, whatever it contains.** A comment banner
placed above the intended title silently becomes the title and shifts the whole
deck down by one line. Four probe decks were once lost to exactly this: the real
title line was then parsed as a `B` element and HSPICE printed its Verilog-A
syntax reference instead of a result. Every deck this module writes therefore
begins with a `*` line that is *meant* to be the title.

---

## 8. Bugs fixed in the base engine along the way

The audit that preceded this work found three live defects, each reproduced by
running it. They are fixed here because the extraction path depends on all three.

* **The physics guard was dead.** `physics_guard._DEF_KB` pointed at
  `<root>/knowledge/physics_rules.yaml`, which does not exist; the KB ships next
  to the module. `load_kb()` swallows a missing file and returns an empty KB, so
  `validate()` passed *everything* -- including a trial with SS = 20 mV/dec at
  350 K, well below the Boltzmann floor of 69.4 -- and `physics_seeds()` returned
  `[]` on every campaign. Both advertised "physics-aware" features were inert.
* **The failure classifier read log files nothing writes.** It looked for
  `tool_sde.log` / `tool_sdevice.log`; the runner writes `tool_structure.log` /
  `tool_device.log` and `certify.py` writes `sde.log` / `sdev.log`. Every real
  failure classified as `unknown_fail`.
* **The runtime metrics module lacked the de-duplication guard its twin had.**
  A repeated bias point -- which every ramp deck produces -- made `gm` come back
  `nan` and `SS` come back `inf`, so a good simulation scored `-1e9`.

All three are verified fixed by tests that fail against the original code. The
full audit, with the coverage reconciliation and the remaining four (lower
severity) findings, is summarised in the v1.1.0 entry of
[../CHANGELOG.md](../CHANGELOG.md).

---

## 9. Where to go next

- [EXTRACTION_TUTORIAL.md](EXTRACTION_TUTORIAL.md) -- run it, one command at a time
- [WRITING_A_PROBLEM.md](WRITING_A_PROBLEM.md) -- Part 2: the `fit:` and `stages:` blocks, every field
- [CONNECTING_A_SIMULATOR.md](CONNECTING_A_SIMULATOR.md) -- Part 2: pointing the engine at your circuit simulator
- [TUNING.md](TUNING.md) -- "Tuning an extraction"
- [ARCHITECTURE.md](ARCHITECTURE.md) -- how one optimizer core serves both jobs
