# The free zone

Back to the route map: [GAA_COMPACT_MODEL.md](GAA_COMPACT_MODEL.md)

There is a set of BSIM-CMG parameters that cannot change the drain current.
Not "barely change it". Cannot. Every line of the model that reads them is
inside the charge calculation, and the charge calculation does not feed the
current.

That fact is worth a whole page, because it changes how the capacitance half of
the extraction is done.

---

## Why it matters

Normally, fitting the capacitance risks the current. You improve one curve,
something else gets worse, a gate rolls the whole stage back, and you learn
nothing about whether the trade was worth making.

Inside the free zone there is no trade. You can fit those parameters as hard as
you like and the drain current comes back bit-identical. Every current sweep,
every point, zero change. So the gate for that stage asks only one question,
"did the capacitance get better", and a stage that improves the capacitance is
always kept.

That is the difference between a capacitance fit that makes progress and one
that spends its life being rolled back.

---

## The list

Taken from BSIM-CMG 112.1.0, with the line of `bsimcmg_body.include` that
proves each one. The engine carries this table in
`tcadopt/l4_knowledge/cv_scope.py` so it can print it and check it.

| parameter | needs CVMOD=1 | what it does | body.include line |
|---|---|---|---|
| `asat` | | straight multiplier on DvsatCV | 2381-2382 |
| `atcv` | yes | temperature coefficient of VSATCV | 1205, 1277 |
| `cdsp` | | drain-source fringe, all cgeomod | 2596 |
| `cfd` | | outer fringe, drain side | 2533 |
| `cfs` | | outer fringe, source side | 2532 |
| `cgbl` | | bias-dependent gate-substrate, bulkmod non-zero | 3074 |
| `cgbn` | | gate-substrate overlap per fin | 931, 933 |
| `cgbo` | | gate-substrate overlap per gate contact | 931, 933 |
| `cgbw` | | GAA gate-substrate overlap per unit area | 933 |
| `cgdl` | | bias-dependent gate-drain overlap | 2516 |
| `cgdo` | | gate-drain overlap, per unit width | 2516 |
| `cgdp` | | drain fringe, absolute, cgeomod 1 | 2561 |
| `cgsl` | | bias-dependent gate-source overlap | 2512 |
| `cgso` | | gate-source overlap, per unit width | 2512 |
| `cgsp` | | source fringe, absolute, cgeomod 1 | 2560 |
| `ckappab` | | shapes CGBL, bulkmod non-zero | 3074 |
| `ckappad` | | shapes CGDL's bias dependence | 2516 |
| `ckappas` | | shapes CGSL's bias dependence | 2512 |
| `covd` | | drain overlap, absolute, cgeomod 1 | 2556 |
| `covs` | | source overlap, absolute, cgeomod 1 | 2555 |
| `deltavsatcv` | | linear-region term of DvsatCV | 2379-2380 |
| `deltawcv` | | the width the charge is computed on | 349, 2471 |
| `dlc` | | the length the charge is computed on | 168, 2471 |
| `dlcacc` | | accumulation length, bulkmod non-zero | 169 |
| `eta0cv` | yes | DIBL of the charge | 1983 |
| `pclmcv` | | channel-length modulation of the charge | 2386 |
| `psatcv` | | exponent of DvsatCV | 2374-2380 |
| `qmtcencv` | | charge-centroid thickness, feeds coxeff | 2240, 2471 |
| `qmtcencva` | | the same, accumulation, bulkmod non-zero | 2248 |
| `u0cv` | yes | low-field mobility of the charge | 1988, 2086, 2368 |
| `uacv` | yes | mobility degradation of the charge | 2066-2068, 2287 |
| `uccv` | yes | body-effect mobility of the charge | 2066 |
| `udcv` | yes | Coulomb scattering of the charge | 2066-2068, 2287 |
| `vfbsdcv` | | flatband reference of the overlap charge | 2512, 2516 |
| `vsatcv` | yes | saturation velocity of the charge | 2086, 2094, 2368 |

Thirty five parameters. On this project twenty six of them were pushed hard on
a real simulator and **every single one left all eight current sweeps
bit-identical**, reported as `0.000e+00`, twenty six times out of twenty six.

---

## The four that look free and are not

