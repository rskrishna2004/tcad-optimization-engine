"""l6_verify -- verification + certification: certify(champion,spec)->{mesh,fidelity,coherence,constraints,verdict}. Reuses verify_final.py, fine-mesh + nobtbt + nonlocal decks.

INTERFACE STUB (P0). Fill during the phase that owns this layer.
Keep public signatures stable so the optimizer core (l5) and any BoTorch swap
remain drop-in behind these interfaces.
"""

from .certify import certify, Certificate, constraint_audit, mesh_shift_pct, btbt_fraction_pct
