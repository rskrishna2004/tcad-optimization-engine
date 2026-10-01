"""l6_verify -- verification + certification: certify(champion,spec)->{mesh,fidelity,coherence,constraints,verdict}. Reuses verify_final.py, fine-mesh + nobtbt + nonlocal decks.

INTERFACE STUB (P0). Fill during the phase that owns this layer.
Keep public signatures stable so the optimizer core (l5) and any BoTorch swap
remain drop-in behind these interfaces.
"""

from .certify import certify, Certificate, constraint_audit, mesh_shift_pct, btbt_fraction_pct
from .identifiability import (jacobian, analyse, report,
                              residual_vector, plan_perturbations,
                              converged_step)
from .gate import (StageGate, scope_check, enforce_scope, census_from_probe,
                   format_scope_report, no_regression, SCOPE_TOL,
                   seed_greedy, format_seed_greedy)
from .response import (map1d, joint_best, format_map, refine,
                       map_signed, format_signed)
from .inventory import (read_model_params, raw_block, find_listing,
                        diff_card, format_inventory, core_names,
                        variants, twins, format_twins)

__all__ = ["certify", "Certificate", "constraint_audit", "mesh_shift_pct",
           "btbt_fraction_pct", "jacobian", "analyse", "report",
           "residual_vector", "plan_perturbations", "converged_step",
           "StageGate", "scope_check", "enforce_scope", "census_from_probe",
           "format_scope_report", "no_regression", "SCOPE_TOL",
           "seed_greedy", "format_seed_greedy",
           "map1d", "joint_best", "format_map", "refine", "map_signed",
           "format_signed", "read_model_params",
           "raw_block", "find_listing", "diff_card", "format_inventory",
           "core_names", "variants", "twins", "format_twins"]
