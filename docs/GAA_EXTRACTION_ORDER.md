# The extraction order

Back to the route map: [GAA_COMPACT_MODEL.md](GAA_COMPACT_MODEL.md)

A compact model has hundreds of parameters. If you free them all at once you
will get a set of numbers that matches your data and means nothing. This page
is about why, and about the order that avoids it.

---

## Why order is the whole problem

Take two parameters that both make the subthreshold slope shallower. Call them
A and B. Your data has one subthreshold slope in it. There are infinitely many
pairs of A and B that produce that slope, and the fit error is identical for
every one of them.

A solver handed both at once will return one of those pairs. Which one depends
on where it started and on rounding. The fit will look perfect. Report those
numbers as measurements of A and B and you are reporting noise.

Now extract them separately, each in a bias region where only one of them
matters, with the other held fixed. Each number is then determined by the data.
That is the difference between an extraction and a curve fit, and it is the
reason for everything below.

---

## The rule

**Free a parameter only in the bias region where it dominates, and freeze it
before moving on.**

Two consequences that people find surprising:

- A later stage is not allowed to improve an earlier stage's parameter, even
  though it could. That improvement would be the later stage's data absorbing
  an error that belongs somewhere else.
- A stage that fails to converge freezes nothing. Passing a half-determined
  number forward is worse than stopping.

---

## The order, for a gate-all-around device

This is the order this project arrived at. Stages 1 to 5 are the current.
Stages 6 to 9 are the charge.

### Stage 1. Electrostatics

**Scored on:** one Id-Vg sweep at low drain bias, subthreshold half only.

**Frees:** `PHIG`, `CIT`, `CDSC`, `NFACTOR`

**Why here:** at low drain bias and below threshold the current is set almost
entirely by how the gate controls the surface potential. Drain bias effects are
small and transport does not matter yet, because there is hardly any current.

**Watch out:** these four are strongly coupled. `CIT`, `CDSC` and `NFACTOR` all
push the subthreshold slope the same way, and on this project the
identifiability report found all three pairwise correlations at exactly 1.00.
That is not a failure of the fit, it is a fact about the data, and what you
report is the combination rather than the individual numbers. See
[GAA_CHECKING_RESULTS.md](GAA_CHECKING_RESULTS.md).

### Stage 2. Short channel effects

**Scored on:** Id-Vg at the lowest and the highest drain bias, subthreshold
half.

**Frees:** `DVT0`, `DVT1`, `ETA0`, `DSUB`, `CDSCD`

**Why here:** these are the parameters that describe how the drain steals
control from the gate. They only show themselves as a **difference between two
drain biases**, so you need at least two Id-Vg curves in the objective. With
one curve any threshold shift is absorbed by `PHIG` and these read as zero.

**Watch out:** `ETA0` and `DSUB` are close to degenerate, measured on this
project at a correlation of about minus 0.997. What the data determines well is
the combination `ETA0 * exp(-DSUB)`, which came out to within 0.16 percent. The
individual numbers did not.

### Stage 3. Transport

**Scored on:** all Id-Vg sweeps, on-state half.

**Frees:** `U0`, `UA`, `UD`, `EU`, `ETAMOB`

**Why here:** above threshold the current is mobility times charge, and the
charge is already fixed by stages 1 and 2. So whatever is left over is
mobility.

**Watch out:** if the mobility degradation term is switched off in your
configuration, `UA` and `EU` have almost no effect and the optimizer will send
them to the ends of their ranges chasing nothing. On this project that produced
a card where `UA` wanted to go below 1e-4 and `EU` past 12, which is the fit
saying "this term does nothing here" in the only way it can. The fix is to
notice it and pin them, not to widen the box.

### Stage 4. Velocity saturation and series resistance

**Scored on:** all Id-Vd sweeps.

**Frees:** `VSAT`, `RDSW`, `RDSWMIN`, `KSATIV`, `MEXP`

**Why here:** the Id-Vd curve's shape at low drain bias is set by series
resistance and its knee is set by velocity saturation. Neither is visible in an
Id-Vg sweep at fixed drain bias.

**Watch out:** `VSAT` and `RDSW` are strongly anti-correlated, measured at
about minus 0.97, because both reduce the on current. Include a low gate bias
Id-Vd sweep, where resistance dominates and velocity saturation does not, and
they separate.

### Stage 5. Output resistance

**Scored on:** Id-Vd sweeps at high gate bias, saturation region only.

**Frees:** `PCLM`, `PCLMG`, `PDIBL1`, `PDIBL2`, `PVAG`, `DROUT`

**Why here:** the slope of the Id-Vd curve after the knee is the only place
these appear.

### Stage 6. The parasitic capacitance floor

**Scored on:** the C-V sweeps at the off-state bias only.

**Frees:** `CGSO`, `CGDO`, `CGBO`, `CGBN`, `CGBW`, `CFS`, `CFD`

