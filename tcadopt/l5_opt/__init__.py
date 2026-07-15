"""l5_opt -- optimization engine: propose(history,space,scorer,n,mode). GP surrogate, BO, ParEGO multi-objective, feasibility-aware, floor-detection, margin-exploit. Reuses gp.py v3, refine_*.py.

INTERFACE STUB (P0). Fill during the phase that owns this layer.
Keep public signatures stable so the optimizer core (l5) and any BoTorch swap
remain drop-in behind these interfaces.
"""
