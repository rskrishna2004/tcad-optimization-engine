# Walking one knob at a time, and the fit

Back to the route map: [GAA_COMPACT_MODEL.md](GAA_COMPACT_MODEL.md)

There are two ways to move a card, and you need both, in this order. This page
is about what each one can and cannot find, and about the one calling
convention that will otherwise cost you two runs.

---

## The walk

Take one parameter. Build five cards, one at each of five values spanning its
range. Simulate all five. Keep the best, but only if it also passes
[the rule](GAA_THE_RULE.md). Then move to the next parameter and do it again.

This is slow, it is completely safe, and it cannot regress. It is also the
only method that tells you anything about a single parameter in isolation, so
it is where you find out which knobs are alive, which are dead, and which are
sitting against a bound.

Three things make a walk worth running properly.

**Put the card's own value in the grid.** Otherwise the walk compares the five
values it tried against a card it never measured, and a parameter whose best
value is where it already sits looks exactly like one whose optimum the grid
straddled.

**Derive the grid from measured values, not from your judgement.** Use the
smallest and largest value the parameter has ever carried on a card that was
actually simulated, widened by the range your own probe file already explored.
A span you invent will either be too narrow to find anything or wide enough to
waste four simulations out of five.

**Run two passes.** The first pass fixes each parameter in turn, so the second
pass sees a different card and can find things the first could not. If the
second pass keeps nothing, a third will keep nothing either, and you can stop.

---

## What the walk cannot find, with numbers

A walk converges to a point where no **single** parameter can improve
anything. That is not the same as a point where no **pair** can. Two
parameters that only help when they move together are completely invisible to
a walk, and this is the normal case in a correlated fit, not an exotic one.

Here is the measurement. On this device, across three steps:

| what was done | simulations | gain in the pooled error |
|---|---|---|
| 7 overlap parameters walked one at a time | about 30 | nothing kept |
| 27 further parameters walked, twice over | about 270 | 0.44 per cent |
| one local fit on the pooled residual | about 300 | **4.18 per cent** |

Three hundred one at a time simulations found less than half a per cent. One
fit over the same parameters found more than four per cent, and it got there
by moving `dlc` 56 per cent and `qmtcencv` 364 per cent, two parameters the
walk had just finished declaring settled.

So the order is: walk first, because it is safe and it diagnoses, then fit,
because the walk cannot see the directions that matter most.

---

## Calling the aligner

`tcadopt/l5_opt/lm_align.lm_align` is a box constrained
Levenberg Marquardt. Its signature is long but only five arguments matter:

```
lm_align(evaluate, residual, params, names, ranges, n_iter=12, ...,
         tag='lm', log=None, post=None, prior=None, prior_strength=0.0001)
```

Four of those five are easy and one is not.

**`evaluate`** is called with a list of cards and must return a list of result
rows. Give it a function with a default second argument so it works whether
the aligner passes a tag or not:

```python
def evaluate(cards, tag="lm", **kw):
    return safe_batch(EV, [dict(c) for c in cards], tag)
```

**`residual`** is called with one result row and must return a vector. Accept
either a row or a bare curves dict, because then you can call it yourself for
the self check:

```python
def residual(row):
    curves = row.get("curves") if isinstance(row, dict) and "curves" in row else row
    ...
    return np.concatenate(parts)
```

**`params` is the whole card, as a dict.** `names` is the list of parameters
inside it that you want fitted. `ranges` is a dict keyed by parameter name,
each value a `(low, high, kind)` triple where kind is `"lin"` or `"log"`.

```python
out = lm_align(evaluate, residual,
               dict(card),                               # the WHOLE card
               ["cgdl", "cgsl", "qmtcencv", "dlc"],      # what to fit
               {"cgdl": (0.9e-10, 4.7e-10, "lin"),
                "cgsl": (0.9e-10, 4.7e-10, "lin"),
                "qmtcencv": (0.0686, 450.0, "log"),
                "dlc": (1.17e-10, 2.7e-09, "log")},
               n_iter=10, tag="fit", post=tie, log=print)
```

**It returns a result dict, not a card.** The card is under `params`:

```python
{"params": {...the whole card...}, "ok": True,
 "S0": 0.5843409, "S": 0.5363, "n_evals": 312,
 "names": [...], "moved": [...], "at_bound": [...], "inert": [...],
 "prior_pull": ..., "prior_weight": ..., "history": [...]}

new_card = out["params"]
```

---

## The two mistakes, so you can skip them

**Passing a list of values as `params`.** This raises

