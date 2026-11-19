# Which number you are minimising

Back to the route map: [GAA_COMPACT_MODEL.md](GAA_COMPACT_MODEL.md)

Before you fit anything, settle this. Three different numbers get called "the
error" in an extraction, all three are correct readings of the same curves,
and they disagree with each other. If you optimise one and report another you
will ship a card that is worse and believe it is better. That happened on this
project, it cost a full step, and the numbers are in this page.

---

## The three numbers

Take one card and eight capacitance curves, 91 points each, 728 points in all.

**One. The mean of the per curve root mean squares.**

For each curve work out the relative root mean square error, then average the
eight. This is what every step of this project reported up to the point the
problem was found.

**Two. The pooled root mean square.**

Put all 728 relative errors in one vector and take its root mean square. No
per curve normalisation anywhere.

**Three. The scorer's own number.**

`CurveResidualScorer` weighs the subthreshold region and the on region
separately about `i_split`. For capacitance it comes out close to the mean of
root mean squares. For current it does not.

On one real card those three read:

| reading | capacitance | current |
|---|---|---|
| mean of the per curve values | 0.026916 | 0.014114 |
| pooled over every point | 0.032142 | 0.013144 |

Neither current number is wrong. The sweeps really are 1.41 per cent out by
one definition and 1.31 per cent out by the other. But only one of them can be
compared against what an earlier log printed, so decide which one you mean and
then never mix them. Every reproduce check in this engine prints both, side by
side, so the two can never be confused again.

---

## Why the mean of root mean squares is the wrong thing to minimise

Because it hides the curve that matters.

An average over eight curves gives each curve one eighth of the gradient. If
one curve carries half of your total error it still gets one eighth of the
attention. That is not a tuning problem, it is arithmetic.

What it looked like in practice. A fit ran 23 parameters for two and a half
hours against the mean of eight root mean squares. The worst curve was Cgd at
the low drain bias, carrying 48.5 per cent of the total error. After the fit:

```
   Cgd at the low drain bias   6.32996  ->  6.32985 per cent
```

The fit was not stuck and the optimiser was not broken. It was pointed at the
wrong thing, and it spent its gradient on seven curves that were nearly right
already.

---

## Why the pooled number is the right thing

Minimise the pooled sum of squares over every point and a curve's share of the
gradient equals its share of the error. Automatically. For every iteration.
With nothing stored anywhere that can go out of date.

That last clause is the whole reason, and the next section is why.

---

## The trap: weights that go stale

The obvious repair for the mean of root mean squares is to weight the curves
by how much error each one carries. Work out each curve's share of the total
sum of squares, turn that into a weight, and the worst curve finally gets the
gradient it deserves.

It works for exactly one card.

Here is what the weights looked like, computed from one card's residuals:

| curve | sum of squares | share | weight |
|---|---|---|---|
| Cgd at Vd 0.05 | 0.364610 | 48.5 % | 3.878 |
| Cgs at Vd 0.05 | 0.121903 | 16.2 % | 1.297 |
| Cgg at Vd 0.05 | 0.099799 | 13.3 % | 1.062 |
| Cgb at Vd 0.05 | 0.085184 | 11.3 % | 0.906 |
| Cgs at Vd 0.60 | 0.046058 | 6.1 % | 0.490 |
| Cgg at Vd 0.60 | 0.019411 | 2.6 % | 0.206 |
| Cgb at Vd 0.60 | 0.014820 | 2.0 % | 0.158 |
| **Cgd at Vd 0.60** | **0.000309** | **0.0 %** | **0.020** |

Look at the last row. Cgd at the high drain bias was at 0.184 per cent, which
is as close to perfect as anything in this project ever got. Its weight came
out 0.02.

**A weight of 0.02 does not mean "this curve is nearly perfect". To an
optimiser it means "this curve does not matter."**

The run then found a card that improved the four low bias curves by 20 to 44
per cent and destroyed the four high bias curves by 159 to 262 per cent. It
checked its weighted score, saw it fall from 0.046394 to 0.038602, and kept
the card. The honest pooled error went the other way, from 0.032142 to
0.034768. The card that shipped was 8.17 per cent worse than the one the step
started from, and the log said the step had succeeded.

