"""l1_spec.scorer -- objective construction from the spec's `objectives` block.

Two modes, chosen by the spec:
  * capped-scalar (hackathon style): score = sum_i w_i*log10(metric_i) with a hard
    penalty when a capped metric (e.g. IOFF) exceeds its cap. cap_sweep -> one
    campaign per cap (hp/std/lp).
  * pareto: exposes the objective vector (all sensed to 'maximize') plus a ParEGO
    augmented-Tchebycheff scalarizer, so the existing single-objective optimizer can
    trace a Pareto front by drawing a random weight each round.

Metric-name map matches plt_parser.extract_metrics() output keys.

$Id: scorer.py, 2026/06/18 [YOUR NAME] $
"""
import math
import random

METRIC_KEYS = {
    "ION":              "ION_A_per_um",
    "IOFF":             "IOFF_A_per_um",
    "ION_IOFF_ratio":   "ION_IOFF_ratio",
    "gm_peak":          "gm_peak_S_per_um",
    "Vg_at_gm_peak":    "Vg_at_gm_peak_V",
    "SS_mV_per_dec":    "SS_mV_per_dec",
    "DIBL":             "DIBL_mV_per_V",
    "Vt":               "Vt_V",
    "Vt_lin":           "Vt_lin_V",
    "Vt_sat":           "Vt_sat_V",
    "gm_over_Id_peak":  "gm_over_Id_peak_1_per_V",
    "gm_over_Id_at_10uA": "gm_over_Id_at_1e-05_1_per_V",
    "gm_over_Id_at_1uA": "gm_over_Id_at_1e-06_1_per_V",
    "gm_at_10uA":       "gm_at_1e-05_S_per_um",
    "gm_at_1uA":        "gm_at_1e-06_S_per_um",
    "ft":               "ft_GHz",
    # --- IdVd output-characteristic driver (Tier-1 #2) ---
    "intrinsic_gain":   "intrinsic_gain",
    "intrinsic_gain_dB":"intrinsic_gain_dB",
    "gds":              "gds_S_per_um",
    "Ron":              "Ron_Ohm_um",
    "Early":            "Early_V",
    "Idsat":            "Idsat_A_per_um",
    "gm_op":            "gm_op_S_per_um",
}
_DEFAULT_PENALTY = 4.0
_EPS = 1e-30


def mval(metrics, name):
    """Fetch a metric by friendly name (falls back to raw key)."""
    return metrics.get(METRIC_KEYS.get(name, name))


def _safelog10(x):
    return math.log10(max(float(x), _EPS))


class CappedScalarScorer(object):
    """Scalar objective with maximize terms, target terms, and bound penalties.
      score = sum w_i*log10(metric_i)                              [maximize terms]
            - sum wt*|dev(metric,target)|                          [target terms]
            - penalty*max(0, log10(capped/cap))                    [upper cap]
            - sum penf*max(0, log10(floor/metric))                 [lower floors]
    Target deviation is in log10 domain by default, or linear ('lin') for signed
    metrics like Vt. With only maximize terms + one cap this reproduces the
    hackathon score exactly (backward compatible)."""

    def __init__(self, terms, cap_metric=None, cap=None, penalty=_DEFAULT_PENALTY,
                 floors=None, targets=None):
        self.terms = terms                      # [(metric, signed_weight)]
        self.cap_metric = cap_metric
        self.cap = cap
        self.penalty = penalty
        self.floors = floors or []              # [(metric, floor_value, penalty)]
        self.targets = targets or []            # [(metric, target, weight, domain)]
        self.mode = "capped"

    def __call__(self, metrics):
        if metrics is None:
            return -1e9
        s = 0.0
        for (name, w) in self.terms:
            v = mval(metrics, name)
            if v is None:
                return -1e9
            s += w * _safelog10(v)
        for (name, target, w, domain) in self.targets:
            v = mval(metrics, name)
            if v is None:
                return -1e9
            if domain == "log":
                tgt = math.log10(max(abs(float(target)), _EPS))
                s -= w * abs(_safelog10(v) - tgt)
            else:
                s -= w * abs(float(v) - float(target))
        if self.cap_metric is not None and self.cap is not None:
            iv = mval(metrics, self.cap_metric)
            if iv is None:
                return -1e9
            over = _safelog10(iv) - math.log10(self.cap)
            if over > 0:
                s -= self.penalty * over
        for (name, floor, penf) in self.floors:
            v = mval(metrics, name)
            if v is None:
                return -1e9
            under = math.log10(max(float(floor), _EPS)) - _safelog10(v)
            if under > 0:
                s -= penf * under
        return s

    def feasible(self, metrics):
        if metrics is None:
            return False
        if self.cap_metric is not None and self.cap is not None:
            iv = mval(metrics, self.cap_metric)
            if iv is None or iv > self.cap:
                return False
        for (name, floor, _penf) in self.floors:
            v = mval(metrics, name)
            if v is None or v < floor:
                return False
        return True


