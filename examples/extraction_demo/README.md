# Extraction Self-Check (not a circuit simulation)

This script exists for one reason: to let you confirm the **extraction
pipeline** installed and runs, on a machine that may not have a circuit
simulator or a SPICE licence.

**It does not simulate a model card.** It replaces HSPICE with a fast analytic
transistor whose parameters carry the same names and the same physical roles as
the BSIM-CMG ones being fitted. No model card is written, no netlist is run, no
simulator is called. The currents it prints come from a formula, not from a
compact model.

```bash
python run_demo.py
python run_demo.py --seed 1
python run_demo.py --stage 1      # just the first stage
```

If it prints a recovered `phig` close to the hidden true value, your extraction
engine is installed correctly and you are ready for the real thing.

## The real thing

To extract parameters for an actual device, you connect your circuit simulator
and point the engine at your reference curves. That is what it is for, and it is
documented in:

- **[docs/PARAMETER_EXTRACTION.md](../../docs/PARAMETER_EXTRACTION.md)** - the complete start-to-finish guide
- [docs/WRITING_A_PROBLEM.md](../../docs/WRITING_A_PROBLEM.md) - the `fit:` and `stages:` blocks, every field
- [docs/CONNECTING_A_SIMULATOR.md](../../docs/CONNECTING_A_SIMULATOR.md) - pointing the engine at your tools

## What the self-check demonstrates

Even though it is not a compact model, watching it run shows real behaviour you
will see on a real extraction.

1. **The error falls round on round, reported as two numbers.** Sub-threshold
   error in *decades*, on-state error in *percent*. When a fit stalls, the two
   numbers say which half stalled and therefore which parameters to release.

2. **`phig` comes back essentially exact.** That is the parameter stage 1 is
   designed to determine - the gate work function, which is what sets the
   threshold voltage in a surface-potential model that has no `VTH0`.

3. **Some parameters come back badly wrong, and that is the correct result.**
   The stand-in model was built so that `CIT`, `CDSC` and `NFACTOR` enter only
   through one sum, and `ETA0` and `DSUB` only through one product. Their
   individual values are therefore not determined by the data at all - only
   their combination is. No fitting method can recover them, and a tool that
   reports three confident numbers there is misleading you.

4. **The identifiability report finds exactly those pairs.** This is the part
   worth watching. A degenerate fit *fits perfectly*, so the fit error can never
   reveal the problem. The report measures it separately, and tells you which of
   your extracted numbers are measurements and which are arbitrary points on a
   ridge.

5. **Freezing carries forward.** Stage 2 starts with stage 1's four parameters
   held fixed, and says so in its header. That is what makes the result an
   extraction rather than a curve fit.

## Why there are two demos

`examples/synthetic_demo` checks the **design-optimization** path: search a
device's geometry for the best electricals. This one checks the **extraction**
path: fit a model's parameters to curves you already have. They share the
surrogate, the trust region and the database, so if one runs the other almost
certainly will too - but they exercise different objectives and different
evaluators, so both are worth running once.
