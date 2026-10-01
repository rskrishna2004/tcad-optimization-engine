# Your first run

Back to the route map: [GAA_COMPACT_MODEL.md](GAA_COMPACT_MODEL.md)

One command at a time, with what every printed line means. Do not skip ahead.
Each step here is cheap, and each one catches a class of problem that is
expensive to find later.

---

## Step 0. Confirm the engine is installed

```bash
cd tcad-optimization-engine
python check_setup.py
```

**You should see** your Python version, the three required packages, the
engine version, and a line for each configurable tool. The tool lines saying
`NOT SET` is fine at this point.

If `python` is an old interpreter on your simulator host, that is expected and
supported. The default optimizer backend needs only numpy and scipy and runs on
Python 3.6.

---

## Step 1. Run the self-check, with no simulator at all

```bash
python examples/extraction_demo/run_demo.py
```

This runs the complete staged extraction against a stand-in transistor with a
known answer and known built-in degeneracies. No circuit simulator is
involved. It takes seconds.

It proves the engine imports and the loop runs. It proves nothing about your
device, and the demo says so itself.

### Reading the output

A stage header looks like this:

```
STAGE s1_electrostatics  free=4  frozen=0  sweeps=1  backend=scipy_gp_v4_tr
```

- `free` is how many parameters this stage may move
- `frozen` is how many earlier stages have already fixed
- `sweeps` is how many reference curves this stage is scored on
- `backend` is which optimizer is driving

Then the result:

```
STAGE COMPLETE  error = 0.07568
   sub-threshold  0.0706 decades   17.6 %
   on state       0.0051            0.51 %
```

Two numbers, not one, and this is deliberate. Below a current threshold the
error is measured in **decades**, because down there the current changes by
orders of magnitude and a percentage is meaningless. Above it the error is
measured as a **fraction**. One measure cannot serve eight decades of current,
and when a fit stalls the two numbers tell you which half stalled.

The demo will also report that two of its parameters came out badly wrong, by
73 percent and 221 percent. **That is the correct result.** Those two are
deliberately degenerate with a third in the stand-in model, so the data cannot
separate them. The point of the demo is that the identifiability report catches
it. A fit can be perfect and meaningless, and this is what that looks like.

---

## Step 2. Point the engine at your circuit simulator

```bash
export TCADOPT_SPICE_TOOL="hspice"
export TCADOPT_SPICE_TIMEOUT=300
```

If the tool is not on your PATH, give the full path instead:

```bash
export TCADOPT_SPICE_TOOL="/opt/synopsys/hspice/bin/hspice"
```

Then check:

```bash
python check_setup.py
```

**You should see** the SPICE tool line now showing your value instead of
`NOT SET`.

These exports last only for the terminal you typed them in. Put them in your
shell profile if you do not want to retype them, and remember that a dropped
SSH session means a new terminal.

---

## Step 3. Load your targets and read the summary

You did this at the end of
[GAA_REFERENCE_DATA.md](GAA_REFERENCE_DATA.md). Do it again here, because this
is the last cheap moment to catch a data problem.

```bash
python -c "
from tcadopt.l3_exec.targets import load_targets, summarize
t = load_targets('targets/iv_targets.csv', 'targets/cv_targets.csv')
print(summarize(t))
"
```

**You should see** every sweep name, its point count, and the excluded-row
count. Read the sweep names. If there is one you do not recognise, a `bias`
value in your CSV is wrong.

---

## Step 4. Write your fit specification

One YAML file describes what to fit and in what order. The shape:

```yaml
fit:
  iv_targets: targets/iv_targets.csv
  cv_targets: targets/cv_targets.csv
  models:
    nsfet_n: nsfet_n          # sweep device name -> model card name
  i_split_A_per_um: 1.0e-7    # below this, error in decades; above, fraction
  structures:
    nsfet_n:
      version: 111.21
      geomod: 5
      ngaa: 4
      wgaa: 10.0e-9
      tgaa: 5.0e-9
      tsus: 10.0e-9
      l: 12.0e-9
      eot: 0.734e-9
      toxp: 0.734e-9
      epsrox: 3.9
      lsp: 5.0e-9
      epsrsp: 7.5
      nbody: 1.0e21
      nsd: 1.0e26
      bulkmod: 0
      cvmod: 0
      shmod: 0
      tnom: 26.85

stages:
  s1_electrostatics:
    sweeps: [nsfet_n_IdVg_0.05]
    budget: {parallel: 8, max_evals: 120, init_n: 24}
    parameters:
      phig:  [4.35, 4.65, lin, eV]
      cit:   [0.0, 5.0e-3, lin, F/m2]
      cdsc:  [1.0e-4, 1.25, log, F/m2]
```