```
TypeError: cannot convert dictionary update sequence element #0 to a sequence
```

which is what Python says when `dict(x)` gets a list whose first element is
not a key and value pair. The aligner does `dict(params)` internally. That
message is the whole diagnosis: params is a dict.

**Reading the top level of the return for parameter names.** They are not
there. The top level holds `params`, `ok`, `S0`, `S` and the rest, so a reader
that looks for `cgdl` at the top finds nothing and concludes the aligner
failed. It did not fail. It ran, and the answer was one unwrap away.

That second one cost a whole run, and it was worse than it looks: four
different calling conventions were tried in one step, all four returned a
perfectly well formed result dict, and the step reported that none of them had
worked.

---

## So do not trust a reading. Count the work.

"It returned something" is not evidence that it fitted anything. Three of the
four conventions above returned a tidy `params` dict having simulated exactly
one card, which is not enough to have built a Jacobian.

Wrap `evaluate` in a counter and probe each candidate convention with
`n_iter=1`, then pick the one that actually ran the algorithm:

```python
EVN = [0]

def evaluate(cards, tag="lm", **kw):
    EVN[0] += len(cards)
    return safe_batch(EV, [dict(c) for c in cards], tag)
```

On the real device that printed:

```
      convention                                      cards  verdict
      1. params = the whole card as a dict, ranges      9  usable
      2. params = the whole card as a dict, ranges      1  usable
      3. params = a list of name and value pairs, r     1  usable
      4. params = a list of name and value pairs, r     1  usable

      chosen: convention 1, because it simulated 9 cards while
      the others simulated 1, 1, 1.
```

Nine cards is one evaluation, a two sided Jacobian on one parameter, and a six
point line search. That is the algorithm running. One card is not.

---

## Which parameters to put in

Not all of them. A parameter the data cannot move only makes the Jacobian
harder to invert.

Use your own probe file. `tcadopt/l1_spec/bias_pair.probe_row` records, for
each parameter, how much a curve moves between the two ends of its range. Take
the ones above about one per cent and leave the rest out. On this device that
cut 35 candidates to 25, and the ones that were dropped were measured dead,
not guessed dead:

```
      uacv    0.0 %     udcv     0.0 %     asat     0.0 %
      psatcv  0.0 %     uccv     0.0 %     pclmcv   0.0 %
```

The aligner will also tell you during the run. Watch the `flat, dropped:` line
in each iteration. On this device `vsatcv` and `u0cv` appeared there in all
five iterations, which agrees exactly with the probe file and with both having
been driven to a bound by an earlier fit.

---

## Reading convergence honestly

The aligner stops on its own `tol`, which defaults to 0.01, after two
iterations that each gain less than one per cent. That is not the same as
having found the minimum. Read the gain sequence before you decide whether
more iterations would help:

```
    LM start: S = 0.584341 over 728 residual entries, 25 parameters
    LM it 1: S -> 0.555387  (-4.95%)
    LM it 2: S -> 0.548079  (-1.32%)
    LM it 3: S -> 0.541461  (-1.21%)
    LM it 4: S -> 0.538201  (-0.60%)
    LM it 5: S -> 0.536466  (-0.32%)
```

It stopped after 5 of the 10 iterations it was given. The gains shrink by
roughly a factor of 0.65 each time, so the remaining gain in that basin
extrapolates to about 0.6 per cent of `S`, which is 0.3 per cent of the pooled
error because pooled is the square root of `S`. Three tenths of a per cent is
not worth another run, and now you know that rather than guessing it.

If instead the last gain is still large, or the sequence is not decaying, the
fit was cut off and more iterations will pay.

One more thing to watch in the output. `at_bound` lists parameters that
finished against the edge of their box. A fit that ends with several
parameters pinned has not converged, it has been stopped by a box you drew,
and the right response is to widen the box and run again rather than to
believe the answer.

---

## And judge the result like everything else

The fit's card gets no special treatment. It goes through
[the same five conditions](GAA_THE_RULE.md) as a hand picked value, measured
against the same baseline, and if it fails, the card you started with stands:

```
  --- the fit's card, judged by the same five conditions ---
        the fit's card passes all five
      pooled 0.027146 against 0.028331 on the card it started
      from, which is -4.18 per cent.
      KEPT.
```

Write the card the walk produced to disk **before** you call the aligner. Then
a convention you have read but never run cannot cost you the work that already
succeeded.

---

Next: [Knowing when it is finished](GAA_WHEN_TO_STOP.md).
