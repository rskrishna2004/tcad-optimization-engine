# Optimizer backends

The optimizer layer (`l5_opt`) has a swappable backend. Everything else in the
engine — the problem file, the physics guard, knowledge seeding, the experiment
database, certification, the defense dossier — is identical whichever backend
runs. Only the way the next batch of candidates is chosen changes.

Both backends serve **both** jobs. A design campaign and an extraction stage
call the same `Optimizer.propose()`, and neither backend knows or cares whether
the vector it is proposing is a set of device dimensions or a set of
compact-model parameters. Everything below therefore applies to extraction as
written; where a sentence says "designs", read "candidates".

There are two.

| | `scipy_gp_v4_tr` (default) | `botorch_qlogei_tr` (optional) |
|---|---|---|
| Needs | numpy, scipy | Python ≥3.11, torch, botorch |
| Runs on Python 3.6 | yes | no |
| Surrogate | ARD-RBF GP, analytic-gradient MLL | SingleTaskGP + GPyTorch priors |
| Acquisition | analytic Expected Improvement | qLogEI / qLogNEI |
| Acquisition search | argmax over 6000 random candidates | multi-start gradient ascent |
| Batching | constant liar | joint q-batch |
| Constraints | product of independent CDFs | sample-level, second GP output |
| Trust region | TCADOpt schedule | the same TCADOpt schedule |

The trust region is deliberately shared. Its constants (`fail_tol=1`,
shrink ×0.5, `MEANINGFUL_EPS=5e-3`, under-explored restart centre) were tuned
against this project's own audit gauntlet, and that tuning is TCAD campaign
knowledge — not something a library default should overwrite.

## Which one runs

By default, whichever is available:

```python
Optimizer(space)                  # auto: botorch if importable, else scipy
Optimizer(space, prefer="scipy")  # force the dependency-light backend
Optimizer(space, prefer="botorch")# require botorch; raise if missing
```

Or without touching code:

```bash
export TCADOPT_BACKEND=scipy      # or: botorch, auto
export TCADOPT_VERBOSE_BACKEND=1  # print why a backend was chosen
```

Every campaign already prints its backend on the first line, so you can always
confirm which one ran:

```
CAMPAIGN nmos_planar_caps  backend=botorch_qlogei_tr  caps=[1e-07, 1e-08, 1e-09]
```

## Why the log-space acquisition matters here

Expected Improvement is a product of a Gaussian CDF and PDF. Once a campaign
converges, the predicted gain over the incumbent is many standard deviations
away for most candidates, both factors collapse toward zero, and the whole
candidate pool underflows to the same number.

Measured on this engine's own GP, dim=17, 400-trial converged history:

| Trust region | max EI over 6000 candidates | candidates with EI exactly 0.0 |
|---|---|---|
| L = 0.40 (fresh) | 5.0e-141 | 319 |
| L = 0.10 (shrunk) | 3.6e-38 | 2201 |
| L = 0.045 (collapse) | 2.4e-04 | 21 |

At `L=0.10`, more than a third of the pool is numerically indistinguishable
from zero and from each other. `argmax` over that region is not selecting the
most promising design; it is selecting whichever identical zero happens to come
first. qLogEI computes the same quantity in log space and keeps ranking
candidates correctly in exactly this regime.

This is also, in hindsight, what the `explore_frac` slice added in `gp.py`
v4.2 was compensating for. That slice was added because "pure EI+TR converges
to a broad decoy and never discovers a superior narrow basin" — which is the
observable symptom of an acquisition that has gone numerically flat. The slice
treats the symptom; the log-space formulation removes the cause. Both are kept,
because the exploration slice is still useful insurance against a confidently
wrong surrogate.

Reference: Ament, Daulton, Eriksson, Balandat & Bakshy, *Unexpected
Improvements to Expected Improvement for Bayesian Optimization*, NeurIPS 36,
2023.

## Why gradient-based acquisition search matters here

The default backend scores 6000 random candidates and takes the best. In 17
dimensions, 6000 points is `6000^(1/17) ≈ 1.67` samples per axis — under two
per dimension. The pool is not resolving the space; it is sampling it thinly
and hoping. The BoTorch backend instead starts from several promising points
and follows the acquisition gradient to a local maximum, which does not degrade
as dimension grows.

## Measured difference

17-D TCAD-like landscape (broad bowl + ridge coupling + a local trap), budget
36 initial + 6 rounds × 10 = 96 evaluations, 3 seeds:

| Backend | best per seed | mean | gap to optimum |
|---|---|---|---|
| `scipy_gp_v4_tr` | −0.070, −0.235, −0.202 | −0.1688 | 0.3835 |
| `botorch_qlogei_tr` | +0.138, +0.119, +0.017 | +0.0913 | **0.1235** |

67.8% of the remaining gap closed, winning on all three seeds.

Cost: optimizer overhead rose from about 6 s to about 82 s per 96 proposals.
Against TCAD simulations that take minutes each, a 96-evaluation campaign is
hours of solver time, so the extra ~76 s is well under 1% of wall clock. The
optimizer is not the bottleneck; the simulator is. Spending more compute to
choose better designs is close to free.

Both benchmarks are synthetic. They are a sanity check on the optimizer, not a
device result — treat them as evidence the backend is worth trying on a real
campaign, not as a claimed device improvement.

## Which one for an extraction

The same rule, with one extra consideration in favour of the default backend:
an extraction stage typically has four to eight free parameters, where the
dimensionality argument for the BoTorch backend was made at 17. At that size a
6000-point random pool resolves the space reasonably well, and the acquisition
does not go numerically flat as readily. The default backend is a perfectly
good choice for extraction, and it is the one the extraction path was developed
and validated against.

The case for BoTorch on an extraction is the late-stage polish, where the trust
region has shrunk around a good point and the differences between candidates
are small — exactly the regime where analytic expected improvement underflows.
If you have Python 3.11 and the dependencies, letting `auto` pick it costs
nothing.

## Choosing on a real machine

Run the default backend if your TCAD workstation is locked to an older Python,
which is common on solver hosts. Nothing is lost: `scipy_gp_v4_tr` is the
backend every certified campaign in this project used.

If the workstation has Python ≥3.11, install the optional dependencies and let
`auto` pick BoTorch. A safe way to adopt it is to run one problem you already
have a certified champion for, on both backends, same seed, and compare —
the engine keeps every trial in the experiment database, so the comparison is
already recorded.
