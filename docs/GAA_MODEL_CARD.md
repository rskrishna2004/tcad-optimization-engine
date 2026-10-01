# The model card for a nanosheet

Back to the route map: [GAA_COMPACT_MODEL.md](GAA_COMPACT_MODEL.md)

The model card is the text block that tells a circuit simulator which equations
to use and with what numbers. The engine writes it for you from the parameters
it extracts, but you have to tell it the fixed parts first, and there are four
things about a gate-all-around card that will waste an afternoon if nobody
tells you.

---

## What a card looks like

```
.model nch nmos level=72 version=111.21
+ geomod=5 ngaa=4 wgaa=10n tgaa=5n tsus=10n
+ l=12n eot=0.734n toxp=0.734n epsrox=3.9
+ lsp=5n epsrsp=7.5 nbody=1e21 nsd=1e26
+ bulkmod=0 cvmod=0 shmod=0 cgeomod=0
+ phig=4.4374 u0=0.03363 vsat=72007 rdsw=104.23
+ ...
```

`level=72` picks BSIM-CMG. Everything after that is a parameter. Lines starting
with `+` continue the previous line.

---

## Thing one: the version, and why the default will not work

**BSIM-CMG at LEVEL 72 defaults to an old version, and that old version has no
gate-all-around geometry at all.**

In PrimeSim HSPICE U-2023.03 the default is version 106.1. Version 106.1's
`GEOMOD` parameter accepts 0 to 3, which covers bulk and SOI FinFET shapes.
Gate-all-around is `GEOMOD=5`, and it does not exist there. Leave the version
line out and you get:

```
*Error*: Out of range from [0:3]: integer parameter GEOMOD = 5 in L72
```

which reads like your card is wrong when actually your version is wrong.

Add the version and the whole gate-all-around parameter set appears:
`TGAA`, `TSUS`, `HPFF`, `WGAA`, `NGAA`, `DWS1` through `DWS6`, `DACH1` through
`DACH6`, `SUBBANDMOD`, `MOBSCMOD`, `FNMOD`, `WGAANOM`.

Find your simulator's highest supported version the way
[GAA_WHAT_YOU_NEED.md](GAA_WHAT_YOU_NEED.md) describes, by asking for a version
that cannot exist and reading the warning. Then always write it explicitly. The
deck generator in this engine writes it on every card for exactly this reason
and does not let the caller omit it.

---

## Thing two: three rules about netlist files

These are not model rules, they are file format rules, and breaking them
produces error messages that point somewhere else entirely.

### Rule 1. The first line of the file is the title, whatever it contains

A circuit simulator treats line 1 as the title of the run. Always. It does not
matter what you wrote there. If you put a comment banner above your title line,
the banner becomes the title and your title line becomes line 2, where it is
read as a circuit element.

On this project, four probe decks all failed at once because of a banner above
the title. The intended title started with the letter B, and B is the
behavioural element letter, so the simulator printed the syntax reference for
behavioural elements and nothing worked. The model was fine. The file had one
extra line at the top.

### Rule 2. Comments start with `*` in column 1

Not `$`, not `#`, not `//`. A `$` at the start of a line is not a comment and
will be parsed as circuit content.

### Rule 3. Make line 1 a comment line on purpose

Since line 1 is the title no matter what, write it as a comment. Then it can
never be misread as an element, whatever you put in it.

```
* nanosheet nFET extraction deck, stage 3
.model nch nmos level=72 version=111.21
...
```

Three lines of policy, and following them removes a whole category of
confusing failure.

---

## Thing three: `.option list node` gives you the gate row for free

Put this in your deck:

```
.option list node
```

and the simulator prints its own operating point for every element at every
bias. For a MOSFET that block ends with the small-signal capacitances,
including `cgs`, `cgd`, `cbtot` and `cgtot`, and `cgs + cgd + cbtot` equals
`cgtot` exactly at every bias.

Those four numbers are the **gate row**, which is exactly what your reference
data holds and exactly what the charge side of the extraction needs. No extra
simulation, no AC analysis, no extra deck. It is already being printed.

The same block also prints `vth` and `vdsat` per bias, and `vdsat` is worth
reading. If the model's `vdsat` on the capacitance sweep is smaller than the
drain voltage the sweep is held at, the model has already pinched the channel
off before the sweep begins, and no capacitance parameter will fix that.
[GAA_CHARGE_PARTITION.md](GAA_CHARGE_PARTITION.md) is about that exact
situation.

