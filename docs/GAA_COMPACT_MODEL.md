# Making a compact model for a GAA device

You built a gate-all-around device in TCAD. It simulates. Now you want a
compact model of it, so the device can go into a circuit simulator and be used
in a real design.

This page is the route map for that. Read it once, all the way down, before
opening any of the pages it links to. It is short on purpose. The detail lives
in the nine pages after it, and each of those links back here.

---

## What a compact model actually is

A compact model is a set of equations with numbers in them.

The equations are not yours. They come from a standard model, and for a
gate-all-around device that standard model is BSIM-CMG. Every circuit
simulator already has those equations built in.

The numbers are yours. There are a few hundred of them, they are called
parameters, and together they are called a model card. The model card is a
plain text file. You hand it to a circuit simulator, and the simulator uses
BSIM-CMG's equations with your numbers to reproduce your device.

Finding those numbers is called parameter extraction, and it is the whole of
what this guide is about.

Two things people expect and do not get:

- **It is not a curve fit.** You are not free to pick whatever numbers make
  the curves line up. Each parameter means a physical thing, and if you let a
  solver move all of them at once it will find a set that matches your data
  perfectly and describes nothing. The order you extract in is most of the
  work.
- **A perfect fit is not proof.** Two parameters that do the same thing to
  your data can trade against each other without changing the error at all.
  The fit error cannot see that. Something else has to measure it, and this
  engine does.

---

## What you end up with

A `.lib` file holding a `.model` card, plus the evidence that it means
something:

- the per-sweep error for every current and capacitance curve you fitted
- the threshold voltage, subthreshold slope, on current and DIBL of your model
  next to your device's
- a list of which extracted numbers the data could actually determine, and
  which pairs of them are indistinguishable
- a record of every parameter that ended up far from its own model default,
  so you can say why

---

## Before you start

You need three things. If any of them is missing, stop here and go get it
first, because everything downstream depends on them.

1. **Reference curves from a device that finished.** Not a device that started.
   The page on this explains how to tell the difference and which sweeps you
   need.
2. **A circuit simulator.** This engine drives PrimeSim HSPICE by default.
   Reading an HSPICE listing is built in. Another simulator needs a small
   parser written for it.
3. **Your structure numbers.** Sheet count, sheet width, sheet thickness,
   channel length, oxide thickness, spacer length, doping. These are not
   fitted. They are measured off the structure you built, and they go into the
   card as fixed values.

---

## The nine steps

Read them in this order. Each page tells you when you are done with it and
where to go next.

1. **[What you need before you start](GAA_WHAT_YOU_NEED.md)** - the exact TCAD
   runs to have in hand, how to check one really finished, and the structure
   numbers to write down.
2. **[Preparing your reference data](GAA_REFERENCE_DATA.md)** - turning TCAD
   output into the two CSV files the engine reads, including the four
   capacitances of the gate row and why the total is not enough.
3. **[The model card for a nanosheet](GAA_MODEL_CARD.md)** - LEVEL 72,
   VERSION 111.21, GEOMOD 5, the five-node element, and the deck rules that
   will otherwise cost you an afternoon.
4. **[Your first run](GAA_FIRST_RUN.md)** - one command at a time, with what
   every printed line means.
5. **[The extraction order](GAA_EXTRACTION_ORDER.md)** - which parameters
   come out in which stage, scored on which sweeps, and why that order and not
   another.
6. **[The free zone](GAA_FREE_ZONE.md)** - the set of parameters that cannot
   change the drain current at all, proved from the model source, and what
   that lets you do.
7. **[Charge partition, the hard part](GAA_CHARGE_PARTITION.md)** - the gate
   row, the drain's share of the channel charge, pinch-off, and the one
   parameter that the current and the charge have to share.
8. **[Checking the result](GAA_CHECKING_RESULTS.md)** - identifiability,
   physicality, distance from default, and what finished actually looks like.
9. **[When it goes wrong](GAA_TROUBLESHOOTING.md)** - every failure this
   project has hit, the exact message it prints, and the fix.

---

## How long this takes

Honest numbers, for a single n-type 4-sheet nanosheet against ten reference
sweeps, on a machine running eight HSPICE jobs in parallel:

| what | how long |
|---|---|
| getting the reference data right | a day, and it is worth it |
| the first current fit, stages 1 to 4 | 2 to 4 hours of compute |
| the capacitance fit | 2 to 6 hours of compute |
| understanding what came out | longer than the compute |

The compute is unattended. The thinking is not. Nearly every hour lost on this
project was lost to reference data that was wrong in a way nobody checked, not
to the optimizer being slow.

---

## What this can and cannot do today

Being clear about this matters more than sounding impressive.

**It can:**

- fit the whole current curve, both the subthreshold decades and the on state,
  across several drain biases at once
- extract in stages with earlier stages frozen, so each parameter is found in
  the bias region where it dominates
- read the full gate row of capacitances, all four of them, out of the
  simulator's own operating point with no extra simulation
- prove which parameters cannot touch the drain current, and fit those with
  the current held exactly fixed
- measure identifiability, so a number comes with an answer to whether the
  data could have determined it
- price a parameter that two objectives disagree about, instead of just
  refusing to move it

**It cannot, yet:**

- run the whole thing from one YAML file end to end for the capacitance side.
  The current side does that. The charge side is still driven by staged
  scripts while the method is being settled.
- handle self-heating, statistical variability, or temperature scaling. Those
  are separate model switches and each needs its own stage.
- extract a p-type card at the same time as the n-type one. You run it twice.
- tell you that your reference data is wrong. It will fit whatever you give
  it. Step 2 exists for that reason.

---

## Words you will meet

Short definitions, because the rest of the guide uses these without stopping.

**I-V** - current against voltage. Id-Vg is drain current swept against gate
voltage at a fixed drain voltage. Id-Vd is drain current swept against drain
voltage at a fixed gate voltage.

**C-V** - capacitance against voltage. Here it means gate capacitance swept
against gate voltage at a fixed drain voltage.

**Model card** - the text block holding your extracted parameters. In HSPICE
it starts with `.model` and lives in a `.lib` file.

**Residual** - the number that says how far the model is from the device.
Smaller is better. This engine splits it into a subthreshold part measured in
decades and an on-state part measured as a fraction, because one number cannot
serve eight decades of current.

**Stage** - one step of the extraction. A stage frees a few parameters, scores
them on the sweeps where they matter, and freezes the answer before the next
stage starts.

**Gate** - the check that decides whether a stage's result is kept. If the
stage made things worse the gate rolls it back and the run carries on.

**The gate row** - the four capacitances Cgg, Cgd, Cgs and Cgb read at one
bias. Cgd plus Cgs plus Cgb equals Cgg exactly. Page 2 explains why you want
all four and not just the total.

**The free zone** - the parameters that only appear inside the charge
equations, so they cannot change the drain current no matter what you set them
to. Page 6 lists them with the line numbers that prove it.

**Identifiability** - whether the data could have determined a parameter at
all. A fit can be perfect and still be meaningless, so this is measured
separately from the fit error.

---

## Where this fits in the repository

This guide is one of three routes through TCADOpt. The other two are design
optimization and generic parameter extraction, and both are listed in
[README.md](README.md).

If you want the engine-level view rather than the device-level view, read
[PARAMETER_EXTRACTION.md](PARAMETER_EXTRACTION.md) for how the extraction path
is built and [ARCHITECTURE.md](ARCHITECTURE.md) for how the layers fit
together. You do not need either of them to follow this guide.

**Next:** [What you need before you start](GAA_WHAT_YOU_NEED.md)
