# The rule that decides what may change the card

Back to the route map: [GAA_COMPACT_MODEL.md](GAA_COMPACT_MODEL.md)

An extraction produces a lot of candidate cards. Some come from a fit, some
from a scan, some from a closed form solve, some from a list of values you
tried by hand. Every one of them has to get past something before it is
allowed to become the card you keep.

This page is about that something. It is short, it is boring, and getting it
wrong is the single most expensive mistake available to you. On this project
it cost one whole step, and the step reported success while doing it.

---

## Write the rule down before the run, not after

The rule goes in the script, above the part that moves anything, and it gets
printed into the log when the run starts. Not because printing is tidy, but
because a threshold you choose after seeing the answer is not a rule. It is a
preference wearing a rule's clothes, and you will not be able to tell the
difference six weeks later when you are writing this up.

Here is the rule this project settled on. Five conditions, and a card goes
forward only if all five hold.

1. The **pooled** error over every capacitance point falls.
2. The quadrature total of the per curve attofarad errors falls.
3. No curve ends up worse, in per cent, than the worst curve already was.
4. No curve ends up worse, in attofarads, than the worst already was.
5. The drain current sweeps are unchanged, to one part in a billion.

---

## Every threshold is read off the baseline, not chosen

Look again at conditions 3 and 4. They do not contain a number. They contain a
rule for finding a number, and the number comes from the card you are
measuring against:

```python
PCT_CAP = max(baseline["pct"][name] for name in CV_NAMES)
AF_CAP = max(baseline["abs"][name] for name in CV_NAMES)
```

On the real device those came out as 6.330 per cent, which was Cgd at the low
drain bias, and 1.7834 attofarads, which was Cgg at the low drain bias. So the
rule reads "no curve may end up worse than the worst curve already was", and
nobody had to pick anything.

This matters because of what happened when I did pick something. An earlier
draft of this rule had a per curve cap of 0.35 attofarads, chosen by me
because it looked reasonable. The best card available asked for a rise of
0.3232 attofarads on one curve. It passed by five thousandths of an
attofarad. Had the device's capacitances been slightly different, or had my
estimate of that rise been slightly off, a hand picked number would have
thrown away an 11 per cent improvement, and the log would have said the card
was refused for a good reason.

Conditions 1 and 2 need no threshold at all, which is why they carry the
weight. They are totals with no weights and no normalisation in them, so
nothing can improve either of them by getting worse somewhere that happened to
be cheap. That is exactly what a weighted objective allows and it is why
[the objective page](GAA_THE_OBJECTIVE.md) exists.

---

## Guard every card that enters the pipeline, not just the fits

This is the one that cost the step.

The project had a guard class, `tcadopt/l1_spec/guard.CurveGuard`, and it
worked. It was wrapped around the output of the local fit. It was not wrapped
around anything else.

The step in question had a ladder that simulated eight candidate cards and
picked the best one by the objective. That pick then became the card the rest
of the step built on. The guard never saw it. The pick had Cgd at the high
drain bias at 0.667 per cent against the baseline's 0.184, a rise of 262 per
cent on a guard that allows 10, and it walked straight through because nobody
asked.

Later in the same step the fit's own result was correctly refused by the
guard. The log printed `NOT kept: the guard refused Cgd 0.60, Cgs 0.60,
Cgg 0.60` and looked like the machinery working.

**A guard that only wraps one of the four places a card can come from is not a
guard.** Write the rule as a function and call it on every candidate, from
every source, including the ones you are confident about:

```python
def rule(d, tag="", loud=True):
    """Judge one card against the baseline. Returns (ok, reasons)."""
    why = []
    if d["pooled"] >= BASE["pooled"]:
        why.append("pooled %.6f is not below %.6f"
                   % (d["pooled"], BASE["pooled"]))
    if d["absq"] >= BASE["absq"]:
        why.append("aF total %.4f is not below %.4f"
                   % (d["absq"], BASE["absq"]))
    for name in CV_NAMES:
        if d["pct"][name] > PCT_CAP * (1 + 1e-9):
            why.append("%s reaches %.3f per cent, past the %.3f any curve"
                       " had reached" % (LABEL[name], d["pct"][name], PCT_CAP))
        if d["abs"][name] > AF_CAP * (1 + 1e-9):
            why.append("%s reaches %.4f aF, past the %.4f any curve had"
                       " reached" % (LABEL[name], d["abs"][name], AF_CAP))
    if abs(d["iv"] - BASE["iv"]) > 1.0e-9:
        why.append("the drain current moved by %.2e" % (d["iv"] - BASE["iv"]))
    if loud:
        print("   %s %s" % (tag, "REFUSED: " + "; ".join(why) if why
                            else "passes all five"))
    return (not why), why
```

---

## When a card is refused, revert to the step's entry card

Not to the last thing some earlier part of the step happened to leave behind.

