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

## The step says it succeeded and the card got worse

### The weighted score improved and the honest error did not

**What you see.** A step reports a healthy improvement and the card it ships
is worse than the card it started from.

**What it is.** You are optimising a weighted objective and reporting an
unweighted one. The weights were computed from the residuals of one card, and
then the card changed underneath them. A curve that was nearly perfect drew a
tiny weight, which an optimiser reads as "this curve does not matter", and it
was then free to triple.

On this project a weight of 0.02 on a curve sitting at 0.184 per cent let it
rise to 0.667, and the step shipped a card 8.17 per cent worse on the pooled
measure while its weighted score fell 16.8 per cent.

**The fix.** Minimise the pooled error over every point, which needs no
weights at all. [Which number you are minimising](GAA_THE_OBJECTIVE.md) has
the arithmetic and the code. If you must use weights, recompute them every
iteration, and run `tcadopt/l6_verify/floor.stale_weights` to find the ones
that no longer describe anything.

### A card got into the pipeline without being guarded

**What you see.** The log shows the guard refusing something, so the guard is
clearly working, and the card is still worse.

**What it is.** The guard is wrapped around your fit and nothing else. A
ladder, a scan or a closed form solve can all produce a card, and if any of
those feeds the next part directly, it never passes the guard.

**The fix.** Write the rule as a function and call it on every candidate from
every source. [The rule](GAA_THE_RULE.md) has the function.

### A refused result reverted to the wrong card

**What you see.** Several parts of a step each report a sensible improvement
and the step as a whole is worse.

**What it is.** When a part was refused, the revert went back to whatever the
previous part left rather than to the card the step started with. Everything
after that is measured against a card that has already regressed.

**The fix.** Keep the entry card in its own variable, never overwrite it, and
revert to it. Say so in the rule's printed text, so a reader of the log knows
before anything runs.

---

## A reproduce check fails and only half the curves moved

### The current reproduces exactly and the capacitance does not

**What you see.**

```
      what                              printed before    this run     drift
      the eight current sweeps             0.014114     0.014114  0.00e+00
      the eight capacitance curves         0.026916     0.040472  1.36e-02
```

**What it is.** This pattern is a gift. A drift in the machine, the simulator,
the library or the card transfer would have moved the current too. Only the
charge moved, so whatever changed touches only the charge equations.

Two causes account for nearly every instance.

**You loaded the wrong card.** A constant named `CARDnn` in an extraction
script very often means the card step nn **started** from, not the card it
produced. Check the number against what the earlier log printed for its own
starting point.

**You wrote a value that looked like a default and was not.** If a parameter's
declared default is a reference to another parameter rather than a number, the
model may assign a **computed** variable, not the declared one. `vfbsdcv`
defaults to `vfbsd`, which is declared 0.0, but the model assigns
`vfbsdcv_v = vfbsd_v`, the computed flatband voltage of the source and drain,
which on this device is about +0.43 V. Putting an explicit 0.0 on the card
overrode it and moved the capacitance from 0.026916 to 0.075682 while the
current did not move at all.

**The fix for both.** Stop reading names. Simulate every card that could be
the baseline and pick the one that matches the numbers the earlier log
printed. [The rule](GAA_THE_RULE.md) has the table and the code.

---

## A parameter will not go below a round number

### Every fit ends with it sitting on exactly 0.02

**What you see.** A parameter finishes on the same round value in run after
run, and every value you try above it is worse.

**What it is.** Either the model clamps it there, or a lower bound in your own
range does. Those look identical in a log and they are completely different
facts, and in this case it mattered a lot: `ckappad` was the only parameter in
the charge model whose two drain biases move in opposite directions, which was
the exact shape of the remaining error.

**The fix.** Measure it, without reading any source. Put the value on a card,
then put smaller values on cards, and compare the curves point by point. If
the model clamps, every smaller value returns curves identical to the last
bit:

```
      value        worst change vs 0.02      verdict
      0.01           0.0000e+00 aF             identical, clamped
      0.005          0.0000e+00 aF             identical, clamped
      0.001          0.0000e+00 aF             identical, clamped
      1e-05          0.0000e+00 aF             identical, clamped
```

[Knowing when it is finished](GAA_WHEN_TO_STOP.md) has the code. Twelve
simulations turn a nagging doubt into a line in your ledger.

---

## The aligner will not run, or runs and seems to do nothing

### `TypeError: cannot convert dictionary update sequence element #0 to a sequence`

**What it is.** You passed `params` as a list of numbers. `lm_align` does
`dict(params)` internally, so `params` is the whole card as a dict and `names`
selects which of its entries to fit.

**The fix.**

```python
out = lm_align(evaluate, residual, dict(card), names, ranges_by_name,
               n_iter=10, tag="fit", post=tie, log=print)
new_card = out["params"]
```

### The aligner returns and nothing in it looks like a parameter

**What it is.** It returns a result dict, not a card. The card is under
`params`. The top level holds `params`, `ok`, `S0`, `S`, `n_evals`, `names`,
`moved`, `at_bound`, `inert` and `history`, so a reader looking for a
parameter name at the top level finds nothing and concludes the fit failed. It
did not.

### It returns cleanly and the card has not changed

**What it is.** Check how many simulations it triggered. A convention that is
almost right can return a well formed result dict having evaluated one card,
which is not enough to have built a Jacobian. Wrap your `evaluate` in a
counter and compare candidates by work done rather than by whether they
returned. [Walking one knob at a time, and the fit](GAA_THE_JOINT_FIT.md) has
the probe.

### It stops after five of the ten iterations you asked for

**What it is.** Not a bug. `tol` defaults to 0.01 and it stops after two
iterations that each gain less than one per cent. Read the gain sequence
before deciding whether more iterations would pay:

```
    LM it 1: S -> 0.555387  (-4.95%)
    LM it 2: S -> 0.548079  (-1.32%)
    LM it 3: S -> 0.541461  (-1.21%)
    LM it 4: S -> 0.538201  (-0.60%)
    LM it 5: S -> 0.536466  (-0.32%)
```

Those shrink by about 0.65 each time, so the rest of that basin is worth about
0.3 per cent of the pooled error. If instead the last gain is still large, the
fit was cut off and more iterations will help.

Also read the `at_bound` list it returns. A fit that finishes with several
parameters pinned against the edge of their boxes has been stopped by a box
you drew, not by a minimum.

---

## A walk finds nothing and a fit finds plenty

**What you see.** You walk thirty parameters one at a time, keep almost
nothing, and conclude the card is finished. A fit over the same parameters
then finds several per cent.

**What it is.** Not a contradiction. A walk finds a point where no single
parameter helps. A fit can move several at once, and two parameters that only
help together are invisible to a walk. On this device 300 one at a time
simulations found 0.44 per cent and one fit found 4.18.

**What to do.** Both, in that order. The walk is safe and it diagnoses which
parameters are alive. The fit finds the directions the walk cannot see. And
write the walk's card to disk before you call the aligner, so a convention you
have read but never run cannot cost you work that already succeeded.

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

**Next:** [A worked extraction, start to finish](GAA_CASE_STUDY_NFET.md),
which is this whole project with the real numbers, including every failure on
this page in the order it actually happened.

**Back to the route map:** [GAA_COMPACT_MODEL.md](GAA_COMPACT_MODEL.md)