These have names that suggest they belong to the charge. They do not. Treat
them as shared, and handle them the way
[GAA_CHARGE_PARTITION.md](GAA_CHARGE_PARTITION.md) describes.

| parameter | why it is not free |
|---|---|
| `ksativ` | sets both saturation voltages, the current's at line 1901 and the charge's at line 2089 |
| `mexp` | smooths both effective drain voltages, line 1916 and line 2103 |
| `eta1` | multiplies `ETA0` and `ETA0CV` alike, line 1983 and the current's DIBL |
| `qmfactorcv` | despite the name, it enters the surface-potential solve the current is built on, lines 1818, 1835-1845, 1926 |

`KSATIV` is the one that matters most and it has a page of its own.

Positive controls are useful here. When this project measured the free zone, it
deliberately included `KSATIV` and `MEXP` in the survey expecting them to fail
the bit-identical test, and they did, moving the current by 0.47 and 0.17. A
test with no case that fails is not a test.

---

## The CVMOD trap

Nine of the entries above are marked "needs CVMOD=1", and this is the part that
looks like a dead parameter and is not.

BSIM-CMG gives the charge equations private copies of six transport
parameters. The whole block of code that reads them is inside a
`if (cvmod == 1)` condition. At `CVMOD=0` the charge reads the **current's**
values instead, and those six private parameters reach nothing at all.

So at `CVMOD=0`, setting `VSATCV` to any value you like produces exactly zero
change, and a survey will list it as inert. It is not inert. It is unplugged.

Measured on this project: sweeping `VSATCV` across its range moved the drain's
share of the channel charge by 0.03 points at `CVMOD=0` and 6.45 points at
`CVMOD=1`. A factor of two hundred, from one integer in the card.

Two practical notes:

- When you survey parameter effects, do it at both switch settings and compare
  **per parameter**. This project once summed the effects of four parameters
  across the switch, and one parameter with a large effect was hidden by
  another with a larger one that happened to act at both settings.
- Turning `CVMOD` on is a real modelling decision, not a convenience. It means
  the charge is allowed to disagree with the current about mobility and
  velocity. Say so in your report.

---

## Verify it yourself, on your own model version

The table above is from BSIM-CMG 112.1.0. Your simulator may implement a
different version, and a line number is only good for the source you have.

So the engine does not ask you to believe it. It measures it.

```python
from tcadopt.l4_knowledge.cv_scope import free_names, verify_scope

# curves_before: the model's current sweeps at your starting card
# curves_after:  the same sweeps after pushing a free-zone parameter hard
# iv_names:      the names of the current sweeps only
result = verify_scope(curves_before, curves_after, iv_names)
print(result["free"], result["worst_rel"], result["where"])
```

`verify_scope` compares point by point and returns whether the claim held, the
worst relative difference it found, and where. The tolerance is one part in a
billion, which for a deterministic simulator on the same card means
"identical", not "close".

Do this once for your model version, on a few parameters, before you rely on
the list. It costs a handful of simulations and it converts a reading of
somebody else's source into a measurement on your own installation.

---

## How to use the free zone in practice

1. Finish the current side first, stages 1 to 5.
2. Save that card. It is now fixed.
3. Fit the parasitic floor at the off-state bias, from the three measured
   floors.
4. Fit the free zone against the whole gate row at both drain biases, with a
   gate that requires the current to be bit-identical.
5. Only then touch the shared parameters, and price them rather than gate them.

The gate for step 4 is `FrozenGate` in `tcadopt/l6_verify/gate.py`. It accepts
a stage only if the capacitance improved **and** no current sweep moved. If a
current sweep does move, that is genuinely interesting: it means one of the
parameters you thought was free is not free in your model version, and you want
to find out which before doing anything else.

---

## What the free zone cannot fix

Being clear about the limit.

The free zone has no parameter that can move charge from the source end of the
channel to the drain end in the way a real device does as it saturates. The
parameters that shape that are `KSATIV` and `MEXP`, and both are shared with
the current.

So if your model's problem is that the drain's share of the channel charge is
wrong, the free zone will improve the sizes and not the split. That is the
subject of the next page.

**Next:** [Charge partition, the hard part](GAA_CHARGE_PARTITION.md)