**Why here:** at a gate bias with no channel, these are the only things
connecting the gate to anything. As
[GAA_REFERENCE_DATA.md](GAA_REFERENCE_DATA.md) explains, this is the one place
in the whole problem where the answer is exact rather than fitted.

**Watch out:** solve for all three terminals at once against the three measured
floors, rather than fitting the total. The total cannot see charge being moved
between terminals. On this project a floor solve that was correct was rolled
back by a gate scored on the total, because redistributing the floor between
three terminals raised the sum by 0.0008 while fixing a 84 percent error on one
terminal.

Also: several of these parameters default to each other. `CGDO` defaults to
`CGSO`, `CFD` to `CFS`, `CGDL` to `CGSL`, `CKAPPAD` to `CKAPPAS`. So setting one
silently sets its twin, and the model cannot tell the drain side from the
source side until you set both explicitly. A real device can, and this project's
two floors differ by 0.21 aF.

### Stage 7. The charge in the channel

**Scored on:** both C-V sweeps, the whole gate row.

**Frees:** the free-zone parameters, listed in
[GAA_FREE_ZONE.md](GAA_FREE_ZONE.md)

**Why here:** these parameters cannot change the drain current. Not "barely
change", cannot, and that is proved from the model source and then measured. So
this stage can run with the current held exactly fixed, and there is no
trade-off to manage at all.

### Stage 8. The shared parameters

**Scored on:** everything.

**Frees:** the few parameters that the current and the charge both use.

**Why last:** because this is the only stage where improving one side can hurt
the other, and it should happen once, at the end, when everything else is
settled. [GAA_CHARGE_PARTITION.md](GAA_CHARGE_PARTITION.md) is about how to
handle it, and the short answer is that you price it rather than gate it.

### Stage 9. Polish

**Scored on:** everything, all sweeps at once.

**Frees:** everything, with a pull towards the model's own default values.

**Why:** the staged order is right for determining parameters and slightly
suboptimal for the final error, because each stage was blind to the others. One
gentle joint pass at the end recovers that, and the pull towards defaults keeps
it from undoing the physical meaning the staging bought.

---

## Freezing, and how to resume

Every stage writes its result to `results/frozen_<spec>.json`. That file is the
extraction's memory. You can stop after any stage and pick up later:

```bash
python -m tcadopt.l8_orch.run_fit problems/your_fit.yaml --stage 5
```

Read the file between stages. It is plain JSON and it is the honest record of
what has been determined so far.

---

## Gates: what keeps a stage and what throws it away

A gate is the check that runs after a stage and decides whether to keep the
result. There are two kinds and they answer different questions.

### The ordinary gate

Asks: **is the whole objective no worse than before?** If yes, keep. If no,
roll back to the previous card and carry on to the next stage.

This is the right check for any stage that can trade one curve against another.

### The frozen gate

Asks two questions: **did the capacitance improve, and did every current sweep
stay bit-identical?** Both must be true.

This is for the free-zone stage. Because those parameters provably cannot touch
the current, "bit-identical" is not a tolerance, it is a prediction, and the
gate checks it point by point on every sweep. If the current moves by anything
at all, the free-zone claim is wrong for your model version and the run says so
and rolls back.

### One warning about gates that cost this project three stages

**The thing the optimizer minimises and the thing the gate judges must be the
same function.** They sound like they obviously are. They were not.

The optimizer minimised a sum of squares. The gate judged a weighted mean of
root-mean-squares. Squaring makes a large error worth much more than a small
one, so the optimizer was happy to double a small error in order to halve a big
one, and the gate, counting errors at face value, correctly refused. Three
stages across two extraction steps found real improvements of 99, 6 and 39
percent and every one of them was thrown away by this mismatch.

The fix is exact rather than a tuning. For one block of per-point errors `u`
over `n` points the judge uses `e = norm(u)/sqrt(n)`. Scale the block by
`sqrt(w*e)/norm(u)` and its contribution to the sum of squares becomes exactly
`w*e`, which is the term the judge adds. Do that for every block and the two
numbers are the same number. That is `scorer_residual` in
`tcadopt/l5_opt/lm_align.py`, and it is worth checking in your own setup if you
ever write a custom objective.

---

## When a stage refuses to improve

In order of how often it is the answer:

1. **The data does not contain what the stage is looking for.** A stage freeing
   DIBL parameters scored on one drain bias cannot work. Check the sweeps the
   stage is scored on.
2. **An earlier stage absorbed the error.** If stage 1 was scored on a sweep
   where stage 2's effects were already visible, stage 1's parameters have
   soaked them up and stage 2 has nothing left to find.
3. **The parameter is switched off.** A whole model term can be inactive in
   your configuration. Sweep the parameter across its full range on its own and
   look at the change. If it is zero, stop fitting it.
4. **The range is wrong.** Not too narrow, wrong. A parameter pinned at a range
   end usually means it is standing in for something that is missing.
5. **The optimizer is stuck.** Last on the list, and on this project it was
   never the answer.

**Next:** [The free zone](GAA_FREE_ZONE.md)