The weights were a photograph of which curves were broken on one particular
card. The run then changed the card. Every weight was out of date from that
moment on, and nothing in the machinery knew.

**The rule: never optimise against a stored weight.** Either recompute the
weights at every single iteration, which is extra machinery that can still be
got wrong, or use the pooled residual, which needs no weights at all.

`tcadopt/l6_verify/floor.stale_weights` exists to catch this case if you do
use weights. It compares a stored weight set against the curves as they are
now and tells you which weights no longer describe anything.

---

## Building the pooled residual

The aligner in `tcadopt/l5_opt/lm_align.py` takes a residual function. Give it
this one and it is minimising the pooled error and nothing else:

```python
import numpy as np

def pooled_residual(row):
    """One entry per point over the capacitance curves, no normalisation.

    The sum of squares of what this returns IS the pooled error times the
    number of points, so minimising it minimises the number you report.
    """
    curves = row.get("curves") if isinstance(row, dict) else row
    if not curves:
        return None
    out = []
    for name in CV_NAMES:                  # your eight capacitance curves
        got = curves.get(name)
        if got is None or name not in TARGETS:
            return None
        model = np.asarray(got[1], float)
        dev = np.asarray(TARGETS[name]["i"], float)
        if model.shape != dev.shape or dev.size == 0:
            return None
        scale = float(np.max(np.abs(dev)))
        live = np.abs(dev) > max(scale * 1.0e-9, 1.0e-30)
        out.append((model[live] - dev[live]) / dev[live])
    return np.concatenate(out) if out else None
```

And the number you report, from the same arithmetic:

```python
def pooled(curves, names):
    total, n = 0.0, 0
    for name in names:
        got = curves.get(name)
        ss, k = FL.rel_ss(got[1], TARGETS[name]["i"])   # l6_verify/floor
        total += ss
        n += k
    return (total / n) ** 0.5 if n else None
```

---

## The check that takes one simulation and saves a run

Before you fit, prove that the residual you handed the optimiser really is the
number you are going to report. Simulate your starting card once, build the
residual, and compare:

```python
r = pooled_residual(row)
own = float(np.sqrt(np.mean(r ** 2)))
mine = pooled(curves, CV_NAMES)
print("%d entries, residual says %.8f, I report %.8f, difference %.2e"
      % (len(r), own, mine, abs(own - mine)))
assert abs(own - mine) < 1.0e-7
```

On the real device that printed:

```
728 entries over the eight capacitance curves
its own pooled value        0.02833136
what this step reports      0.02833136
difference                  0.00e+00   the same number
```

If those two disagree, stop. The optimiser is minimising something you are not
measuring, and whatever it hands back will be judged by a different standard
than the one it worked to.

There is a second, independent confirmation available for free. A
Levenberg Marquardt run prints its own starting sum of squares, `S0`. That
should equal your pooled value squared, times the number of points. On this
device `S0` came back as 0.5843409 and `728 * 0.028331362 ** 2` is 0.5843409.
When those match you know the whole chain is consistent: your residual, the
optimiser's objective and the number in your report are one number.

---

## What to report

Report all of it. The engine prints every card four ways on purpose:

```
      what                        Step 32    this step     change
      the eight, mean of rms      0.026916     0.024302    -9.71 %
      the eight, POOLED           0.032142     0.027146   -15.54 %
      the sixteen curve total     0.024116     0.020996   -12.94 %
      the eight current sweeps    0.014114     0.014114    +0.00 %
      the eight, total in aF      2.617306     2.204624   -15.77 %
```

The last line is worth as much as the rest. A relative error flatters a small
curve and punishes it for nothing: Cgd at the high drain bias going from 0.184
to 1.000 per cent sounds like a disaster and is 0.026 to 0.140 attofarads on a
curve whose own root mean square is 14 attofarads. A circuit built on the card
feels attofarads. Print both columns and let the reader see the trade.

---

Next: [The rule that decides what may change the card](GAA_THE_RULE.md).