class ParetoScorer(object):
    """Multi-objective: objective vector (sensed to maximize) + ParEGO scalarizer."""

    def __init__(self, objectives, report=None, rho=0.05):
        # objectives: list of (metric_name, sense in {'max','min'})
        self.objectives = objectives
        self.report = report or []
        self.rho = rho
        self.mode = "pareto"

    def vector(self, metrics):
        """Return objectives as a maximize-vector in log10 domain (None if missing)."""
        v = []
        for (name, sense) in self.objectives:
            x = mval(metrics, name)
            if x is None:
                return None
            lx = _safelog10(x)
            v.append(lx if sense == "max" else -lx)
        return v

    def parego(self, metrics, weight, ref_lo, ref_hi):
        """Augmented Tchebycheff scalarization (to MAXIMIZE).
        weight: simplex vector; ref_lo/ref_hi: per-objective min/max for scaling."""
        v = self.vector(metrics)
        if v is None:
            return -1e9
        # normalize each objective to ~[0,1] using observed range, then Tchebycheff
        norm = []
        for i, vi in enumerate(v):
            lo, hi = ref_lo[i], ref_hi[i]
            rng = (hi - lo) if (hi - lo) > _EPS else 1.0
            norm.append((vi - lo) / rng)
        wv = [weight[i] * norm[i] for i in range(len(norm))]
        # maximize: Tchebycheff = min_i w_i*norm_i ; augmented with sum term
        return min(wv) + self.rho * sum(wv)

    @staticmethod
    def random_weight(k, seed=0):
        rng = random.Random(seed)
        w = [-math.log(max(rng.random(), _EPS)) for _ in range(k)]
        s = sum(w)
        return [wi / s for wi in w]


def build_scorer(objectives, cap=None):
    """Factory: returns a scorer (and is cap-aware for the capped-scalar family).
    `objectives` is the spec's objectives block; `cap` selects one cap_sweep value."""
    # pareto mode
    if isinstance(objectives, dict) and objectives.get("mode") == "pareto":
        front = [(o["metric"], o.get("sense", "max")) for o in objectives["front"]]
        return ParetoScorer(front, report=objectives.get("report"))
    # capped-scalar mode (list of objective entries)
    terms, cap_metric, cap_val = [], None, cap
    floors, targets = [], []
    for o in objectives:
        name, sense = o["metric"], o.get("sense", "max")
        if "cap" in o or "cap_sweep" in o:
            cap_metric = name
            if cap_val is None:
                cap_val = o.get("cap")  # if no sweep value passed, use literal cap
        elif "floor" in o or "floor_sweep" in o:
            fl = o.get("floor")
            if fl is None and "floor_sweep" in o:
                fl = o["floor_sweep"][0]
            floors.append((name, float(fl), float(o.get("penalty", _DEFAULT_PENALTY))))
        elif sense == "target":
            targets.append((name, float(o["target"]),
                            float(o.get("weight", 1.0)), o.get("domain", "lin")))
        else:
            w = float(o.get("weight", 1.0))
            terms.append((name, w if sense == "max" else -w))
    return CappedScalarScorer(terms, cap_metric=cap_metric, cap=cap_val,
                              floors=floors, targets=targets)


def cap_sweep_values(objectives):
    """Return the list of caps to sweep (one campaign each), or [None]."""
    if isinstance(objectives, dict):
        return [None]
    for o in objectives:
        if "cap_sweep" in o:
            return list(o["cap_sweep"])
        if "cap" in o:
            return [o["cap"]]
    return [None]
