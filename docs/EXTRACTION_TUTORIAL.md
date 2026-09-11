# Your First Extraction, One Command at a Time

[PARAMETER_EXTRACTION.md](PARAMETER_EXTRACTION.md) explains what the extraction
subsystem is and why it is built the way it is. This document is the other
thing: a run-along. Every command, in order, with what you should see and what
it means.

Work through it once with the self-check, then once with your own device.
Nothing here assumes you have read the design-optimization guides.

---

## Step 0: confirm the engine is installed

```bash
cd tcad-optimization-engine
python check_setup.py
```

You should see something like:

```
============================================================
TCADOpt environment check
============================================================
Python  : 3.11.5  (OK)
numpy   : found (1.26.4)
scipy   : found (1.11.4)
yaml    : found (6.0.1)
tcadopt : v1.1.0
------------------------------------------------------------
Simulator tools (optional -- only needed for real runs)
  design optimization : structure=NOT SET  device=NOT SET
  model extraction    : spice=NOT SET
```

`NOT SET` is expected at this point. Step 1 needs no simulator at all.

---

## Step 1: run the self-check

```bash
python examples/extraction_demo/run_demo.py
```

This runs the complete staged extraction against a stand-in transistor — a fast
analytic function standing in for a circuit simulator. It is not a compact
model and no netlist is run, but every other part of the machinery is the real
one.

### Reading the output

```
STAGE s1_electrostatics  free=4  frozen=0  sweeps=1  backend=scipy_gp_v4_tr
  free   : phig, cit, cdsc, nfactor
  init        error = 0.33436
  round 0     error = 0.28821
  round 1     error = 0.13928
  ...
  STAGE COMPLETE  error = 0.07568
     sub-threshold  0.0706 decades  (17.6 % in current)
     on state       0.0051          (0.51 %)
     phig      = 4.50315       true 4.503         err    0.00 %
```

Line by line:

- **`free=4 frozen=0`** — this stage may move four parameters and inherits none.
  Stage 2 will say `frozen=4`.
- **`sweeps=1`** — this stage is scored on one target curve. Later stages use
  more, and stage 2 uses two *because* it has to: the effect it is fitting is
  defined as the difference between two drain biases.
- **`error` falling round on round** — the surrogate is learning. Flattening is
  expected and is how the stage decides it is done.
- **the two error numbers** — this is the part worth understanding. Drain
  current spans about eight decades, so one error measure cannot serve both
  ends. Sub-threshold error is quoted in **decades** (0.0706 decades is 17.6 %
  in current); on-state error is quoted as a **fraction** (0.0051 is 0.51 %).
  When a fit stalls, these two say which half stalled and therefore which
  parameters to release.
- **`phig ... err 0.00 %`** — the stand-in has a hidden true value the optimizer
  was never given, and stage 1 recovered it. That is the check that the loop
  works, not just that it runs.

Then some parameters come back badly wrong:

```
     cit       = 0.000315928   true 0.0012        err   73.67 %
     cdsc      = 0.00965356    true 0.003         err  221.79 %
```

**This is the correct result, not a failure.** Read on.

### The identifiability report

At the end you get:

```
free parameters : 9
effective rank  : 7   (independent directions the data constrains)
-> 2 parameter(s) MORE than the data can determine.

NOT MEASURED by this data: vsat

degenerate pairs (only their combination is determined):
   cit    ~ cdsc      r = +1.0000   DEGENERATE
   cdsc   ~ nfactor   r = +1.0000   DEGENERATE
   eta0   ~ dsub      r = -0.9969   DEGENERATE
```

The stand-in model was deliberately built so that `CIT`, `CDSC` and `NFACTOR`
enter only through one sum, and `ETA0` and `DSUB` only through one product.
Those are exactly the pairs reported, and the rank deficiency of 2 is exactly
the two lost directions.

So the optimizer did not fail. It answered the question the data can answer, and
this report says which question that was. **A degenerate fit fits perfectly**,
so the fit error can never reveal this — which is precisely why the check is a
separate measurement.

---

## Step 2: point the engine at your circuit simulator

```bash
export TCADOPT_SPICE_TOOL="hspice"
export TCADOPT_SPICE_TIMEOUT=300
```

Use the full path if it is not on your `PATH`:

```bash
export TCADOPT_SPICE_TOOL="/opt/synopsys/hspice/bin/hspice"
```

Confirm:

```bash
python check_setup.py
```

`model extraction : spice=hspice` means you are connected.

To make this permanent, put the `export` lines in `~/.bashrc`.

---

## Step 3: prepare your reference curves

Two CSV files, one row per bias point, under `targets/`.

**`targets/iv_targets.csv`**

