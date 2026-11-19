# A worked extraction, start to finish

Back to the route map: [GAA_COMPACT_MODEL.md](GAA_COMPACT_MODEL.md)

Everything in Path C came out of one extraction. This page is that extraction,
with the real numbers, including the eight things that went wrong and what
each one cost. It is here because the failures are more useful than the
result, and because every rule in the other pages looks arbitrary until you
see the run that produced it.

Read it after your first run, not before. It will mean much more once you have
seen your own log.

---

## The device

A 4 sheet gate all around nanosheet nFET, built in Sentaurus.

| | |
|---|---|
| sheets | 4, one stack |
| sheet width and thickness | 10 nm and 5 nm |
| sheet pitch | 15 nm, so a 10 nm gap |
| channel length | 22 nm, of which 12 nm is gated |
| gate stack | 0.5 nm SiO2 plus 1.5 nm HfO2, EOT 0.734 nm |
| spacers | Si3N4, 5 nm each side |
| channel doping | boron 1e15 |
| source and drain | arsenic 1e20 |
| gate | TiN, work function 4.4432 eV |
| substrate | bulk silicon, boron 1e15, with its own contact |

One detail is worth pulling out because it was argued about for a week. The
structure has a 3 nm SiO2 plug under the gate only, for bottom dielectric
isolation. That plug is **not** a buried oxide and it does not make the device
silicon on insulator. The structure script says `(define EnableBOX 0)`, the
substrate is real and has its own contact, so the body terminal exists and the
gate to substrate charge is bias dependent. That means `bulkmod = 1`.

Setting `bulkmod = 0` would have been the easy mistake. It makes Cgb a
constant in BSIM-CMG, and the device's Cgb is not constant: it falls
monotonically from 1.93 to 1.41 attofarads across the gate sweep. Getting this
one switch right is worth more than any fit in this guide.

---

## The reference data

Sixteen curves, 1532 points.

- four IdVg sweeps at Vd 0.05, 0.20, 0.40 and 0.60 V
- four IdVd sweeps at Vg 0.38, 0.45, 0.53 and 0.60 V
- two Cgg sweeps at Vd 0.05 and 0.60 V
- the gate row at both drain biases, so Cgd, Cgs and Cgb, six more curves

The circuit simulator was PrimeSim HSPICE with BSIM-CMG LEVEL 72
VERSION 111.21, GEOMOD 5, `bulkmod 1`, `cvmod 1`.

The six gate row curves are the reason this extraction found anything. Fitting
only the two Cgg sweeps hides the error, because Cgd being too small and Cgs
being too large cancel in the total.
[The reference data page](GAA_REFERENCE_DATA.md) has the arithmetic.

---

## The milestones

| | current | capacitance, mean | capacitance, pooled | sixteen curves |
|---|---|---|---|---|
| after the current fit | 0.014117 | 0.040472 | 0.048541 | 0.034790 |
| after the first charge fit | 0.014114 | 0.026916 | 0.032142 | 0.024116 |
| a step that regressed | 0.014114 | 0.029940 | 0.034768 | 0.025789 |
| after the overlap work | 0.014114 | 0.026569 | 0.028455 | 0.021805 |
| after the parameter walk | 0.014114 | 0.026446 | 0.028331 | 0.021728 |
| **after the joint fit** | **0.014114** | **0.024302** | **0.027146** | **0.020996** |

The drain current is identical on every row from the second onward. Not close,
identical, to the last digit printed. That is what the free zone buys you:
[the free zone page](GAA_FREE_ZONE.md) lists the parameters that cannot touch
the current, and every charge step used only those, and then measured that the
current had not moved rather than assuming it.

---

## The eight things that went wrong

### 1. A seed computed from the right physics and the wrong equation

The gate to substrate capacitance needed a starting value for `cgbl`. The
bottom dielectric isolation plug is 3 nm of SiO2 under a known area, so its
plate capacitance is easy, and that number went on the card.

