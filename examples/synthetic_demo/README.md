# Install Self-Check (not a device simulation)

This script exists for one reason: to let you confirm the **optimizer** installed
and runs, on a machine that may not have any TCAD simulator.

**It does not simulate a device.** It replaces the simulator with a fast
mathematical function so the optimization loop has something to optimize. No
structure is built, no mesh is made, no electrical simulation is run, no TCAD
tool is called. The numbers it prints are from a formula, not from physics.

```bash
python run_demo.py
python run_demo.py --seed 1
python run_demo.py --seed 2
```

If it prints a CHAMPION, your engine is installed correctly and you are ready
for the real thing.

## The real thing

To optimize an actual device, you connect your TCAD simulator and run a real
campaign. That is what the engine is for, and it is documented in:

- **[docs/WORKFLOW.md](../../docs/WORKFLOW.md)** — the complete start-to-finish guide
- [docs/CONNECTING_A_SIMULATOR.md](../../docs/CONNECTING_A_SIMULATOR.md) — pointing the engine at your tools
- [docs/TUNING.md](../../docs/TUNING.md) — setting parallelism and budget for your machine

## What the self-check demonstrates about the optimizer

Even though it is not physics, watching it run shows real optimizer behavior:

1. **The score improves over rounds**, then flattens. The surrogate model is learning.
2. **One tuned quantity lands in the middle of its range**, a genuine trade-off point, because the stand-in function has competing costs just like a real device.
3. **Another rides its upper bound**, a reminder that the optimizer pushes to the edge of whatever range you allow, so your real ranges must be fabricable.
4. **Running several seeds and comparing champions** is exactly how you confirm a global optimum on a real problem.
