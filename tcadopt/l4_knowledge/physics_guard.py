# $Id: physics_guard.py, v1.1 2026/07/06 [YOUR NAME] - D-DAY: physics_seeds is now DEVICE-AGNOSTIC via canonical-role alias resolution (EOT<->TOX, NFIN<->NCH, LGATE<->LG, ...), so KB levers seed ANY device family the hackathon drops (FinFET/GAA/nanosheet/planar), not just planar names. v1.0 2026/07/05 [YOUR NAME] - l4_knowledge: the engine's runtime physics layer. Three services: (1) validate(metrics) -> unphysical results are flagged physics_suspect and EXCLUDED from the surrogate (score=None) so the GP never learns from solver artifacts or extractor bugs -- automatic self-correction; (2) physics_seeds() -> KB lever-map pushes from a baseline, so campaigns start where the physics says the objective improves; (3) trend_audit() -> Spearman trend of every metric vs every param in the experiment DB compared against the KB signs; contradictions raise alarms (either the KB or the extraction is wrong -- both must be looked at). KB: knowledge/physics_rules.yaml. $
"""l4_knowledge.physics_guard -- runtime physics knowledge for the engine.

The KB (physics_rules.yaml) is curated from Sze & Ng, Taur & Ning, and the
the device solver User Guide model equations, plus signs confirmed in this
project's own certified campaigns. This module makes that knowledge ACTIVE:

  validate(metrics, T_K)   -> (ok, violations)  [invariant check per trial]
  physics_seeds(...)       -> list of param dicts biased along KB levers
  trend_audit(rows, ...)   -> list of (metric, param, expected, observed, n)

Design rule: knowledge BIASES (seeds) and AUDITS (invariants, trends); it
never hard-constrains the optimizer's search space. The GP remains free to
discover physics the KB does not know.
"""
import copy
import math
import os
import re

try:
    import yaml
    _HAVE_YAML = True
except ImportError:
    _HAVE_YAML = False

_KB_CACHE = None
_DEF_KB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "knowledge", "physics_rules.yaml")

# metric aliases the invariant expressions may reference
_NUM_LITERAL = re.compile(r"\d+\.?\d*(?:[eE][-+]?\d+)?")   # strip 5.0e-3 etc.
_EXPR_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SAFE_FUNCS = {"abs": abs, "min": min, "max": max}


def load_kb(path=None):
    global _KB_CACHE
    if _KB_CACHE is not None and path is None:
        return _KB_CACHE
    p = path or _DEF_KB
    if not (_HAVE_YAML and os.path.exists(p)):
        return {"invariants": [], "levers": {}}
    kb = yaml.safe_load(open(p)) or {}
    kb.setdefault("invariants", [])
    kb.setdefault("levers", {})
    if path is None:
        _KB_CACHE = kb
    return kb


# ---------------------------------------------------------------- validate
def _eval_expr(expr, env):
    """Evaluate one invariant expression against the metric env. Any metric
    referenced but absent -> invariant is SKIPPED (None), never failed:
    invariants only judge what the measurement actually produced."""
    names = set(_EXPR_TOKEN.findall(_NUM_LITERAL.sub(" ", expr)))
    for nm in names:
        if nm in _SAFE_FUNCS or nm in ("and", "or", "not"):
            continue
        if nm not in env or env[nm] is None:
            return None
        try:
            v = float(env[nm])
        except (TypeError, ValueError):
            return None
        if v != v:                      # NaN metric -> cannot judge
            return None
    scope = dict(_SAFE_FUNCS)
    scope.update({k: float(v) for k, v in env.items()
                  if k in names and v is not None})
    try:
        return bool(eval(expr, {"__builtins__": {}}, scope))
    except Exception:
        return None


def validate(metrics, T_K=350.0, kb_path=None):
    """Check a trial's metrics against every applicable invariant.
    Returns (ok, violations). ok is True when NO applicable invariant fails.
    Aliases: Vt_V resolves from Vt_lin/Vt_sat when only those exist."""
    kb = load_kb(kb_path)
    env = dict(metrics or {})
    env["T_K"] = T_K
    if "Vt_V" not in env:
        for alt in ("Vt_sat_V", "Vt_lin_V"):
            if env.get(alt) is not None:
                env["Vt_V"] = env[alt]
                break
    violations = []
    for inv in kb["invariants"]:
        r = _eval_expr(inv.get("expr", ""), env)
        if r is False:
            violations.append("%s: %s" % (inv.get("id", "?"), inv.get("why", "")))
    return (len(violations) == 0), violations



# Canonical KB-role -> the parameter names that play that role across device
# families. physics_seeds pushes the parameter present in the baseline that
# matches a lever's canonical role, so lever knowledge transfers to any device.
_METRIC_KB = {
    "ION": "ION_A_per_um", "IOFF": "IOFF_A_per_um", "SS": "SS_mV_per_dec",
    "DIBL": "DIBL_mV_per_V", "gm": "gm_peak_S_per_um",
    "gm_peak": "gm_peak_S_per_um", "Ron": "Ron_Ohm_um", "Vt": "Vt_V",
    "Idsat": "ION_A_per_um", "gain": "intrinsic_gain",
    "intrinsic_gain": "intrinsic_gain",
}


