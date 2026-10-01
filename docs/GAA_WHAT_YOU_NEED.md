# What you need before you start

Back to the route map: [GAA_COMPACT_MODEL.md](GAA_COMPACT_MODEL.md)

This page is a shopping list. Work through it before you run anything. Every
hour spent here saves several later, because the engine will happily fit bad
data and give you a confident wrong answer.

---

## 1. The device simulations you must already have

You are extracting a model of a device. The device has to have been simulated
first, and simulated in a specific set of bias conditions. Here is the minimum
set, and why each one is in it.

### Current sweeps

| sweep | what is swept | held fixed | what it pins down |
|---|---|---|---|
| Id-Vg at low Vd | gate voltage, 0 to Vdd | drain at about 50 mV | threshold voltage, subthreshold slope, low-field mobility |
| Id-Vg at two mid Vd | gate voltage | drain at about Vdd/3 and 2Vdd/3 | how threshold moves with drain bias, which is DIBL |
| Id-Vg at high Vd | gate voltage | drain at Vdd | DIBL again, and the saturation on current |
| Id-Vd at low Vg | drain voltage, 0 to Vdd | gate just above threshold | series resistance |
| Id-Vd at three higher Vg | drain voltage | gate up to Vdd | velocity saturation, the knee, output resistance |

Four Id-Vg and four Id-Vd is what this project used and it was enough. Fewer
than three Id-Vg curves and you cannot separate threshold voltage from DIBL,
because with two curves any threshold error can be absorbed into the DIBL
parameter and the fit will not notice.

### Capacitance sweeps

| sweep | what is swept | held fixed | what it pins down |
|---|---|---|---|
| C-V at low Vd | gate voltage | drain at about 50 mV | overlap and fringe capacitance, gate oxide capacitance, the charge in the channel |
| C-V at high Vd | gate voltage | drain at Vdd | how the channel charge moves to the source end as the drain pinches off |

Two is the minimum. You need both because the interesting thing the charge
model does is redistribute charge between the two ends of the channel as the
drain bias rises, and one bias cannot show you that.

### The bias range that people get wrong

**Your C-V sweep must start at a gate voltage where there is no channel.**
Below threshold, well below. Start at 0 V if your device turns on at 0.37 V,
and start at a negative gate voltage if you can.

The reason is worth understanding, because it decides whether the whole
capacitance extraction is possible.

At a gate voltage with no channel, the only capacitance between the gate and
the other terminals is overlap and fringe. Those come from geometry, they do
not depend on bias, and in the model they are set by four or five parameters
that appear nowhere else. So that one bias point is a **direct measurement** of
those parameters. It involves no physics and no fitting. It is the one place in
the whole problem where the answer is exact.

If your sweep starts at 0.2 V and your device turns on at 0.37 V, you are
partly in the channel already, the floor is contaminated, and you have thrown
away the only free measurement in the problem.

### The sweep resolution

Use at least 100 points per sweep. This project used 101 points from 0 to 0.6 V
in 6 mV steps for the current, and 91 points for the capacitance. Coarser than
about 10 mV and the subthreshold slope is being read off too few points to be
trustworthy.

---

## 2. How to tell a TCAD run actually finished

This costs people whole days. A device simulator printing its normal
end-of-run message means the program exited. It does not mean the voltage ramp
reached the value you asked for.

Check the data, not the log. For every sweep:

```
# how many rows did the sweep actually produce
wc -l <your_plot_file>

# what is the last bias it reached
tail -3 <your_plot_file>
```

**You should see** the row count you asked for and a last row at the bias you
asked for. If you asked for 101 points from 0 to 0.6 V and you get 6 rows
ending at 0.033 V, the run stalled at 3 percent and exited politely.

On this project two runs out of six came back looking finished and were not.
One had reached 5 rows of 101. The other had 6 points of 91. Both had printed
a clean exit message.

While you are there, check three more things:

- **Monotonic.** Drain current in an Id-Vg sweep should rise all the way. A dip
  means the solver wandered.
