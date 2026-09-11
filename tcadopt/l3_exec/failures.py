"""l3_exec.failures -- failure taxonomy + classifier (failure-intelligence seed).

Turns a run result (+ the the TCAD simulator logs runner.py leaves on disk) into a single
failure class, so L4 can map class -> repair action. Encodes the failure signatures
this project actually hit, especially the silent doping sqrt(2) fallback that makes
a deck "succeed" while simulating the wrong device.

$Id: failures.py, 2026/06/18 [YOUR NAME] $
"""
import os
import re

# ordered: first match wins (most specific / most actionable first)
_PATTERNS = [
    ("doping_incoherent", [
        r"must be greater than the value at junction",
        r"Assigning a default value of sqrt",
    ]),
    ("license_error", [
        r"checkout failed", r"Cannot checkout", r"FLEXlm", r"license server",
        r"Cannot find (?:a )?license",
    ]),
    ("model_error", [
        r"is not a valid", r"[Uu]nknown keyword", r"unknown identifier",
        r"not a known (?:model|keyword|parameter)", r"[Pp]arse error",
        r"syntax error", r"Unexpected token",
    ]),
    ("geometry_error", [
        r"overlap", r"degenerate (?:element|region)", r"self-intersect",
        r"invalid region", r"could not (?:mesh|generate mesh)",
    ]),
    ("convergence_stall", [
        r"convergence has not been achieved", r"not been reached",
        r"minimal step size", r"step size below", r"Newton.*diverg",
        r"no convergence", r"failed to converge",
    ]),
]

ACTION_HINTS = {
    "doping_incoherent": "clamp every analytic Gaussian PeakVal > background, re-render",
    "convergence_stall": "apply numerics ladder R1-R6 (step/iterations/damping/method)",
    "model_error":       "model-registry fix (e.g. NonLocalPath case + built-in defaults)",
    "geometry_error":    "nudge offending geometric param to nearest valid value",
    "license_error":     "back off parallelism / wait / report to human",
    "no_plt":            "inspect tool logs; likely upstream sde/sdevice failure",
    "timeout":           "raise timeout or simplify; check for a hang",
    "partial":           "incomplete IdVg sweep; usable but flag",
    "unknown_fail":      "escalate to LLM diagnosis hook",
}


# Every log filename any producer in this repository actually writes.
# runner.run_one -> tool_structure.log / tool_device.log
# certify._build_and_run -> sde.log / sdev.log
# (legacy names kept so an old run directory still classifies)
_STRUCTURE_LOGS = ("tool_structure.log", "sde.log", "tool_sde.log")
_DEVICE_LOGS = ("tool_device.log", "sdev.log", "tool_sdevice.log",
                "hspice.lis", "tool_spice.log")


def _read(path):
    try:
        with open(path, "r") as fh:
            return fh.read()
    except (IOError, OSError):
        return ""


def _read_any(run_dir, names):
    """Concatenate whichever of `names` exist. A run may leave more than one
    (a retry, or a two-stage flow), and the signature can be in any of them."""
    parts = []
    for n in names:
        t = _read(os.path.join(run_dir, n))
        if t:
            parts.append(t)
    return "\n".join(parts)


def _scan(blob, pats):
    for p in pats:
        if re.search(p, blob, re.I):
            return True
    return False


def classify(result, sde_log=None, sdevice_log=None, run_dir=None):
    """Return (failure_class, detail).

    result: the dict returned by runner.run_one (status/stage/error/metrics).
    sde_log/sdevice_log: log text (optional; for tests). If omitted and run_dir
    is given, the tool logs are read from disk.
    """
    status = result.get("status")
    if status == "ok":
        return ("ok", "")

    err = (result.get("error") or "")
    low = err.lower()
    if "timeout" in low:
        return ("timeout", err)

    if (sde_log is None or sdevice_log is None) and run_dir:
        # BUGFIX (audit D2): runner.run_one writes "tool_structure.log" and
        # "tool_device.log"; certify.py writes "sde.log"/"sdev.log"; this
        # function used to read only "tool_sde.log"/"tool_sdevice.log", which
        # NOTHING writes. Every real failure therefore fell through to
        # unknown_fail and ACTION_HINTS never fired. Read every name any
        # producer in this repository actually emits.
        if sde_log is None:
            sde_log = _read_any(run_dir, _STRUCTURE_LOGS)
        if sdevice_log is None:
            sdevice_log = _read_any(run_dir, _DEVICE_LOGS)

    blob = "\n".join(t for t in (sde_log, sdevice_log) if t)
    for klass, pats in _PATTERNS:
        if _scan(blob, pats):
            return (klass, ACTION_HINTS.get(klass, klass))

    if "no plt" in low:
        return ("no_plt", err)
    if status == "partial":
        return ("partial", "incomplete sweep")
    return ("unknown_fail", err or "unclassified")
