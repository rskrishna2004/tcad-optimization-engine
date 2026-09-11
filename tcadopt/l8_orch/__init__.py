"""l8_orch -- orchestrator state machine + LLM-reasoning hooks (ingestion/failure/strategy/interpret). Selective L3 in-loop.

INTERFACE STUB (P0). Fill during the phase that owns this layer.
Keep public signatures stable so the optimizer core (l5) and any BoTorch swap
remain drop-in behind these interfaces.
"""

from .run_campaign import run_campaign
from .run_pareto import run_pareto, pareto_front, champions_on_front
from .run_fit import run_stage, load_frozen, save_frozen
