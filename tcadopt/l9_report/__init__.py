"""l9_report -- certificate + report generation (generalizes the hackathon report).

INTERFACE STUB (P0). Fill during the phase that owns this layer.
Keep public signatures stable so the optimizer core (l5) and any BoTorch swap
remain drop-in behind these interfaces.
"""

from .where import (bands, verdict, format_report, contrast,
                    format_contrast, band_vector, band_probe)
from .gaterow import (reference_row, compare, intrinsic, collapse,
                      format_compare, format_collapse, format_row,
                      model_row, row_table, format_row_table, rms_by_term,
                      format_rms_by_term, split, format_split,
                      floor_of, floor_solve, best_constant)

__all__ = ["bands", "verdict", "format_report", "contrast",
           "format_contrast", "band_vector", "band_probe",
           "reference_row", "compare", "intrinsic", "collapse",
           "format_compare", "format_collapse", "format_row",
           "model_row", "row_table", "format_row_table", "rms_by_term",
           "format_rms_by_term", "split", "format_split",
           "floor_of", "floor_solve", "best_constant"]