- **Decades.** Take log10 of the highest current over the lowest. Six to seven
  decades is healthy for a sweep that starts below threshold. Three decades
  means you started too high up the curve.
- **The same physics in every run.** Open each log and check the work function,
  the mesh file and the model switches match across all your sweeps. One run on
  this project used a work function 0.07 eV different from the others, which
  describes a completely different device, and it was only caught by reading
  the log line by line.

---

## 3. The structure numbers to write down

These are not fitted. They are properties of the device you built, they go into
the model card as fixed values, and if you get one wrong every fitted parameter
absorbs the error.

Copy them straight off your structure script.

| number | what it is | card parameter |
|---|---|---|
| sheet count | how many stacked sheets | `NGAA` |
| sheet width | the wide dimension of one sheet | `WGAA` |
| sheet thickness | the thin dimension of one sheet | `TGAA` |
| sheet spacing | gap between stacked sheets | `TSUS` |
| gate length | the physical channel length | `L` |
| oxide thickness | physical, not equivalent | `TOXP` |
| equivalent oxide thickness | | `EOT` |
| oxide permittivity | 3.9 for silicon dioxide | `EPSROX` |
| spacer length | | `LSP` |
| spacer permittivity | | `EPSRSP` |
| channel doping | | `NBODY` |
| source and drain doping | | `NSD` |
| temperature | the one your sweeps were run at | `TNOM` |

One derived number is worth computing now because it appears everywhere later:

```
effective width = NGAA * 2 * (WGAA + TGAA)
```

For four sheets of 10 nm by 5 nm that is `4 * 2 * (10 + 5) = 120 nm`. The model
calls it the UFCM width. Every capacitance per unit width in the card gets
multiplied by it, so when a capacitance comes out looking odd by a factor of
two, this is the first number to check.

---

## 4. The circuit simulator

The engine calls a circuit simulator to evaluate every trial model card.

```bash
export TCADOPT_SPICE_TOOL="hspice"
export TCADOPT_SPICE_TIMEOUT=300
which hspice
```

**You should see** a path printed by `which`. If it prints nothing, the tool is
not on your PATH. Most sites have a setup script to source. Source it in the
same terminal you will run from, because the effect does not survive into a new
terminal or a dropped SSH session.

### Check the model version your simulator has

This one matters more than it sounds, and it is a two minute check that saves a
whole debugging session. See [GAA_MODEL_CARD.md](GAA_MODEL_CARD.md) for the
full story, but the short version is that the gate-all-around geometry mode
only exists in recent versions of BSIM-CMG, and your simulator's default
version is probably not one of them.

Write this deck, exactly as shown, and run it:

```
* version probe, line 1 must be a comment
.model nch nmos level=72 version=999
.end
```

**You should see** a warning naming the highest version your simulator
supports, something like:

```
**warning** Version = 999 in BSIM-CMG model is not supported.
Reset it to version = 111.21
```

Write that number down. It goes in your card.

---

## 5. Python

```bash
cd tcad-optimization-engine
python check_setup.py
```

**You should see** your Python version, numpy, scipy and yaml all present, the
engine version, and your configured tools. The engine's default optimizer
backend runs on Python 3.6 on purpose, because simulator hosts are often locked
to an old interpreter.

---

## The checklist

Tick all of these before moving on.

- [ ] at least three Id-Vg sweeps at different drain biases
- [ ] at least three Id-Vd sweeps at different gate biases
- [ ] two C-V sweeps, one at low drain bias and one at high
- [ ] every C-V sweep starts below threshold, ideally at a negative gate voltage
- [ ] every sweep has at least 100 points
- [ ] row count and last bias checked on every sweep, from the data not the log
- [ ] every sweep is monotonic where it should be
- [ ] work function, mesh and model switches identical across all sweeps
- [ ] all thirteen structure numbers written down
- [ ] effective width computed
- [ ] circuit simulator on PATH and answering
- [ ] highest supported model version written down
- [ ] `check_setup.py` clean

**Next:** [Preparing your reference data](GAA_REFERENCE_DATA.md)