Two rules about parameter ranges:

1. **A range is a claim about what is fabricable or physical.** Do not widen a
   range just because the fit wants to go there. If a parameter ends up hard
   against the end of its range, that is information, and the answer is usually
   that something else is wrong, not that the range is too tight.
2. **Use `log` for anything that spans orders of magnitude.** Mobility,
   velocity, resistance, the `CDSC` family. Use `lin` for work function,
   exponents and anything that can go negative.

The full field-by-field reference is in
[WRITING_A_PROBLEM.md](WRITING_A_PROBLEM.md).

---

## Step 5. Run the first stage alone

Never run the whole schedule first. Run stage 1, look at it, then continue.

```bash
python -m tcadopt.l8_orch.run_fit problems/your_fit.yaml --stage 1
```

### If it says `0/N ok`

Every simulation failed. Go and look at one:

```bash
ls runs_fit/fit_s1_electrostatics_init000/
cat runs_fit/fit_s1_electrostatics_init000/*.lis | grep -i error
```

The three usual causes, in the order they happen:

- the simulator is not on your PATH in this terminal, so nothing ran at all
- the version line is missing or wrong, so `GEOMOD=5` was rejected
- a deck has content above line 1's title, so the title is being parsed as a
  circuit element

All three are covered in
[GAA_TROUBLESHOOTING.md](GAA_TROUBLESHOOTING.md) with the exact messages.

### If it ran, verify the deck before you believe the number

```bash
grep -i "version\|geomod\|phig" runs_fit/fit_s1_electrostatics_init000/*.lib
```

**You should see** your version, `geomod=5`, and a work function inside the
range you gave. This project lost eleven hours of compute to a stale deck. Two
seconds here.

---

## Step 6. Run the whole schedule

```bash
python -m tcadopt.l8_orch.run_fit problems/your_fit.yaml
```

Each stage prints a header showing what it freed and what it inherited frozen:

```
STAGE s2_short_channel  free=5  frozen=4  sweeps=2
   frozen from earlier: phig, cit, cdsc, nfactor
   scored on: nsfet_n_IdVg_0.05, nsfet_n_IdVg_0.60
```

Everything a stage extracts is written out, so you can stop and resume:

```bash
cat results/frozen_your_fit.json
python -m tcadopt.l8_orch.run_fit problems/your_fit.yaml --stage 3
```

A stage that does not converge freezes nothing. That is on purpose. A half
finished stage handing a bad number to the next one is worse than stopping.

---

## Step 7. Watch it without stopping it

Start it detached and follow the log:

```bash
nohup python -m tcadopt.l8_orch.run_fit problems/your_fit.yaml > run.txt 2>&1 &
tail -f run.txt
```

Ctrl-C stops the watching, not the run.

Three lines worth watching for:

- `batch done: N/N ok` with the two numbers equal. If the second number drops,
  simulations are failing and you want to know now.
- the stage error falling. If it goes flat in the first two rounds, the
  parameters this stage frees probably do not affect the sweeps it is scored
  on.
- a gate verdict, `ACCEPTED` or `rolled back`. A rollback is the engine working,
  not failing. It means the stage made things worse overall and the previous
  card was kept.

---

## Step 8. Read the card

```bash
python -c "
import json
from tcadopt.l2_decks.cardgen import render_card
frozen = json.load(open('results/frozen_your_fit.json'))
print(render_card('nsfet_n', frozen, polarity='nmos'))
" > nsfet_n.lib
```

Open it and read every line. This is the deliverable, and reading it once is
how you notice a parameter sitting exactly on the end of its range.

Everything that ran is also in `results/extraction.db`, so nothing is lost and
nothing is ever repeated.

---

## What to do next

You have a card and a number. Neither is finished until you know what the
number means.

- to understand why the stages are in that order:
  [GAA_EXTRACTION_ORDER.md](GAA_EXTRACTION_ORDER.md)
- to fit the capacitance side: [GAA_FREE_ZONE.md](GAA_FREE_ZONE.md) and then
  [GAA_CHARGE_PARTITION.md](GAA_CHARGE_PARTITION.md)
- to find out whether your numbers mean anything:
  [GAA_CHECKING_RESULTS.md](GAA_CHECKING_RESULTS.md)

**Next:** [The extraction order](GAA_EXTRACTION_ORDER.md)
