"""l1_spec.compile -- turn a Problem Spec YAML into runtime objects.

compile(spec_path) -> CompiledProblem{spec, space, cap_values, make_scorer,
                                       models, fidelity, budget, verify_plan}

The engine has no problem-specific code: everything downstream (optimizer, decks,
verification) is driven by what this returns. New objective/constraint/value = new
YAML, no code change.

$Id: compile.py, 2026/06/18 [YOUR NAME] $
"""
import os

try:
    import yaml
except ImportError:
    raise ImportError(
        "\n\nTCADOpt is missing a required package (PyYAML).\n"
        "Fix this with:\n"
        "    pip install -r requirements.txt\n"
        "If that command is not found, try:\n"
        "    pip3 install -r requirements.txt\n"
        "    python -m pip install -r requirements.txt\n"
        "    py -m pip install -r requirements.txt        (Windows)\n"
        "Then verify with:  python check_setup.py\n")

from .paramspace import ParamSpace
from .scorer import build_scorer, cap_sweep_values


class CompiledProblem(object):
    def __init__(self, spec, space, cap_values, objectives, models, fidelity,
                 budget, verify_plan, metric_config=None, measurement="idvg"):
        self.spec = spec
        self.problem_id = spec["problem_id"]
        self.device_class = spec["device_class"]
        self.space = space
        self.cap_values = cap_values          # list; [None] for pareto/single
        self._objectives = objectives
        self.models = models
        self.fidelity = fidelity
        self.budget = budget
        self.verify_plan = verify_plan
        self.metric_config = metric_config or {}   # FoM extraction config
        self.measurement = measurement             # idvg | 2vd | idvd -> deck

    def make_scorer(self, cap=None):
        """Build the scorer for a given cap-sweep value (or pareto/single)."""
        return build_scorer(self._objectives, cap=cap)

    @property
    def is_pareto(self):
        return isinstance(self._objectives, dict) and \
            self._objectives.get("mode") == "pareto"

    def __repr__(self):
        mode = "pareto" if self.is_pareto else "capped/single"
        return ("CompiledProblem(%s, class=%s, %s, mode=%s, caps=%s, "
                "budget=%s)" % (self.problem_id, self.device_class, self.space,
                                mode, self.cap_values, self.budget))


def load_spec(spec_path):
    with open(spec_path) as fh:
        return yaml.safe_load(fh)


def compile(spec_path):
    spec = load_spec(spec_path)
    for key in ("problem_id", "device_class", "parameters", "constraints",
                "objectives", "models", "fidelity", "budget"):
        if key not in spec:
            raise ValueError("spec missing required key: %s" % key)

    coupled = (spec["constraints"] or {}).get("coupled", [])
    space = ParamSpace(spec["parameters"], coupled=coupled)

    objectives = spec["objectives"]
    caps = cap_sweep_values(objectives)

    verify_plan = {
        "mesh_refine": spec["fidelity"].get("verify_mesh_refine", 2.0),
        "fidelity": spec["fidelity"].get("verify_fidelity", []),
        "thresholds": spec["fidelity"].get("verify_thresholds",
                                           {"mesh_shift_pct": 10, "btbt_frac_pct": 5}),
    }
    # FoM extraction config (optional): drives the rich metric library
    me = spec.get("metric_extraction", {}) or {}
    metric_config = {
        "vdd": abs(spec.get("operating", {}).get("supplies", {}).get("VDD", 1.0)),
        "vt_icrit": me.get("vt_icrit_A_per_um", 1.0e-7),
        "id_targets": me.get("gm_over_Id_targets_A_per_um", []),
    }
    return CompiledProblem(
        spec=spec, space=space, cap_values=caps, objectives=objectives,
        models=spec["models"], fidelity=spec["fidelity"], budget=spec["budget"],
        verify_plan=verify_plan, metric_config=metric_config,
        measurement=spec.get("measurement", "idvg"))
