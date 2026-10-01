# Preparing your reference data

Back to the route map: [GAA_COMPACT_MODEL.md](GAA_COMPACT_MODEL.md)

The engine reads two CSV files. Getting them right is the single highest value
thing you will do in this whole process, so this page is long.

---

## The two files

```
targets/iv_targets.csv     your current sweeps
targets/cv_targets.csv     your capacitance sweeps
```

Both are plain CSV with a header row. Extra columns are ignored, so you can
carry whatever provenance information you like alongside the data. That turns
out to be a good idea, and there is a section on it below.

---

## iv_targets.csv

### Columns the engine reads

| column | what goes in it |
|---|---|
| `device` | a short name, for example `nsfet_n`. A name ending in `_p` is treated as p-type. |
| `sweep` | `IdVg` or `IdVd` |
| `bias` | the voltage held fixed for this sweep. For `IdVg` that is the drain voltage, for `IdVd` it is the gate voltage. |
| `vg` | gate voltage at this point |
| `vd` | drain voltage at this point |
| `id_uA_per_um` | drain current in microamps per micron, **or** use `id_A` for amps |
| `usable` | `yes` or `no` |

### How sweeps get their names

The engine builds a sweep name from three of those columns:

```
<device>_<sweep>_<absolute value of bias>
```

So a row with `nsfet_n`, `IdVg`, `0.05` joins the sweep called
`nsfet_n_IdVg_0.05`. Every row with those same three values is one curve. You
never name a sweep yourself, and you will see these names in every line the
engine prints, so it is worth recognising them.

### A real header

```
device,sweep,bias,vg,vd,vs,vb,phig_eV,phig_provenance,id_A,abs_id_A,id_uA_per_um,ig_A,usable,exclude_reason
```

Only seven of those are read. The rest are carried for the human.

---

## cv_targets.csv

### Columns the engine reads

| column | what goes in it |
|---|---|
| `device` | same short name as in the I-V file |
| `vd` | the drain voltage this sweep is held at |
| `vg` | gate voltage at this point |
| `Cgg_F` | total gate capacitance, in farads |
| `Cgd_F` | gate to drain, in farads |
| `Cgs_F` | gate to source, in farads |
| `Cgb_F` | gate to body, in farads |
| `usable` | `yes` or `no` |

### A real header

```
device,vd,vg,freq_Hz,phig_eV,phig_provenance,Cgg_F,Cgd_F,Cgs_F,Cgb_F,Cgg_aF,gate_row_closure_pct,usable,exclude_reason
```

---

## The gate row, and why the total is not enough

This is the most important idea on the page. It took this project nineteen
extraction steps to learn it properly, so it is written out in full.

### What the four numbers are

At any one bias there are four capacitances that describe what the gate is
coupled to:

```
Cgd   how much charge leaves the drain    when the gate voltage changes
Cgs   how much charge leaves the source   when the gate voltage changes
Cgb   how much charge leaves the body     when the gate voltage changes
Cgg   the total, and Cgd + Cgs + Cgb = Cgg exactly
```

Together they are called the gate row. The sum is exact, not approximate, and
that gives you a free check on your own data, described below.

### Why fitting only Cgg hides the real error

Suppose your model puts too much charge on the source end of the channel and
too little on the drain end. The two errors have opposite signs. Add them up
and they partly cancel. Cgg looks fine.

That is not a hypothetical. On this project the model's total gate capacitance
was within about 5 percent while the drain's share of the channel charge was
16 percent against the device's 48 percent. The model was putting the channel
charge in completely the wrong place and the total could not see it.

Worse, it makes a whole family of parameters look dead. The parameters that
control velocity saturation and channel-length modulation on the charge side
move charge **between** the two ends of the channel. They barely change the
sum. So a survey that scores those parameters on Cgg reports every one of them
as having no effect, which is true of the sum and false of the device.

So: **put all four capacitances in your CSV, not just the total.**

### The row and the column are different things, and both sum to Cgg

This one is a genuine trap and it cost this project a whole extraction step.

There are two different sets of four numbers you can get out of a simulator,
and they look identical:

**The row** is what you want. Drive each of the other terminals in turn and
measure the current into the gate. This is minus the derivative of the gate
charge with respect to each terminal's voltage.

**The column** is what you get if you drive the gate and measure the current
out of the other three terminals. This is minus the derivative of each
terminal's charge with respect to the gate voltage.

