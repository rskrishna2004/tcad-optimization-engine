"""l3_exec -- simulate(deck)->plt/logs/status, extract(plt,protocols)->metrics, failure classifier. Reuses plt_parser.py.

INTERFACE STUB (P0). Fill during the phase that owns this layer.
Keep public signatures stable so the optimizer core (l5) and any BoTorch swap
remain drop-in behind these interfaces.
"""

from .metrics import (foms_from_idvg, foms_multibias, metrics_from_plt, constant_current_vt, subthreshold_swing, dibl_mV_per_V, ft_GHz)

from .hspice_parser import parse_lis, sweep_columns, parse_measures
from .targets import load_targets, load_iv_targets, load_cv_targets, summarize
