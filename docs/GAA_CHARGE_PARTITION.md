# Charge partition, the hard part

Back to the route map: [GAA_COMPACT_MODEL.md](GAA_COMPACT_MODEL.md)

Everything up to here is the well-trodden part. This page is where a
gate-all-around compact model actually gets difficult, and where the standard
model has a limitation you will have to decide what to do about.

Read [GAA_FREE_ZONE.md](GAA_FREE_ZONE.md) first.

---

## What charge partition means

There is a sheet of inversion charge in the channel. When the gate voltage
changes, that charge changes, and the extra charge has to come in from
somewhere. It comes in from both ends, from the source and from the drain, and
the question is how much from each.

The answer depends on drain bias.

- **At a drain bias of zero** the two ends of the channel are at the same
  potential, so a change in gate voltage adds the same charge at each end. The
  split is fifty fifty.
- **At a high drain bias** the drain end of the channel is pinched off. There
  is no charge there to modulate. The split collapses towards the source end,
  and the drain's share goes to nearly zero.

So the drain's share of the channel charge, swept against drain bias, is a
direct picture of how the model saturates. It is the single most informative
number on the charge side.

---

## How to compute it

You need the gate row at two biases, and you need the parasitic floor removed.

```
at a gate bias with no channel:       Cgd_off,  Cgs_off       (the floor)
at a gate bias well above threshold:  Cgd_on,   Cgs_on

Cgd_channel = Cgd_on - Cgd_off
Cgs_channel = Cgs_on - Cgs_off

drain share = Cgd_channel / (Cgd_channel + Cgs_channel)
```

Subtracting the floor matters. The overlap and fringe capacitances do not
depend on the channel at all, so leaving them in dilutes the number you are
trying to read.

The engine does this for you:

```python
from tcadopt.l9_report.gaterow import split, format_split
s = split(model_row, at_vg=0.60, vg_off=-0.20)
print(s["frac_d"])    # the drain's share, as a fraction
```

### What the numbers should look like

Measured on a real 4-sheet nanosheet nFET in TCAD:

| drain bias | drain's share of channel charge |
|---|---|
| 50 mV | 48.2 percent, so almost the fifty fifty you expect |
| 600 mV | 3.9 percent, so almost fully pinched off |

And what the model produced before any of this was understood:

| drain bias | model's drain share |
|---|---|
| 50 mV | 15.7 percent |
| 600 mV | 0.0 percent |

At 50 mV the model was already three quarters of the way to pinch-off at a
bias where the device had barely started. That is one fault, showing up
everywhere, and no amount of adjusting capacitance parameters was going to fix
it, because capacitance parameters change the size of a capacitance and this is
a problem about **where the charge is**.

---

## The one line that tells you immediately

If your deck has `.option list node`, the simulator prints `vdsat` for every
bias. On the capacitance sweep, compare it to the drain voltage the sweep is
held at.

```
model VDSAT on the C-V sweep:  29.8 mV
drain bias the sweep is at:    50.0 mV
```

The model thinks it is saturated before the sweep begins. That is the whole
diagnosis in two numbers, and it is printed for free in every listing you have
ever run.

---

## The ceiling

Here is why the charge saturates early, from the model source. BSIM-CMG
computes the charge's saturation voltage like this, at lines 2086 to 2100 of
`bsimcmg_body.include`:

```
Esats_cv  = 2 * VSATCV_t / u0_cv * Dmobs_cv
EsatLs_cv = Esats_cv * Leff
T6        = KSATIV_a * (qis_cv + 2 * Vtm)
Vdsat_cv  = EsatLs_cv * T6 / (EsatLs_cv + T6)
```

That last line is a harmonic combination of two quantities. A harmonic
combination is always smaller than either of them. So:

```
Vdsat_cv  <  T6  =  KSATIV * (qis_cv + 2 * Vtm)
```

**`KSATIV` is a hard ceiling on the charge's saturation voltage.** `VSATCV`,
`U0CV`, `UACV` and `UDCV` can only push `Vdsat_cv` up **towards** that ceiling.
None of them can lift it.

On this project's card, `KSATIV` was 0.2619 and `(qis_cv + 2*Vtm)` was about
0.20 V, which puts the ceiling at 52.3 mV, against a capacitance sweep taken at
50 mV. The model had no room at all.

### The test that confirms it

Do not argue about this, measure it. Take the four parameters that push
`Esats_cv` and push them ten times further out than any sensible range, one at
a time and then all together, and read the drain's share.

On this project the answer was that the most any of it bought was **0.3
percentage points** of drain share, against a gap of about 30 points. The
capacitance-only family is exhausted, exactly as the ceiling says it must be.

Four simulations, and the question is settled.

---

## The parameter the two sides have to share

`KSATIV` appears twice in the model:

```
line 1901   T6 = KSATIV_a * (qis    + 2*Vtm)     the CURRENT's saturation voltage
line 2089   T6 = KSATIV_a * (qis_cv + 2*Vtm)     the CHARGE's  saturation voltage
```

Same parameter. And the two sides want different values.

Measured on this project, sweeping `KSATIV` with everything else held:

| KSATIV | drain share at 50 mV | Cgg at 600 mV |
|---|---|---|
| 0.02 | 0.02 percent | 51.74 aF |
| 0.26 (what the current fit chose) | 15.7 percent | 49.44 aF |
| 1.06 | 39.9 percent | 45.10 aF |
| 4.0 | 43.4 percent | 44.45 aF |
| **the device** | **48.2 percent** | **45.135 aF** |

Around `KSATIV` near 1 the model's saturation capacitance lands on the device's
to better than a tenth of a percent, and the charge partition nearly fixes
itself. But the current fit, optimising the eight current sweeps, drove it to
0.26.

This is the limitation worth writing down in your report. **BSIM-CMG 112.1.0
gives the charge its own private copy of `VSAT`, `U0`, `UA`, `UC`, `UD` and
`ETA0`, and no private copy of `KSATIV`.** On a device where the current and
the charge want different saturation voltages, the model cannot satisfy both,
and that is a property of the model rather than of your extraction.

---

## Why a gate cannot decide this, and what to do instead

A gate asks "is everything no worse than before?". For a shared parameter the
answer is almost always no, because one side is already good and the other is
not. The run stops and you learn nothing about whether the trade was worth
making.

On this project a gate was asked that question twice about `KSATIV` and
answered "plus 15 percent" and "plus 18 percent" both times. Both true. Both
useless.

So do not gate it. **Price it.** That is what `tcadopt/l5_opt/trade.py` is for.

### How pricing works

Pick a ladder of values for the shared parameter. At each value:

1. **Freeze** the shared parameter there.
2. **Completely re-fit the other side on its own sweeps alone**, to
   convergence, with the first side not in the objective at all.
3. **Only then** read both sides.

Step 2 is the whole point. Without it, the ladder measures "the card was not
built for this value", which is true and useless. With it, the ladder measures
the only thing that matters: how much accuracy the other side actually loses
**after it has been given its chance to recover**.

```python
from tcadopt.l5_opt.trade import trade_curve, format_curve, knee, cap_ladder

rows = trade_curve(ladder, refit, read, log=print, label="ksativ")
print(format_curve(rows, "ksativ", order=[...], targets={...}))
print(format_knee(knee(rows, "IV_err", "share", cost_cap=cap,
                       gain_target=device_share), "ksativ"))
```

### Read the answer three ways

One cost cap is one opinion wearing a number, so look at the trade from three
angles.

**In fit units.** The raw table: what the current error is at each rung, and
what the charge gets in return.

**Under several caps.** `cap_ladder` applies the same rule at a ladder of cost
caps. If the pick is the same at plus 10 percent and plus 100 percent, the cap
is not what decided it. If the pick moves with the cap, the cap **is** the
decision and you should choose it deliberately rather than taking a default.

**In millivolts and percent.** The fit error is an internal number. What gets
signed off is threshold voltage error and on current error. Read the ladder
against plain accuracy budgets, for example within 2 mV and 2 percent, within
5 and 5, within 10 and 10, and see which rung survives each.

### There is no wrong answer

If the table says the charge can be fixed for a millivolt or two of threshold
voltage, take it.

If it says the current will not pay at any price, that is a real and
reportable result: this device's current and charge want saturation voltages
far enough apart that a model with one shared `KSATIV` cannot serve both, and
here is the measured price of that.

Either way you have a number instead of an argument, and the trade curve goes
in the report.

---

## Things the gate row will teach you that the total will not

Three findings from this project, all invisible in `Cgg` alone:

**The two sides of a symmetric model are not the two sides of a real device.**
`CGDO` defaults to `CGSO` and `CFD` defaults to `CFS`, so unless you set both
explicitly the model's drain-side and source-side floors are exactly equal. The
real device's differed by 0.21 aF.

**Gate to body capacitance can be wrong by 84 percent and hide completely.**
With `BULKMOD=0` the model's `Cgb` is a constant, set by
`(CGBO*nf*ngcon + (CGBN + CGBW*WGAAeff)*NFINtotal) * Lg` at line 933. The
device's fell from 1.93 to 1.41 aF across the gate sweep. The best a constant
can do is one number in the middle, which takes the error from 84 percent to
about 8.8 percent. Getting the shape right needs `BULKMOD` on, which is a
structural change and deserves its own stage.

**`CGDL` is the only pure drain-side knob in the model.** Measured, it moved
`Cgd` by 15.07 aF at low drain bias and 8.90 aF at high drain bias while moving
`Cgs` by exactly zero. If you need to move one side without the other, that is
the parameter.

And one warning attached to that last one. `CKAPPAS` and `CKAPPAD` shape how
`CGSL` and `CGDL` depend on bias, and they appear **only inside the `CGSL` and
`CGDL` brackets**. With `CGSL` at zero the whole bracket is multiplied by zero
and `CKAPPAS` can do nothing. This project surveyed those two parameters three
separate times with `CGSL` and `CGDL` at zero, called them dead all three
times, and was measuring the zero rather than the parameter. When you survey a
parameter that only multiplies another term, switch the other term on first.

**Next:** [Checking the result](GAA_CHECKING_RESULTS.md)