What the model actually does with `cgbl` is multiply it by
`NFINtotal * LeffCV`, which on this device is 1.0845e-8 metres. So a seed of
2.8e-10 put the bias dependent ceiling at 3.04 attofarads on a device whose
Cgb never exceeds 1.93. The fit came out at 79.8 per cent error.

**Cost: the whole of a two and a half hour slot**, because the script called
`sys.exit` when the reproduce check failed.

**What changed:** seed from the model's own declared defaults, never from a
hand calculation, and then measure a derived value against the default on a
ladder and keep whichever wins. `tcadopt/l6_verify/seed.py` is that ladder.
And no measurement anywhere in a run is allowed to end it, which is
[the no stop rule](GAA_THE_RULE.md).

### 2. A closed form solve that modelled one term when there were two

A solve on the measured curves promised that Cgb could reach 1.39 per cent.
The simulator measured 1262 per cent on the card it proposed.

The arithmetic was not wrong about its own term. There were two terms. Besides
the gate to substrate overlap, BSIM-CMG puts the channel's **accumulation**
charge on the body node. That branch is dormant while the channel is inverted
and it opens as the sweep crosses flatband, and the parameter the solve had
chosen, `delvfbacc = 1.0`, put 98 per cent of the gate sweep below flatband.
The branch is worth up to 61 attofarads on this device, against a measured Cgb
of 1.93.

**Cost: nothing, and that is the point.** A ladder measured the proposed card
against the model's own defaults in one minute, rejected it, and started the
fit from the defaults instead. The run survived because the solve was treated
as a candidate and not as an answer.

**What changed:** `tcadopt/l4_knowledge/cgb_overlap.accumulation_risk`
computes, for any card, how much of your sweep sits below flatband and how
large that dormant branch would be if it opened. It is a four line call and it
would have caught this before the run.

### 3. Writing a value that looked like the default and was not

`vfbsdcv` had never been on the card in 32 steps. Its declared default is
`vfbsd`, which is 0.0, so putting 0.0 on the card looked free.

It is not. The model assigns `vfbsdcv_v = vfbsd_v`, a **computed** variable,
not the declared parameter. `vfbsd_v` is the flatband voltage of the n plus
source and drain, which on this device is about +0.43 V. Writing an explicit
0.0 overrode it.

The log was unambiguous once read properly. The drain current reproduced to
`0.00e+00` on both definitions and only the capacitance moved, from 0.026916
to 0.075682, because `vfbsdcv` is read in exactly two places and both are in
the overlap charge.

**Cost: a run stopped in its first minute**, correctly, by its own reproduce
check.

**What changed:** when a parameter's declared default is a reference to
another parameter rather than a number, do not put the number on the card.
Measure what the model is using instead, which took one extra simulation and
came out at +0.43 V by three independent routes.

### 4. Weights computed from one card, used on another

This is the expensive one and it has [its own page](GAA_THE_OBJECTIVE.md).

The objective was weighted by each curve's share of the error. Cgd at the high
drain bias stood at 0.184 per cent, so it drew a weight of 0.02. It then rose
to 0.667 and nothing objected, because to an optimiser a weight of 0.02 means
the curve does not matter.

The step shipped a card whose weighted score had improved 16.8 per cent and
whose honest pooled error was 8.17 per cent **worse** than the card it started
from. The log said the step had succeeded.

**Cost: one whole step of three hours, plus the step after it, which was spent
finding out what had happened.**

### 5. A guard that only wrapped one of four places a card can come from

The same step had a working guard, around the fit. The ladder that picked the
card before the fit was not guarded, and its pick had a curve 262 per cent
worse than the baseline on a guard that allows 10.

### 6. A revert that went to the wrong card

When the fit in that step was correctly refused, the revert went back to the
unguarded ladder pick rather than to the card the step had started with. Three
later parts then reported their results against a card that had already
regressed, and all three looked reasonable.

