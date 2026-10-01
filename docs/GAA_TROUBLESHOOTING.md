# When it goes wrong

Back to the route map: [GAA_COMPACT_MODEL.md](GAA_COMPACT_MODEL.md)

Every failure in this list actually happened on a real extraction. The message
is what was printed, and the fix is what worked. Find yours by the message.

---

## Nothing runs at all

### `ModuleNotFoundError: No module named 'tcadopt'`

You are in the wrong directory. Change into the repository root first.

```bash
cd tcad-optimization-engine
```

### `hspice: command not found`

Your circuit simulator is not on the PATH of **this terminal**. Most sites have
a setup script to source, and sourcing it only affects the terminal you type it
in. A new terminal, or an SSH session that dropped and reconnected, needs it
again.

```bash
source /path/to/your/simulator/setup
which hspice          # must print a path, not nothing
```

### Every simulation fails, `batch done: 0/N ok`

Go and look at one. Do not guess.

```bash
ls -t runs_fit | head -1
cat runs_fit/<DIR>/*.lis | grep -i error
```

The three usual causes are the simulator not being on the PATH, the model
version, and the netlist title. All three are below.

---

## The model card is rejected

### `*Error*: Out of range from [0:3]: integer parameter GEOMOD = 5 in L72`

Your `VERSION` line is missing or too old. LEVEL 72 defaults to an old version
that has no gate-all-around geometry at all, so `GEOMOD=5` is genuinely out of
range there.

Find your simulator's highest supported version by asking for one that cannot
exist:

```
* version probe
.model nch nmos level=72 version=999
.end
```

**You should see** a warning naming the real maximum:

```
**warning** Version = 999 in BSIM-CMG model is not supported.
Reset it to version = 111.21
```

Put that number in your card and the whole gate-all-around parameter set
appears.

### The listing prints a syntax reference for an element you never used

For example, a reference for the behavioural element `Bxxx` when your deck has
no behavioural elements in it.

**Line 1 of your netlist is being read as a circuit element.** The first line
of a netlist file is the title, whatever it contains. If you put a comment
banner above your title, the banner became the title and your intended title
moved to line 2, where it is parsed as content. A title starting with `B` reads
as a behavioural element, one starting with `M` as a MOSFET, and so on.

Three rules that remove this whole class of problem:

1. Line 1 is the title. Never put anything above it.
2. Comments start with `*` in column 1. Not `$`.
3. Make line 1 itself a `*` comment, so it can never be misread.

### `PHIBE_i = 0 is less than 0.2, setting it to 0.2`

This is a warning, not an error, and it is normal for a card that does not set
`PHIBE`. The model clamped it. You can ignore it or set `PHIBE` explicitly.

---

## The reference data is the problem

### A sweep has far fewer points than you asked for

The device simulation stalled and exited cleanly. A tool printing its
end-of-run message means the program exited, not that the ramp finished.

Check every sweep by its data, not its log:

```bash
wc -l <plot file>
tail -3 <plot file>
```

On this project two runs out of six looked finished and were not. One had 5 rows
of 101. One had 6 points of 91.

### The loader excludes far fewer rows than you marked

Your `usable` column is not being read. Almost always stray whitespace, or the
value being `Yes` or `YES` where the loader expects `yes`. Print what the
loader sees:

```bash
python -c "
import csv, collections
c = collections.Counter(r['usable'] for r in
                        csv.DictReader(open('targets/cv_targets.csv')))
print(c)
"
```

### Two of your sweeps describe different devices

Open every simulation log and compare the work function, the mesh file and the
model switches. On this project one capacitance run used a work function 0.07
eV different from the rest of the set, which is a completely different device,
and it was only caught by reading the logs line by line.

### The C-V sweep starts above threshold

Then there is no bias in your data with the channel off, and the parasitic
floor cannot be measured. That floor is the one exact answer in the whole
problem, and losing it means those parameters have to be fitted along with
everything else, where they are degenerate with several things.

Re-run the sweep starting at zero or below. It is worth the simulation time.

### The gate row closure error is large

`Cgd + Cgs + Cgb` should equal `Cgg` to a few parts in a million. If yours is
out by percent, the four numbers did not come from the same place, or one of
them has the wrong sign convention. Fix it before fitting anything, because
the engine will fit whatever you give it.

---

## The simulation runs but the numbers look wrong

### A capacitance is out by a factor of about two

Check your effective width. For a gate-all-around device the model computes

```
effective width = NGAA * 2 * (WGAA + TGAA)
```

which for four sheets of 10 nm by 5 nm is 120 nm. Every capacitance specified
per unit width gets multiplied by that. A factor of two usually means the
sheet count or the factor of 2 for top and bottom surfaces is being applied
twice, or not at all.

### The drain and source capacitance floors are exactly equal

That is the model being symmetric, not your device. `CGDO` defaults to `CGSO`,
`CFD` defaults to `CFS`, `CGDL` to `CGSL` and `CKAPPAD` to `CKAPPAS`, so
setting one silently sets its twin. Set both explicitly if you want them to
differ.

### The results are ten million times too large or too small

Units. Current in amps against current in microamps per micron is a factor of
about a million for a device this size. Capacitance in farads against
attofarads is 1e18. This project lost real time to exactly this at step 1, and
the only defence is to print a value from your CSV and a value from the
simulator side by side, once, and look at them.

---

## A stage does not improve

### The error is flat from the first round

The parameters this stage frees do not affect the sweeps it is scored on.
Check the stage's `sweeps` list. A stage freeing DIBL parameters scored on one
drain bias cannot work, because DIBL is a difference between two drain biases.