| column | meaning |
|---|---|
| `device` | device name, e.g. `nsfet_n`. Also selects polarity: a name ending `_p` is treated as p-type. |
| `sweep` | `IdVg` or `IdVd` |
| `bias` | the *fixed* terminal voltage for this sweep (the drain bias for an IdVg, the gate bias for an IdVd) |
| `vg`, `vd` | the bias at this point |
| `id_uA_per_um` *or* `id_A` | the drain current |

**`targets/cv_targets.csv`**

| column | meaning |
|---|---|
| `device`, `vd`, `vg` | as above |
| `Cgg_F` | gate capacitance in farads |
| `usable` | optional. Anything other than `yes`/`true`/`1`/blank excludes the row. |

The `usable` column matters more than it looks. Real capacitance data has
regions where the measurement itself is not trustworthy — a matrix row that
does not sum to zero, a point at the simulator's noise floor. Fitting to a
point the reference says is bad is worse than having no point, because the
optimizer will faithfully bend the model to reproduce a measurement error. Mark
those rows and the engine excludes them at load time and prints the count.

Check the engine agrees with you about what it loaded:

```bash
python -c "
from tcadopt.l3_exec.targets import load_targets, summarize
t,d = load_targets({'iv_targets':'targets/iv_targets.csv',
                    'cv_targets':'targets/cv_targets.csv'}, root='.')
print(summarize(t,d))"
```

```
target curves: 16 sweeps, 1631 bias points; 25 C-V rows excluded (reference flagged them unusable)
  nsfet_n_IdVg_0.05          iv  n=101   |Id|[A/um] 2.415e-11 .. 1.345e-04
  nsfet_n_IdVg_0.60          iv  n=101   |Id|[A/um] 4.508e-11 .. 1.620e-04
  ...
```

Read the sweep **names** here. They are what you write into each stage's
`sweeps:` list, and they are built as `<device>_<sweep>_<|bias|>`.

---

## Step 4: write your fit spec

Copy `problems/nsfet_gaa_fit.yaml` and edit it. Every field is documented in
[WRITING_A_PROBLEM.md](WRITING_A_PROBLEM.md), Part 2. The two blocks that
matter:

```yaml
fit:
  iv_targets: targets/iv_targets.csv
  cv_targets: targets/cv_targets.csv
  models: {nsfet_n: nsfet_n}
  i_split_A_per_um: 1.0e-7        # where sub-threshold ends and the on state begins
  structures:                      # MEASURED, never fitted
    nsfet_n:
      version: 111.21
      geomod: 5
      ngaa: 4
      l: 12.0e-9
      # ... every structural parameter of your device

stages:
  - name: s1_electrostatics
    sweeps: [nsfet_n_IdVg_0.05]
    budget: {parallel: 8, max_evals: 120, init_n: 24}
    parameters:
      phig: [4.35, 4.65, lin, eV]
      cit:  [0.0, 5.0e-3, lin, F/m2]
```

Two rules that save the most trouble:

1. **`structures:` is measured, not fitted.** Put every structural dimension
   there. If the optimizer can move a dimension, it will hide a current error
   by quietly resizing your transistor, and the parameter that absorbs the
   error will then be wrong and will mean nothing.
2. **Each stage frees only what its sweeps can determine.** More free
   parameters than the data has independent directions produces confident
   numbers with no content.

---

## Step 5: run stage 1 alone, first

```bash
python -m tcadopt.l8_orch.run_fit problems/your_fit.yaml --stage 1
```

Do this before running the whole schedule. Stage 1 is typically the cheapest —
few parameters, one sweep — and it exercises the model card, the deck
generation, the simulator call, the listing parser and your target file all at
once. If any of those is misconfigured you find out in minutes.

**If the first batch shows `0/N ok`**, the problem is integration, not
optimization. Look in the run directory the log names:

```bash
ls runs_fit/fit_s1_electrostatics_init000/
cat runs_fit/fit_s1_electrostatics_init000/*.lis | grep -i error
```

The three most common causes, in order:

- **The simulator is not on the path.** `check_setup.py` says so.
- **The model card is rejected.** The listing says which parameter. The most
  common by far is a `VERSION` that does not support your geometry — but the
  generated cards always write `VERSION`, so this usually means the value in
  `structures:` is wrong for your model.
- **The parser found no table.** Your simulator's listing format differs.
  See [CONNECTING_A_SIMULATOR.md](CONNECTING_A_SIMULATOR.md), Part 2.

**Before you trust a run that succeeded**, check the listing used the card you
think it did:

```bash
grep -i "version\|phig" runs_fit/fit_s1_electrostatics_init000/*.lib
```

This sounds paranoid. It is not: a run in this project's own history completed
cleanly after eleven hours and produced clean, complete, useless data because a
stale deck was in the run directory. A successful run of the wrong thing costs
more than a failure, because a failure tells you.

---

## Step 6: run the whole schedule

