# Checking the result

Back to the route map: [GAA_COMPACT_MODEL.md](GAA_COMPACT_MODEL.md)

You have a card and a small error number. This page is about everything you
have to check before you are allowed to believe it.

The short version: **a low fit error is necessary and nowhere near
sufficient.** A degenerate fit fits perfectly. An unphysical card can fit
perfectly. A card that reproduces your eight sweeps and nothing else can fit
perfectly.

---

## 1. Identifiability: could the data have determined this number

This is the check that the fit error structurally cannot do for you.

If two parameters have the same effect on your data, any change in one can be
undone by a change in the other. The fit error does not move. The optimizer
returns one of infinitely many equally good answers, and which one depends on
where it started.

So it has to be measured separately. The engine builds the Jacobian of the
residual around the extracted point and reports three things.

```bash
python - <<'EOF'
from tcadopt.l1_spec.curve_scorer import CurveResidualScorer
from tcadopt.l3_exec.targets import load_targets
from tcadopt.l3_exec.spice_exec import HSpiceEvaluator
from tcadopt.l6_verify.identifiability import jacobian, analyse, report
# build scorer, targets and evaluator for the stage you want to check,
# then:
names = ['phig', 'cit', 'cdsc', 'nfactor', 'u0', 'ua', 'vsat', 'rdswmin']
J = jacobian(...)
print(report(analyse(J, names)))
EOF
```

### What it reports and what to do

| it reports | what it means | what to do |
|---|---|---|
| a parameter with near-zero sensitivity | the data barely responds to it | do not report it as measured. Fix it at its default and say so. |
| a pair with correlation near plus or minus 1 | the two are interchangeable | report the combination, not the two numbers |
| effective rank below the number of free parameters | the data contains fewer independent directions than you freed | free fewer parameters, or add a sweep that separates them |
| a condition number in the thousands | the fit is numerically fragile | the same answer as above |

### A worked example from this project

Nine free parameters, effective rank 7. Two directions lost. The report named
them:

```
NOT MEASURED by this data: vsat
degenerate pairs:
   cit  ~ cdsc      r = +1.0000
   cdsc ~ nfactor   r = +1.0000
   cit  ~ nfactor   r = +1.0000
   eta0 ~ dsub      r = -0.9969
   vsat ~ rdswmin   r = -0.9043
```

That is not a failure. It is the correct and useful answer. The three
subthreshold parameters all push the slope the same way, so what the data
determines is a combination of them. The engine recovered the combinations:

```
swing group:  n = 1 + 0.25*NFACTOR + 60*CIT + 25*CDSC     determined to 2.69 %
DIBL group:   d = ETA0 * exp(-DSUB)                       determined to 0.16 %
```

`ETA0 * exp(-DSUB)` is determined to 0.16 percent. `ETA0` on its own is not
determined at all. Report the first, not the second.

### What to write in a report

Not "ETA0 = 0.325". Write:

> The DIBL group ETA0 * exp(-DSUB) is determined by this data to 0.16 percent.
> The individual values of ETA0 and DSUB are not separately identifiable from
> four Id-Vg sweeps, with a measured pairwise correlation of minus 0.997, and
> the values reported are one point on that line.

That is a stronger claim than a number, because it is true.

---

## 2. Physicality: does the card describe a real device

Some parameter combinations are impossible, not just unlikely. The physics
guard checks every result against invariants that cannot be violated.

The one that catches the most is the subthreshold slope limit. At temperature
T the slope cannot be steeper than

```
SS_min = ln(10) * k * T / q       which is 59.6 mV/dec at 300 K
```

A model reporting 20 mV/dec is not a good model, it is a broken one, and it
should never be allowed into the surrogate the optimizer learns from.

Others worth checking, and all cheap:

- on current above off current, by the number of decades your device has
- current monotonic in gate voltage in an Id-Vg sweep
- current monotonic in drain voltage in an Id-Vd sweep, before the knee
- signs consistent between the two polarities
- capacitances positive where they should be

The engine runs these automatically and quarantines a trial that fails, so a
broken simulation never poisons the search.

One caution from experience: check the guard is actually firing. On this
project the physics guard silently did nothing for a long time because the
knowledge base file it looked for was at the wrong path and a missing file
returned an empty rule set. Every trial passed, including one at 20 mV/dec.
If your guard has never rejected anything, test it by feeding it something that
should fail.