They are different numbers. They both add up to Cgg. So a closure check passes
for either one and **cannot tell you which you have.**

Measured on this project's own device at one bias, gate at 0.6 V and drain at
0.05 V:

```
the column:   Cdg 23.95   Csg 26.27   Cbg 0.27    total 50.50 aF
the row:      Cgd 16.36   Cgs 33.87   Cgb 0.27    total 50.50 aF
```

Same total. The drain and source split differs by 7.6 aF, which is 15 percent
of the total. Fit the wrong one and you will be chasing an error that does not
exist.

Your reference data should hold the **row**, because that is the convention
compact-model capacitance targets use, and because the engine reads the row
out of the circuit simulator to compare against it.

### The closure check, which is free

Because the sum is exact, you can check your own extraction of the data:

```
closure error = 100 * |Cgd + Cgs + Cgb - Cgg| / Cgg
```

Add that as a column. On good data it comes out at a few parts in a million.
On this project the column is called `gate_row_closure_pct` and it reads
`0.000002`. If yours reads 5 or 50, something is wrong in how you pulled the
numbers out of the simulator, and you want to know that now.

---

## The `usable` column

Any row with `usable` set to anything other than `yes` is dropped when the file
is loaded, and the engine prints how many it dropped. It does not hide it.

Use this rather than deleting rows. A deleted row is a decision nobody can
review. A row marked unusable with a reason in the next column is a decision
with an argument attached.

Reasons that have come up on this project and deserve the flag:

- the sweep stalled and these are the points after the last good one
- the closure check on this row is over 1 percent
- this bias is inside a region where the solver was visibly struggling
- this run used a different work function from the rest of the set

Add an `exclude_reason` column and write the reason in words. Future you will
want it.

---

## Carry your provenance

Extra columns are ignored by the engine and read by people. Put in whatever
lets you answer "where did this number come from" six months later:

- `phig_eV` - the work function the run used. If two of your sweeps disagree
  here, they describe different devices.
- `phig_provenance` - how that value was arrived at, in a few words.
- `freq_Hz` - the small-signal frequency the capacitance was measured at.
- `vs`, `vb` - the source and body voltages, so it is explicit they were zero.
- `Cgg_aF` - the same number in attofarads, so a human can read the file.

---

## Loading and checking

Once both files are written, check what the engine sees, before fitting
anything:

```bash
cd tcad-optimization-engine
python -c "
from tcadopt.l3_exec.targets import load_targets, summarize
t = load_targets('targets/iv_targets.csv', 'targets/cv_targets.csv')
print(summarize(t))
"
```

**You should see** the number of sweeps, the total number of bias points, the
name of every sweep, and a line saying how many rows were excluded and why.

Read that list of sweep names carefully. This is the moment when a typo in the
`bias` column turns into two half-sweeps with different names, and it is far
cheaper to see it here than to wonder later why one curve fits badly.

### Four things to verify by eye

1. **The sweep count is what you expect.** Ten sweeps means ten, not eleven
   with one of them holding four stray points.
2. **Every sweep has the point count you expect.** One short sweep means a
   stalled run got in.
3. **The excluded count matches what you intended to exclude.** If you marked
   25 rows and it reports 3, your `usable` column is not being read, probably
   because of stray whitespace.
4. **The current spans the decades you expect.** Compute it directly:

```bash
python -c "
import csv, math
lo, hi = 1e30, 0.0
for r in csv.DictReader(open('targets/iv_targets.csv')):
    if r['sweep'] == 'IdVg' and r['usable'] == 'yes':
        i = abs(float(r['id_uA_per_um']))
        if i > 0:
            lo, hi = min(lo, i), max(hi, i)
print('decades of current in the Id-Vg data: %.2f' % math.log10(hi/lo))
"
```

Six to seven decades is healthy. Three means your sweeps start above threshold
and the subthreshold half of the fit has almost nothing to work with.

---

## The one mistake that is hardest to undo

Everything in the engine assumes your reference data is right. It has no way to
know otherwise, and it will fit whatever you hand it, confidently.

So the order is: get the data right, check it four ways, and only then start
extracting. If a fit later refuses to improve, come back to this page before
you blame the optimizer. On this project the answer was in the data more often
than it was in the engine.

**Next:** [The model card for a nanosheet](GAA_MODEL_CARD.md)