```bash
python -m tcadopt.l8_orch.run_fit problems/your_fit.yaml
```

Each stage prints what it freed, what it inherited, and what it froze:

```
STAGE s2_short_channel  free=5  frozen=4  sweeps=2
  free      : cdscd, dsub, dvt0, dvt1, eta0
  frozen    : cdsc=0.009851, cit=0.001575, nfactor=0.2205, phig=4.503
  scored on : nsfet_n_IdVg_0.05, nsfet_n_IdVg_0.60
```

Frozen values are written to `results/frozen_<spec>.json` after every stage, so
you can stop, inspect, and resume:

```bash
cat results/frozen_your_fit.json
python -m tcadopt.l8_orch.run_fit problems/your_fit.yaml --stage 3
```

A stage that fails to converge freezes **nothing**, so a bad stage cannot
contaminate the next one.

---

## Step 7: check identifiability before you believe the numbers

This is the step people skip, and it is the one that decides whether you have
an extraction or a coincidence.

```bash
python - <<'EOF'
import json
from tcadopt.l1_spec.curve_scorer import CurveResidualScorer
from tcadopt.l3_exec.targets import load_targets
from tcadopt.l3_exec.spice_exec import HSpiceEvaluator
from tcadopt.l6_verify.identifiability import jacobian, analyse, report

frozen = json.load(open('results/frozen_your_fit.json'))
targets, _ = load_targets({'iv_targets': 'targets/iv_targets.csv'}, root='.')
targets = [t for t in targets if t['name'] in ('nsfet_n_IdVg_0.05',
                                               'nsfet_n_IdVg_0.60')]
scorer = CurveResidualScorer(targets, i_split=1.0e-7)
ev = HSpiceEvaluator(targets, models={'nsfet_n': 'nsfet_n'},
                     structures={'nsfet_n': frozen}, n_parallel=4, scorer=scorer)
names = ['phig', 'cit', 'cdsc', 'nfactor', 'u0', 'ua', 'vsat', 'rdswmin']
J, used = jacobian(ev, scorer, frozen, names,
                   log_names=('u0', 'ua', 'vsat', 'rdswmin'))
print(report(analyse(J, used)))
EOF
```

This costs two simulator runs per parameter, which for eight parameters is
sixteen — minutes, not hours.

**How to act on what it says:**

| It reports | What it means | What to do |
|---|---|---|
| `effective rank` equals the number of free parameters, no degenerate pairs | Every parameter is independently determined | Nothing. This is the good outcome. |
| `NOT MEASURED by this data: X` | The curve does not respond to `X` at all | Fix `X` at a physically sensible value and remove it from the stage. Its fitted value is a starting guess wearing a result's clothes. |
| `A ~ B  r = +1.0000  DEGENERATE` | Only the combination of `A` and `B` is determined | Fix one of them from physics or from a datasheet, or add a measurement that separates them — another temperature, another geometry, another bias. More optimizer budget will not help. |
| A large `condition number` with no single bad pair | The set is collectively over-parameterised | Reduce the stage's free parameters, or split it into two stages against different bias regions. |

The important thing about all four rows: **none of them is visible in the fit
error.** You will not find any of this by looking at how well the curve
matches.

---

## Step 8: read the extracted card

`results/frozen_<spec>.json` holds every extracted parameter. To produce the
model card itself:

```bash
python -c "
import json
from tcadopt.l2_decks.cardgen import render_card
frozen = json.load(open('results/frozen_your_fit.json'))
print(render_card('nsfet_n', frozen, polarity='nmos'))" > nsfet_n.lib
```

Every fit attempt — not just the winner — is in `results/extraction.db`, with
its parameters, its per-sweep errors and its provenance. That database is what
makes the extraction auditable rather than merely finished.

---

## What "done" looks like

You have an extraction you can defend when all four of these are true:

1. **Every stage converged**, with the two error numbers at a level you have
   stated in advance is acceptable for your application. Say what that level is
   *before* you fit, not after.
2. **The identifiability report is clean**, or every degeneracy it reports has
   been resolved by fixing a parameter or adding a measurement — and you can
   say which.
3. **You can name, for every parameter, which measurement determined it** and
   what was held fixed while it was found. Staging gives you this for free; it
   is the reason to stage.
4. **You have stated the scope honestly.** One geometry, one temperature, one
   polarity is a perfectly good deliverable. Silently implying otherwise is not.

---

## Where to go next

- [PARAMETER_EXTRACTION.md](PARAMETER_EXTRACTION.md) — why each piece is built the way it is
- [WRITING_A_PROBLEM.md](WRITING_A_PROBLEM.md) — Part 2, every field of a fit spec
- [TUNING.md](TUNING.md) — "Tuning an extraction", for budgets and parallelism
- [ARCHITECTURE.md](ARCHITECTURE.md) — how one optimizer core serves both jobs
