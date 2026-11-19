# Knowing when it is finished

Back to the route map: [GAA_COMPACT_MODEL.md](GAA_COMPACT_MODEL.md)

There is no error value that means finished. Two per cent is excellent on one
device and poor on another, and a run that has stopped improving might be at
the model's limit or might be one parameter away from a much better card.

What you can do is close every direction the card could still move in, one at
a time, each with a measurement. When the list is complete you are finished,
and you can say so with evidence instead of with a feeling. This page is how
to build that list.

---

## The ledger

Write it as a table, and fill the result column with a number some run
produced. Not an opinion, not an estimate. Here is the completed one from this
device, as an example of the shape and the standard.

| | lever | how it was closed |
|---|---|---|
| 1 | the six overlap parameters | each walked one at a time, 30 simulations. Every one already at its best value |
| 2 | `vfbsdcv`, the overlap knee | scanned 0.300 to 1.017 V, 25 cards. Minimum at +0.617 V |
| 3 | `ckappad`, `ckappas`, `ckappab` below 0.02 | the model clamps all three. Curves identical to 0.0000e+00 aF |
| 4 | the overlap symmetry the device has | forcing it costs 23.55 per cent. The model needs the asymmetry |
| 5 | the 27 remaining charge parameters | walked twice over, about 270 simulations. 0.44 per cent in total |
| 6 | every parameter together, on the pooled error | one fit, converged, 4.18 per cent. 0.3 per cent left in the basin |
| 7 | the source and drain charge partition | no parameter in BSIM-CMG moves it. 42 per cent of what remains |
| 8 | the saturation voltage | would fix the channel ratio and costs 38 per cent of drain current error |

Lines 1, 2, 5 and 6 are the ordinary work and the earlier pages cover them.
Lines 3, 4, 7 and 8 are the interesting ones, because each needed a
measurement that is not obvious, and three of them end in a limit rather than
in a number you can improve.

---

## Line 3. Is that bound the model's, or one you drew?

Every fit on this project kept ending with `ckappad` sitting on exactly 0.02.
A parameter that stops dead on a round number is either held there by the
model itself or held there by a lower bound somebody typed into a range. Those
two look identical in a log and they are completely different facts.

If it is the model, the parameter is dead below 0.02 and the question is
closed. If it was only your box, there is room underneath that nobody has
used, and in this case it mattered a great deal, because `ckappad` was the one
parameter in the whole charge model whose two drain biases move in **opposite**
directions, which was the exact shape of the error that was left.

**You do not need the model source to find out.** Put the value on a card,
then put smaller values on cards, and compare the curves:

```python
CLAMP_EPS = 1.0e-9     # attofarads. A real change cannot hide under this.

def maxdiff(a, b):
    """Largest difference between two sets of curves, in attofarads."""
    worst = 0.0
    for name in CV_NAMES:
        ca, cb = a.get(name), b.get(name)
        if ca is None or cb is None:
            continue
        va, vb = np.asarray(ca[1], float), np.asarray(cb[1], float)
        if va.shape == vb.shape and va.size:
            worst = max(worst, float(np.max(np.abs(va - vb))) * 1.0e18)
    return worst

ref = simulate(card_with(name, 0.02))
for v in (0.01, 0.005, 0.001, 1.0e-5):
    moved = maxdiff(simulate(card_with(name, v)), ref)
    print("%-11g  %12.4e aF   %s"
          % (v, moved, "MOVES THE CURVES" if moved > CLAMP_EPS
             else "identical, clamped"))
```

On this device, for all three of `ckappad`, `ckappas` and `ckappab`:

```
      value        worst change vs 0.02      verdict
      0.01           0.0000e+00 aF             identical, clamped
      0.005          0.0000e+00 aF             identical, clamped
      0.001          0.0000e+00 aF             identical, clamped
      1e-05          0.0000e+00 aF             identical, clamped
```

Bit for bit identical. The model clamps them, the knob is dead below 0.02, and
the question is closed for good with twelve simulations and no source reading.

Run this on any parameter that has finished on a suspiciously round number.
It takes minutes and it turns a nagging doubt into a line in the ledger.

---

## Line 4. Does the fit depend on breaking a symmetry your device has?

This one is not about improving the card. It is about knowing what the card's
quality rests on, which a reviewer will ask and which you want to have
measured rather than argued.

The device here is symmetric. The spacer is 5 nm on each side, the ungated
channel is about 5 nm on each side, and the source and drain are both arsenic
at 1e20. Its own curves agree: at the bottom of the sweep, where the channel
is off and the curve is overlap and fringe alone, the device has Cgd 14.1162
attofarads against Cgs 13.9031, which is 1.5 per cent apart.

The card did not agree. It carried