_ROLE_ALIASES = {
    "LG":    ("LG", "LGATE", "LCH", "LG_NM"),
    "TOX":   ("TOX", "EOT", "TOXP", "TOX_NM", "EOT_NM"),
    "TSI":   ("TSI", "TFIN", "TCH", "WSI", "TBODY", "WFIN"),
    "NCH":   ("NCH", "NFIN", "NBODY", "NCHANNEL", "NCH_CM3"),
    "NSUB":  ("NSUB", "NWELL", "NSUBSTRATE"),
    "NSD":   ("NSD", "NSDE", "NSOURCE", "NSD_CM3"),
    "NLDD":  ("NLDD", "NEXT", "NEXTENSION", "NLDD_CM3"),
    "NHALO": ("NHALO", "NPOCKET", "NHALO_CM3"),
    "XJSD":  ("XJSD", "XJ", "XJUNCTION"),
    "NPOLY": ("NPOLY", "NGATE"),
}


def _resolve_param(lever_key, present):
    """Return the baseline parameter that fills lever_key's physical role, or
    None. Exact name wins; else the first alias present in the design."""
    if lever_key in present:
        return lever_key
    for alt in _ROLE_ALIASES.get(lever_key, ()):
        if alt in present:
            return alt
    return None

# ------------------------------------------------------------ physics seeds
def physics_seeds(objective_metrics, baseline, space, n=8, kb_path=None,
                  strengths=(0.15, 0.3, 0.45, 0.6, 0.75)):
    """Generate up to n seeds by pushing the KB's levers for the objective
    metrics in their favorable directions from `baseline`.
    objective_metrics: [(metric_name, sense)] with sense 'max'|'min'.
    space: ParamSpace (uses .bounds dict {name:(lo,hi,log?)} if present, else
    clips to [baseline/4, baseline*4] for dopings and +/-50% geometry).
    Returns plain param dicts (decoded space)."""
    kb = load_kb(kb_path)
    seeds = []
    for strength in strengths:
        for direction in (1.0,):        # favorable push only
            p = copy.deepcopy(baseline)
            moved = False
            for metric, sense in objective_metrics:
                kb_key = _METRIC_KB.get(metric, metric)
                lev = kb["levers"].get(kb_key) or kb["levers"].get(metric, {})
                want_up = (sense == "max")
                for prm_key, info in lev.items():
                    prm = _resolve_param(prm_key, p)
                    if prm is None:
                        continue
                    sgn = 1.0 if info.get("sign") == "+" else -1.0
                    push = sgn if want_up else -sgn
                    lo, hi = _bounds_for(prm, baseline[prm], space)
                    if _is_log(prm, space):
                        span = math.log10(hi / lo)
                        newv = 10 ** (math.log10(p[prm])
                                      + push * strength * span * 0.5 * direction)
                    else:
                        span = hi - lo
                        newv = p[prm] + push * strength * span * 0.5 * direction
                    p[prm] = min(max(newv, lo), hi)
                    moved = True
            if moved:
                seeds.append(p)
    # dedupe (levers of multiple metrics can collapse to the same point)
    uniq, seen = [], set()
    for p in seeds:
        key = tuple(round(math.log10(v) if v > 0 else v, 4)
                    for v in (p[k] for k in sorted(p)))
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    return uniq[:n]


def _bounds_for(prm, val, space):
    b = getattr(space, "bounds", None)
    if isinstance(b, dict) and prm in b:
        lo, hi = b[prm][0], b[prm][1]
        return float(lo), float(hi)
    if val > 1e10:                       # a doping
        return val / 4.0, val * 4.0
    return val * 0.5, val * 1.5


def _is_log(prm, space):
    b = getattr(space, "bounds", None)
    if isinstance(b, dict) and prm in b and len(b[prm]) > 2:
        return bool(b[prm][2])
    return True if prm.startswith("N") else False


# -------------------------------------------------------------- trend audit
def _spearman(x, y):
    """Spearman rank correlation, numpy-free (pure python, fine for audits)."""
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r
    n = len(x)
    if n < 8:
        return None
    rx, ry = rank(x), rank(y)
    mx = sum(rx) / n
    my = sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    dy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def trend_audit(rows, kb_path=None, min_n=12, strong=0.25):
    """Compare observed metric-vs-param trends in DB rows against KB signs.
    rows: iterables with 'params' and 'metrics' dicts (JSON already decoded).
    Returns alarms: (metric, param, expected_sign, observed_rho, n) where the
    observed correlation is STRONG (|rho|>=strong) and CONTRADICTS the KB.
    A contradiction means: the KB is wrong here, or the extraction/deck is
    broken -- either way a human (or Claude) must look."""
    kb = load_kb(kb_path)
    alarms = []
    for metric, lev in kb["levers"].items():
        pts = [(r["params"], (r.get("metrics") or {}).get(metric))
               for r in rows
               if r.get("params") and (r.get("metrics") or {}).get(metric)
               is not None]
        if len(pts) < min_n:
            continue
        for prm, info in lev.items():
            xs, ys = [], []
            for p, mv in pts:
                if prm in p:
                    x = p[prm]
                    xs.append(math.log10(x) if x > 0 and x > 1e10 else x)
                    ys.append(mv)
            rho = _spearman(xs, ys)
            if rho is None:
                continue
            exp_sgn = 1.0 if info.get("sign") == "+" else -1.0
            if abs(rho) >= strong and (rho * exp_sgn) < 0:
                alarms.append((metric, prm, info.get("sign"),
                               round(rho, 3), len(xs)))
    return alarms
