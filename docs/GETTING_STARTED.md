# Getting Started

This guide takes you from a fresh clone to running the engine, first on synthetic problems that need no simulator at all, and then pointing you toward connecting your real tools.

TCADOpt does two jobs. **Design optimization** searches a device's geometry and doping for the best electricals. **Parameter extraction** fits a compact model's parameters to reference curves from a device you already have. Both are verified below, and each has its own guide afterward.

---

## 1. Requirements

- Python 3.6 or newer
- The three Python packages in `requirements.txt` (numpy, scipy, PyYAML)
- Optional, only for optimizing real devices: any TCAD simulator that provides a structure/mesh builder and an electrical device solver
- Optional, only for extracting real model parameters: any circuit simulator that can run a SPICE netlist from the command line (the reference implementation drives HSPICE)

Nothing beyond the three Python packages is needed for the two self-checks in sections 3 and 4.

---

## 2. Install

```bash
git clone https://github.com/rskrishna2004/tcad-optimization-engine.git
cd tcad-optimization-engine
pip install -r requirements.txt
```

**Then run the setup check, before anything else:**

```bash
python check_setup.py
```

This confirms Python and all three dependencies (numpy, scipy, PyYAML) are
installed and importable, reports the engine version, and tells you which
simulator tools are currently configured for each path. Neither tool is needed
yet, so "NOT SET" at this stage is expected and fine. If `pip install` did not
work on the first try
(a very common first-run snag, especially on Windows where `pip` sometimes
is not on the PATH), `check_setup.py` prints the exact alternative command
to run:

```bash
pip3 install -r requirements.txt
python -m pip install -r requirements.txt
py -m pip install -r requirements.txt        # Windows
```

Do not move on to the next step until `check_setup.py` reports that
everything is installed. Skipping this is the single most common reason a
first run fails, and the error you would see instead
(`ModuleNotFoundError: No module named 'yaml'`) is this exact problem,
just reported from deep inside the engine instead of up front.

---

## 3. Run the design-optimization self-check (no simulator needed)

The synthetic demo replaces the physics simulator with a fast mathematical function that behaves like a device: it has an on-current-like quantity to maximize and a leakage-like quantity to keep under a cap. This lets you watch the entire optimization pipeline work in seconds on any computer.

```bash
python examples/synthetic_demo/run_demo.py
```

You will see output similar to:

```
CAMPAIGN synthetic_demo  backend=scipy_gp_v4_tr
  [physics-seed] knowledge-guided init points
  init best score = ...
  round 0 best = ...
  round 1 best = ...
  ...
  CHAMPION: ...
  convergence evidence: ...
```

What is happening, step by step:

1. The engine reads the demo problem file and builds the parameter space and the scoring function.
2. It seeds the first batch using physics-style guidance, then fills the rest with a space-filling sample.
3. It runs a batch of synthetic "simulations".
4. It fits a surrogate model to all results so far, then chooses the next batch by balancing exploitation and exploration inside a trust region.
5. It repeats for several rounds, improving the best score.
6. It reports a champion and a short block of convergence evidence you can use to judge how confident the result is.

---

## 4. Understand the output

- **init best score**: the best design found in the initial sampling, before any learning.
- **round N best**: the best design after the surrogate-guided batch N. This should improve over rounds.
- **CHAMPION**: the best design across the whole campaign, with its metric values.
- **convergence evidence**: the gap between the champion and the runner-up, the spread of the top designs, and how many trust-region restarts happened. A small gap means many near-equal designs exist; a large gap with tight clustering means a sharp, well-separated optimum.

---

## 5. Run the extraction self-check (no simulator needed)

The extraction demo does the same favour for the other path. It replaces the circuit simulator with a stand-in transistor whose parameters carry the same names and physical roles as real compact-model ones, and it runs the complete staged extraction against it.

```bash
python examples/extraction_demo/run_demo.py
```

Three things are worth watching:

- **The error is two numbers, not one.** Sub-threshold error is reported in *decades* and on-state error as a *percentage*, because drain current spans about eight decades and one measure cannot serve both ends. When a fit stalls, the two numbers say which half stalled.
- **`phig` comes back essentially exact.** That is the gate work function, and it is what stage 1 exists to determine. The stand-in model has a hidden true value the optimizer was never given.
- **Some parameters come back badly wrong, and that is the correct result.** The stand-in was built so that three of its parameters enter through a single sum and two more through a single product. Their individual values are simply not determined by the data. The identifiability report at the end finds exactly those pairs and says so — which the fit error can never do, because a degenerate fit fits perfectly.

## 6. Run multiple seeds for global confidence

Bayesian optimization cannot mathematically prove it found the global optimum on a black-box function. The practical way to gain confidence is to run several independent seeds and check they agree. The demo supports this:

```bash
python examples/synthetic_demo/run_demo.py --seed 0
python examples/synthetic_demo/run_demo.py --seed 1
python examples/synthetic_demo/run_demo.py --seed 2
```

If the champions from different seeds land in the same region, that agreement is strong practical evidence you are at or near the global optimum.

---

## 7. Move to a real device

When you are ready to optimize a real transistor, you connect the engine to your TCAD simulator by writing a small adapter. This is the only integration work required, and it is explained in full in [CONNECTING_A_SIMULATOR.md](CONNECTING_A_SIMULATOR.md).

The flow for a real design problem is:

1. Write a problem YAML file describing the parameters, ranges, objective, and constraints. See [WRITING_A_PROBLEM.md](WRITING_A_PROBLEM.md).
2. Write your simulator deck template with the tunable parameters marked, and the adapter that renders a candidate into a deck, runs the simulator, and parses the electrical output. See [CONNECTING_A_SIMULATOR.md](CONNECTING_A_SIMULATOR.md).
3. Run a campaign:
   ```bash
   python -m tcadopt.l8_orch.run_campaign path/to/your_problem.yaml
   ```
4. Optionally trace a Pareto front:
   ```bash
   python -m tcadopt.l8_orch.run_pareto path/to/your_pareto_problem.yaml
   ```

---

## 8. Move to a real extraction

The flow for a real extraction is shorter, because there is only one tool to connect:

1. Export your reference curves to CSV, one row per bias point. See [PARAMETER_EXTRACTION.md](PARAMETER_EXTRACTION.md).
2. Point the engine at your circuit simulator:
   ```bash
   export TCADOPT_SPICE_TOOL="hspice"
   ```
3. Write a fit spec describing the target curves and the stage schedule. See [WRITING_A_PROBLEM.md](WRITING_A_PROBLEM.md).
4. Run it:
   ```bash
   python -m tcadopt.l8_orch.run_fit path/to/your_fit.yaml
   ```

[EXTRACTION_TUTORIAL.md](EXTRACTION_TUTORIAL.md) walks through all four steps on a worked example, with every printed line explained.

---

## 9. Where to go next

- To optimize a real device, end to end: [WORKFLOW.md](WORKFLOW.md)
- To extract real model parameters, end to end: [PARAMETER_EXTRACTION.md](PARAMETER_EXTRACTION.md)
- To understand how the engine works internally: [ARCHITECTURE.md](ARCHITECTURE.md)
- To learn the problem file format in depth: [WRITING_A_PROBLEM.md](WRITING_A_PROBLEM.md)
- To see how physics is used to guide and audit the search: [PHYSICS_KNOWLEDGE.md](PHYSICS_KNOWLEDGE.md)
- To read a real optimization story with its lessons: [CASE_STUDY.md](CASE_STUDY.md)