---

## 3. Distance from default: is this parameter doing someone else's job

Every BSIM-CMG parameter has a declared default. That default is a
representative value from the model's own authors, so a parameter that has
travelled a long way from it is worth a question.

The check is simple: for each fitted parameter, compare it to its default.
Flag anything more than a factor of ten away for a log parameter, or 50
percent away for a linear one.

Being far from default is **not wrong**. A short-channel gate-all-around device
genuinely is different from whatever the default was chosen for. But it is a
question, and it needs an answer per parameter, in writing:

> Does this device have a reason to be that different, or has this parameter
> absorbed an error that belongs somewhere else?

The second case is the common one. A parameter that has run to a factor of
twenty from its default is usually standing in for a term that is missing,
switched off, or being modelled in the wrong stage.

The engine reads the defaults out of the simulator's own parameter listing,
rather than from a table someone typed, so the comparison is against what your
installation actually implements.

---

## 4. The figures of merit, against your device

The residual is the objective. These are what a person reads.

| quantity | what to compare | what is good |
|---|---|---|
| threshold voltage | model against device, at every drain bias | within a few mV |
| subthreshold slope | at every drain bias | within about 1 mV/dec |
| on current | at the highest gate and drain bias | within a few percent |
| DIBL | the threshold voltage shift per volt of drain bias | within a few mV/V |
| the DIBL slope across biases | how DIBL itself changes | this one is hard, and worth reporting honestly |

Extract these from the fitted card and print them next to the device's. If the
residual is small and the threshold voltage is out by 20 mV, something is wrong
with the objective, not with the device.

---

## 5. The band report: where the error lives

A single number per sweep hides where the error is. Split each sweep into
bands and report the signed error in each:

```python
from tcadopt.l9_report.where import bands
print(bands(target, model))
```

Signed matters. An error of plus 5 percent in one band and minus 5 percent in
another averages to zero and is a real problem. Two errors of plus 5 percent
are a different problem with a different cause.

Reading the band report is how you tell a threshold voltage error from a
mobility error from a resistance error, without guessing.

---

## 6. The ledger: what each stage actually bought

Keep a running table of every stage, whether its result was kept or rolled
back, and the error after it. It takes one line per stage and it answers the
question everybody asks at the end, which is "where did the improvement
actually come from".

A real one from this project:

```
the card this step starts from                 kept         0.266686
PART 3 -- the parasitic floor                  kept         0.063952
PART 4 -- the C-V core at CVMOD = 1            kept         0.058505
PART 5 -- the bias-dependent overlap           rolled back  0.060551
PART 6 -- shared knobs, pull 1e-05             rolled back  0.023445
```

Two rollbacks in that ledger turned out to be a bug in the engine rather than
bad stages, and it was the ledger that made it obvious: two stages in a row
finding large improvements and both being refused is a pattern, not bad luck.
See the gate warning in
[GAA_EXTRACTION_ORDER.md](GAA_EXTRACTION_ORDER.md).

---

## What finished looks like

Four things, all of them required.

1. **Every stage converged**, against an error level you stated before you ran
   it rather than after you saw it.
2. **The identifiability report is clean, or its findings are written into the
   result.** Degeneracies do not have to be absent. They have to be stated.
3. **Every reported parameter is traceable to a measurement.** You can name the
   sweep, the bias region and the stage that determined each one. Anything you
   cannot trace is a fixed value, and it is reported as a fixed value.
4. **The scope is stated honestly.** This card reproduces these sweeps, at this
   temperature, over these bias ranges, for this geometry. It has not been
   checked outside that, and saying so is not a weakness.

---

## What is not checked, and you should say so

Unless you have done extra work, your card has not been checked for:

- **temperature**, unless you fitted at more than one
- **self-heating**, unless `SHMOD` was on
- **geometry scaling**, unless you fitted more than one channel length
- **the opposite polarity**, which is a separate extraction
- **noise**, which uses its own parameters and its own measurements
- **transient and large-signal behaviour**, which a DC and small-signal fit
  does not exercise
- **circuit-level accuracy**, which is a different question from curve accuracy

A card with four honest limitations stated is more useful than a card with
none stated, because the reader knows what they are holding.

**Next:** [When it goes wrong](GAA_TROUBLESHOOTING.md)
