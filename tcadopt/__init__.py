"""TCADOpt -- a physics-aware Bayesian optimization engine for semiconductor
device simulation, and a compact-model parameter extraction engine.

Two things live here behind one optimizer core:

  * DESIGN optimization  -- search a device's geometry and doping for the best
    electrical characteristics.  `tcadopt.l8_orch.run_campaign`
  * PARAMETER EXTRACTION -- fit a compact model's parameters to reference
    curves from a device you have already simulated.
    `tcadopt.l8_orch.run_fit`

The surrogate model, the trust region, the physics guard, the experiment
database and the campaign loop are shared by both. See docs/ARCHITECTURE.md.
"""

__version__ = "1.1.0"
__all__ = ["__version__"]