One practical note on reading those tables. A simulator prints at most four
data columns per table, so a print statement asking for more than four splits
the output across two tables under one bias heading. A parser that only joins
tables with identical column lists will turn 91 biases into 182 one-row blocks
and then report a one-point curve. The parser in this engine stitches them back
together. If you write your own, handle it.

---

## Thing four: the element has five nodes

The BSIM-CMG module has a thermal node as well as drain, gate, source and bulk.
A four-node instance line works and gives you the isothermal device. A
five-node instance line plus `shmod=1` turns on self-heating.

```
M1 nd ng 0 0 nt nch          $ five nodes, nt is the thermal node
```

Measured on this project, the same bias with `shmod=1` and a thermal resistance
set gave 9.18 microamps against 9.89 isothermal, a 7.2 percent reduction. Leave
`shmod=0` until the isothermal card is finished. Self-heating is its own
extraction stage and mixing it in early will corrupt the mobility parameters.

---

## The switches, and what each one turns on

These are integers, not fitted values. Set them deliberately and write down
why.

| switch | set it to | what it does |
|---|---|---|
| `GEOMOD` | `5` | gate-all-around geometry. Needs the right version. |
| `CGEOMOD` | `0` | how the parasitic capacitances are specified. `0` takes them per unit width, `1` takes absolute values. |
| `BULKMOD` | `0` | with `0` the gate to body capacitance is a constant. With non-zero it gains a bias-dependent term. |
| `CVMOD` | `0` or `1` | `0` means the charge reuses the current's transport parameters. `1` gives the charge its own private copies. See below. |
| `SHMOD` | `0` | self-heating off. |
| `NQSMOD` | `0` | quasi-static. Leave it off. |
| `RDSMOD` | as needed | how series resistance is modelled. |

### CVMOD is worth understanding before you set it

BSIM-CMG gives the charge equations their own private copies of six transport
parameters: `VSATCV`, `U0CV`, `UACV`, `UCCV`, `UDCV` and `ETA0CV`. Each one
defaults to the plain parameter of the same name.

The catch is that those copies are only used when `CVMOD=1`. At `CVMOD=0` the
charge calculation reads the **current's** values instead, and the six private
parameters reach nothing at all. You can set `VSATCV` to anything you like and
measure exactly zero change, which looks like a dead parameter and is actually
a switch in the wrong position.

Measured on this project: sweeping `VSATCV` across its range moved the drain's
share of the channel charge by 0.03 points at `CVMOD=0` and by 6.45 points at
`CVMOD=1`. A factor of two hundred, from one integer.

So:

- start at `CVMOD=0`, because it keeps the model self-consistent and there is
  less to go wrong
- switch to `CVMOD=1` only when you have decided the charge genuinely needs to
  depart from the current, and say so in your report when you do

---

## What the engine writes and what you supply

You supply, in your fit specification:

- the structural numbers from
  [GAA_WHAT_YOU_NEED.md](GAA_WHAT_YOU_NEED.md)
- the switches above
- the version
- the parameter ranges to search, per stage

The engine writes:

- the whole card, including the version line
- the decks that exercise it, one per reference sweep
- the title comment on line 1 of every deck

You can render the current card at any time:

```bash
python -c "
import json
from tcadopt.l2_decks.cardgen import render_card
frozen = json.load(open('results/frozen_your_fit.json'))
print(render_card('nsfet_n', frozen, polarity='nmos'))
" > nsfet_n.lib
```

**You should see** a complete `.model` block. Open it and read it. Every number
in there is something you are claiming about your device, and reading it once
at the end is how you catch a parameter that ran to the end of its range.

---

## A sanity check worth running once

After your first stage, look inside the deck the engine actually ran, not the
one you think it ran:

```bash
ls -t runs_fit | head -1
```

then with that directory name:

```bash
grep -i "version\|geomod\|ngaa\|phig" runs_fit/<DIR>/*.lib
```

**You should see** your version, `geomod=5`, your sheet count, and a work
function that is inside the range you gave. This project once lost eleven hours
of compute to a stale deck that was being regenerated from an old template, and
this two second check is what would have caught it.

**Next:** [Your first run](GAA_FIRST_RUN.md)