The same step got this wrong too, and the two mistakes compounded. The
unguarded ladder pick became the working card. The fit on top of it was
refused. The revert went back to the ladder pick, because that was what the
fit had started from. So the card that went into the next part was already
8 per cent worse than the card the step began with, and every comparison
printed from that point onward was measured against it. Three later parts all
reported their results relative to a regression, and all three looked
reasonable.

Keep the entry card in a variable, never overwrite it, and revert to it:

```python
ENTRY_CARD = dict(BEST)          # set once, at the top, never touched again
ENTRY_D = dict(BEST_D)
...
if not good:
    say("not kept. The card this step started from stands.")
    BEST, BEST_D = dict(ENTRY_CARD), dict(ENTRY_D)
```

And write the consequence into the rule's own text, so the reader of the log
knows it before anything runs: **if nothing passes, the card that ships is the
one the step started with.**

---

## Find the baseline by measurement, not by its name

You will have a lot of cards on disk and a lot of constants in your scripts
with names like `CARD32`. Do not trust any of them.

The convention in the scripts on this project turned out to be that `CARDnn`
means "the card step nn **started** from", not the card step nn produced. A
later step loaded `CARD32` believing it was step 32's result, and got step
25's card instead. What it printed was:

```
      what                              printed before    this run     drift
      the eight current sweeps             0.014114     0.014114  0.00e+00
      the eight capacitance curves         0.026916     0.040472  1.36e-02
```

The drain current reproduced to zero and only the capacitance moved, which was
the clue: step 32 was a charge only step, so the card it started from has
identical current parameters and different charge parameters. And 0.040472 is
exactly the number step 32's own log gives for where it began.

The repair is to stop reading names. Gather every card that could be the
baseline, simulate all of them in one batch, and pick the one that matches the
numbers the earlier log printed:

```
      card                                current      mean     pooled   sixteen   matches
      --------------------------------------------------------------------------------------
      CARD33                              0.014114  0.026916  0.032142  0.024116   4 of 4
      CARD32                              0.014114  0.040472  0.048541  0.034790   1 of 4
      CARD29                              0.014117  0.040472  0.048541  0.034790   0 of 4
      CARD25                              0.014117  0.040472  0.048541  0.034790   0 of 4
      step32_out/step32_card.json         0.014114  0.026916  0.032142  0.024116   4 of 4
      step33_out/step33_card_part4.json   0.014114  0.029940  0.034768  0.025789   1 of 4
```

Two of them match all four numbers, which is expected because one is a copy of
the other. The rest are now identified for good, and the question of which
constant means what never has to be asked again. The cost is a handful of
simulations at the start of a run, and it is the cheapest insurance in this
whole guide.

---

## The no stop rule

A run that has four hours of simulation behind it must not be endable by a
measurement.

A probe pushes a parameter to the end of its declared range on purpose. Some
of those cards make the circuit simulator fail to converge and some make the
model's own checking file reject the card. **Both of those are results.** If
your script treats them as accidents and exits, you lose the hours.

This project lost a slot of two and a half hours to exactly that. The repair
is two lines and one discipline:

```python
def safe_batch(ev, cards, tag):
    """Evaluate, and never let a card the model refuses stop the run."""
    try:
        return ev.evaluate_batch([dict(c) for c in cards], tag=tag)
    except Exception as exc:
        return [{"status": "error", "error": "%s: %s"
                 % (type(exc).__name__, exc)} for _ in cards]
```

And then have the script count its own exits and say so in the log, at the
top, before anything has run:

```python
HARD_EXITS_ALLOWED = 1
text = open(os.path.abspath(__file__)).read()
n = text.count("sys." + "exit(")      # split so this line is not a hit
print("this file contains %d hard exit(s) and is allowed %d" % (n, HARD_EXITS_ALLOWED))
if n > HARD_EXITS_ALLOWED:
    raise SystemExit("more exits than allowed")
```

One exit, inside one function, reached only by a setup check or by the
baseline failing to reproduce. No measurement anywhere in the run can end it.
If that count ever creeps up, the self test fails before a single simulation
has been spent.

---

## Read every card in per cent and in attofarads

The rule has both because the two disagree about what matters.

```
      curve      ------ per cent ------    -------- attofarads --------
                  base   card A   card B    base   card A   card B
      Cgg 0.05   3.312    1.972    2.102   1.7834  0.8989   1.1334
      Cgd 0.60   0.184    0.667    2.482   0.0258  0.0938   0.3481
```

Cgd at the high drain bias going from 0.184 to 2.482 per cent is a factor of
thirteen and looks fatal. In attofarads it is 0.026 to 0.348 on a curve whose
own root mean square is 14 attofarads, which is a quarter of one per cent of
the curve. Meanwhile Cgg at the low drain bias improving by 37 per cent is
worth 0.65 attofarads, which is nearly twice as much real capacitance in the
other direction.

Per cent tells you how well the model describes each curve. Attofarads tell
you what a circuit built on the card will feel. A rule with only one of them
in it will make a trade you would not have agreed to.

---

Next: [The extraction order](GAA_EXTRACTION_ORDER.md), which is the order to
apply all of this in.