Mistakes 4, 5 and 6 were one mistake wearing three hats, and the repair is the
whole of [the rule page](GAA_THE_RULE.md).

### 7. Trusting a variable name

A later step loaded a constant called `CARD32`, believing it was the card step
32 produced. The convention in those scripts is that `CARDnn` is the card step
nn **started** from. It got a card seven steps older.

**Cost: one minute**, because the reproduce check caught it, and then the
repair was to stop reading names altogether and find the baseline by
simulating every candidate. That table is now printed at the start of every
run and the question cannot be asked again.

### 8. Two mistakes calling one optimiser

The first fit on the pooled objective passed `params` as a list of numbers and
got

```
TypeError: cannot convert dictionary update sequence element #0 to a sequence
```

because the aligner does `dict(params)` internally, so `params` is the card.
The second attempt fixed that, tried four conventions, and reported that none
had worked. All four had run. The aligner returns a result dict with the card
under `params`, and the reader was looking at the top level.

**Cost: two runs, about 45 minutes of compute and a lot more of trust.**

**What changed:** [the joint fit page](GAA_THE_JOINT_FIT.md) now documents the
convention exactly, and the probe counts how many simulations each candidate
convention triggers, because three of the four returned a tidy result dict
having simulated one card, which is not enough to have built a Jacobian.

---

## And one mistake that did not happen, because the rule stopped it

An early draft of the acceptance rule had a per curve cap of 0.35 attofarads,
a number chosen by hand because it looked reasonable. The best card available
asked for a rise of 0.3232 attofarads on one curve.

It passed by five thousandths of an attofarad. A slightly different device, or
a slightly worse estimate on my part, and a hand picked threshold would have
thrown away an 11 per cent improvement with a log entry that looked like
diligence.

The rule now reads every threshold off the baseline card instead. That is why
[the rule page](GAA_THE_RULE.md) is so insistent about it.

---

## The finished card, and what is left

```
                                     start      finished    change
  the eight current sweeps         0.014114     0.014114     0.00 %
  the eight capacitance, mean      0.026916     0.024302    -9.71 %
  the eight capacitance, POOLED    0.032142     0.027146   -15.54 %
  the sixteen curve total          0.024116     0.020996   -12.94 %
  the eight capacitance, total aF  2.617306     2.204624   -15.77 %
```

Where the remaining error sits:

```
      curve        per cent      aF      share of what is left
      Cgd 0.05      4.986 %   1.0361       42.2 %
      Cgs 0.60      3.349 %   0.9237       19.0 %
      Cgs 0.05      2.795 %   0.7866       13.3 %
      Cgg 0.05      2.279 %   1.2184        8.8 %
      Cgg 0.60      2.088 %   0.8998        7.4 %
      Cgb 0.05      1.762 %   0.0266        5.3 %
      Cgb 0.60      1.184 %   0.0202        2.4 %
      Cgd 0.60      1.000 %   0.1399        1.7 %
```

The top two lines are 61 per cent of the total and both are the charge
partition. About half of the first is the split, measured, and the whole of
the second's excess is the split landing on Cgs because the drain end is
pinched off there and carries almost no channel charge.
[The charge partition page](GAA_CHARGE_PARTITION.md) is that measurement.

That is the limit. It is a property of BSIM-CMG 112.1.0, which has no charge
partition parameter, and not a property of the fitting. The honest way to
finish an extraction is to be able to write that sentence with a number
attached to it.

---

## What this took

| | |
|---|---|
| getting the reference data right | about a day |
| the current fit | a few hours of compute |
| the charge fit that worked | three hours |
| the eight mistakes above | several days |
| closing the ledger | about three hours of compute across four short runs |

The compute was never the problem. Nearly every hour lost on this project went
to something that was reasoned instead of measured, and every one of those was
eventually caught by a measurement. That is the only lesson on this page worth
carrying to your own device.

---

Back to the route map: [GAA_COMPACT_MODEL.md](GAA_COMPACT_MODEL.md)