```
      cgdl    2.65881e-10 F/m   an overlap of 5.65 nm
      cgsl    1.04367e-10 F/m   an overlap of 2.22 nm
      a factor of 2.55 apart, on a symmetric device
```

Both lengths are under the 10 nm the structure allows, so neither is
impossible on its own. Their ratio is what cannot be right.

So measure what the symmetry costs. Force `cgdl = cgsl` across a few values,
with `ckappad = ckappas`, and read the pooled error:

```
      ckappa    cgdl = cgsl      pooled     penalty
      0.201463  1.044e-10      0.035157    +23.55 %
      0.02      2.255e-10      0.039324    +38.20 %
      0.02      1.044e-10      0.066983   +135.40 %
      0.201463  2.659e-10      0.145482   +411.26 %
```

Every symmetric card is worse, the best by 23.55 per cent. **So the asymmetry
is load bearing, not an artefact a better objective would remove.** The model
needs it, and the reason is line 7.

That number, 23.55 per cent, is a better result than another decimal place on
the fit would have been. It is an upper bound too: a symmetric card refitted
in its other parameters could only do better than one that was not refitted at
all, so the real dependence is somewhere between zero and 23.55 per cent.

If your own test comes back the other way, and the symmetric card is better,
then the asymmetry was never buying anything, and you should keep the
symmetric card because it is both physical and lower error.

---

## Line 7. The limit that is the model's and not yours

This is the one that ends the extraction, and
[the charge partition page](GAA_CHARGE_PARTITION.md) has the full treatment.
The short version, because it belongs in the ledger:

At the top of each gate sweep, the share of the channel charge that the source
takes:

| | low drain bias | high drain bias |
|---|---|---|
| textbook | 0.5000 | 0.6667 |
| the device | 0.5077 | 0.6693 |
| BSIM-CMG | 0.5459 | 0.6946 |

The device sits on the textbook value at both ends of its range, which is the
sign that the reference data is sound. The model is too far toward the source
at both, and **no parameter on the card moves it.** BSIM4 and BSIM-BULK expose
this as XPART. BSIM-CMG 112.1.0 does not.

Hold the model's own total charge and give it the device's split and the worst
curve goes from 14.18 per cent out to 6.96, so roughly half of the largest
single error in the extraction is this and only this. On the finished card
that curve is 42 per cent of everything that is left.

When a line in your ledger reads like that, it is closed. There is no step
that fixes it, and the honest thing is to put the number in the report.

---

## Line 8. The parameter two halves have to share

The channel charge was 12.6 per cent short at the low drain bias and 19.3 per
cent long at the high one, which one parameter would fix: the saturation
voltage. It is read in both the current equations and the charge equations, so
there is one value and it serves both.

Do not argue about whether to move it. Price it. Let it move, let **every**
current parameter move afterwards to repair the damage, and measure what is
left:

```
      ksativ = 0.904 closes 80 per cent of the high bias gap and still
      costs 38 per cent of drain current error after the repair.
```

Thirty eight per cent, measured, with seventeen parameters free to try to undo
it. That is a refusal with a number attached, and it closes the line. Someone
reading your report can disagree with the decision and cannot disagree with
the measurement. `tcadopt/l5_opt/price.py` and `tcadopt/l5_opt/trade.py` exist
for exactly this.

---

## The determinacy warning

Before you write any extracted value into a table, check whether the data
could have determined it.

One parameter on this device, `qmtcencv`, was successively fitted to 0.0686,
then 9.02, then 0.617, then 2.865 across four steps, moving by factors of a
hundred while the error changed by fractions of a per cent. **That parameter is
not determined by this data.** It belongs in the card because the card needs a
value, and it does not belong in a results table as though it had been
measured.

`tcadopt/l6_verify/determinacy.py` reports this properly, with an interval per
parameter and a list of the pairs the data cannot tell apart. Run it and
report what it says, including the parameters it cannot pin down.
[Checking the result](GAA_CHECKING_RESULTS.md) covers the rest.

---

## What finished looked like here

For a 4 sheet n type nanosheet, sixteen reference curves, against Sentaurus:

```
                                     start      finished
  the eight current sweeps         0.014114     0.014114
  the eight capacitance, mean      0.026916     0.024302
  the eight capacitance, POOLED    0.032142     0.027146
  the sixteen curve total          0.024116     0.020996
  the eight capacitance, total aF  2.617306     2.204624
```

The drain current never moved, bit identical, through every capacitance step.
The capacitance improved 15.5 per cent on the pooled measure and 15.8 per cent
in absolute attofarads. And 42 per cent of what remains is one curve whose
error is about half charge partition, which is line 7.

That is what a closed ledger looks like. Not a small number, a complete list.

---

Next: [Checking the result](GAA_CHECKING_RESULTS.md), and then
[a worked extraction from start to finish](GAA_CASE_STUDY_NFET.md).