### A parameter sits exactly on the end of its range

The fit wants to go further. Resist widening the range. In every case on this
project where a parameter railed, the real cause was elsewhere:

- the term the parameter belongs to was switched off in this configuration, so
  the fit was chasing an effect worth nothing and ran to the end of the box
- the parameter was standing in for a missing term
- a different parameter should have absorbed that effect in an earlier stage

Before widening, sweep the parameter across its whole range on its own and look
at how much the error changes. If the whole range is worth 1e-5 of residual, it
is not being determined and widening the range just moves the noise.

### A parameter measures as completely dead

Three causes, in order of how often they are the answer.

1. **A switch is in the wrong position.** The whole block of code that reads it
   is inside an `if`. The `CVMOD` family is the big one here, see
   [GAA_FREE_ZONE.md](GAA_FREE_ZONE.md).
2. **It only multiplies another term, and that term is zero.** `CKAPPAS` only
   appears inside the `CGSL` bracket. With `CGSL = 0` the bracket is multiplied
   by zero and `CKAPPAS` can do nothing. This project called those two
   parameters dead three separate times before noticing. When you survey a
   parameter that shapes another term, switch the other term on first.
3. **You are scoring it on a quantity that cannot see it.** The parameters that
   move charge between the two ends of the channel barely change the total gate
   capacitance, because the total is the sum of the two ends. Score them on the
   gate row, not on `Cgg`.

---

## A stage improves and gets thrown away

### The gate rolls back a stage that clearly got better

First, check the gate is judging the right thing. A gate scored on a total
cannot see a quantity being redistributed between terminals. On this project a
correct parasitic floor solve, which took one terminal's error from 84 percent
to 38 percent with the current unchanged, was rolled back because the total
rose by 0.0008.

Second, and this one cost three stages across two extraction steps: **check
that the optimizer and the gate minimise the same function.** If the optimizer
minimises a sum of squares and the gate judges a mean of root-mean-squares,
they will disagree, and they will disagree in a specific direction. Squaring
makes a big error worth much more than a small one, so the optimizer will
double a small error to halve a big one and the gate will correctly refuse.

The engine has `scorer_residual` in `tcadopt/l5_opt/lm_align.py` for exactly
this. Its sum of squares is the scorer's total, term for term. If you write a
custom objective, check the identity yourself before trusting a rollback.

### A gate rolls back a shared parameter every time

A gate is the wrong tool for a shared parameter. See
[GAA_CHARGE_PARTITION.md](GAA_CHARGE_PARTITION.md) and price it instead.

---

## The run crashes partway

### `KeyError` on a parameter name you definitely asked for

The aligner drops parameters whose Jacobian column is degenerate, so the
result does not always contain every name you passed in. Read the result with
`.get()` and treat a missing name as "did not move", rather than indexing every
name you asked for.

### `TypeError: 'NoneType' object is not iterable`

Something upstream returned `None` and it was not checked. The common source is
a curve that came back too short to score. Look further up the log for a sweep
reporting a point count of 1 or 0, which is usually a parser problem rather
than a simulation problem.

### A parser returns a one-point curve from a full listing

A circuit simulator prints at most four data columns per table. A print
statement asking for more than four splits the output across two tables under
one bias heading, and a parser that only joins tables with identical column
lists will turn 91 biases into 182 one-row blocks.

The parser in this engine stitches them. If you wrote your own, handle it.

### `TypeError: key (...) is not a string` when writing results

JSON keys have to be strings. If you are using tuples as dictionary keys,
convert them before dumping.

---

## A number is not a number

### A share or a fraction comes back as `nan`

A share is a division. If the thing being divided by is zero, there is no
share. For the drain's share of the channel charge this means the card has
destroyed the channel charge entirely, which is a real reading and not a crash.

The thing to be careful about is what happens next. In Python every comparison
against `nan` is false, so a `nan` sitting at the front of a `min` or a `max`
is returned unchallenged and silently becomes the answer. Filter for finite
values before any comparison. The engine does this in `trade.py` and it is
worth doing in anything you write.

### `gm` comes back `nan` and `SS` comes back `inf`

A repeated bias point in the sweep, which most ramp decks produce at the sweep
ends. A numerical derivative then divides by zero. De-duplicate the x axis
before differentiating.

---

## The run takes far longer than expected

Set the budget and the parallelism explicitly rather than hoping:

```bash
export TCADOPT_PARALLEL=8            # simultaneous simulator jobs
export TCADOPT_SPICE_TIMEOUT=300     # seconds before one job is abandoned
```

Set the parallel count to the number of licences or cores you actually have,
whichever is smaller. More than that and jobs queue, which looks like the
optimizer being slow.

If a stage is the bottleneck, check how many sweeps it is scored on. A stage
scored on ten sweeps costs ten simulations per evaluation. A stage scored on
the two it actually needs costs two, and gives the same answer.

---

## Still stuck

Keep the whole log. Not the last twenty lines, the whole file. On this project
every single root cause was in the log, and in most cases it was in a line that
looked routine until someone read the file from the top.

The four questions that found the cause most often:

1. Did the simulation actually run, or did it fail and get counted as a
   partial success?
2. Is the deck that ran the deck I think ran? Check the file in `runs_fit/`.
3. Does the reference data say what I think it says? Print it.
4. Is the thing being optimised the same thing being judged?

**Back to the route map:** [GAA_COMPACT_MODEL.md](GAA_COMPACT_MODEL.md)
