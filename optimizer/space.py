# $Id: space.py, v2.0 2026/06/12 [YOUR NAME] - WIDENED bounds after 240-eval audit (7 knobs were camping on walls); rule walls (LG,TOX/EOT,XJSD) preserved $
# Python 3.6 + numpy only.
import numpy as np
# COHERENCE CONSTRAINT (Phase 4c): NCH must be >= NSUB. The surface-peak channel
# Gaussian cannot peak below its background or SDE corrupts it (sqrt(2) fallback).
# Enforce with clamp_coherent(params) below before any SDE build.

# (name, low, high, log_scale)
# v2 changes (reason in comment). RULE WALLS unchanged: LG>=0.040,
# TOX>=0.0016 (EOT), XJSD>=0.025 -- these are competition law, not free.
SPACE = [
    ("LG",     0.040,  0.060,  False),   # rule floor kept; champ sat mid-range
    ("TOX",    0.0016, 0.0022, False),   # rule floor kept; widened top a touch
    ("LSP",    0.012,  0.060,  False),   # WAS 0.020 floor -> 0.012 (camped low)
    ("NSD",    5e19,   3e20,   True),    # WAS 2e20 -> 3e20 top (realistic n+)
    ("XJSD",   0.025,  0.055,  False),   # rule floor kept; top 0.050->0.055
    ("LATSD",  0.18,   0.45,   False),   # WAS 0.25 floor -> 0.18 (camped low)
    ("NLDD",   5e18,   1.2e20, True),    # WAS 6e19 -> 1.2e20 top (camped HIGH)
    ("XJLDD",  0.006,  0.025,  False),   # WAS 0.008 floor -> 0.006
    ("LATLDD", 0.25,   0.75,   False),   # slight widen both ends
    ("NHALO",  5e17,   1.2e19, True),    # WAS 8e18 -> 1.2e19 top
    ("DHALO",  0.008,  0.045,  False),   # slight widen both ends
    ("SHALO",  0.005,  0.025,  False),   # WAS 0.008 floor -> 0.005 (camped low)
    ("WHALO",  0.010,  0.050,  False),   # WAS 0.035 -> 0.050 top (camped HIGH)
    ("NCH",    8e16,   2e18,   True),    # WAS 1e17 floor -> 8e16
    ("XCH",    0.015,  0.065,  False),   # slight widen both ends
    ("NSUB",   3e16,   8e17,   True),    # widen both ends
    ("NPOLY",  6e19,   1.0e21, True),    # WAS 1.5e20 -> 1e21 top (CAMPED at ceiling!)
]
FIXED = {"LSD": 0.150, "HPOLY": 0.100, "HSUB": 0.800}

NAMES = [s[0] for s in SPACE]
DIM = len(SPACE)
_LO = np.array([np.log10(s[1]) if s[3] else s[1] for s in SPACE])
_HI = np.array([np.log10(s[2]) if s[3] else s[2] for s in SPACE])
_LOG = np.array([s[3] for s in SPACE])


def decode(u):
    u = np.clip(np.asarray(u, dtype=float), 0.0, 1.0)
    x = _LO + u * (_HI - _LO)
    vals = np.where(_LOG, 10.0 ** x, x)
    p = dict(zip(NAMES, [float(v) for v in vals]))
    p.update(FIXED)
    return p


def encode(params):
    x = np.array([params[n] for n in NAMES], dtype=float)
    x = np.where(_LOG, np.log10(x), x)
    return (x - _LO) / (_HI - _LO)


def lhs(n, seed=0):
    rng = np.random.RandomState(seed)
    u = np.empty((n, DIM))
    for j in range(DIM):
        u[:, j] = (rng.permutation(n) + rng.rand(n)) / n
    return u


def reencode_old_data(rows_params):
    """Map params dicts from the v1-bounds campaign into v2 unit-cube coords,
    so 240 prior evals SEED the v2 GP instead of being thrown away.
    Points outside v2 range get clipped (rare; only if a knob shrank)."""
    return np.array([encode(p) for p in rows_params])


# --- v2.1 coherence guard (Phase 4c): channel implant peak must exceed background,
# else the surface-peak Gaussian goes incoherent and SDE silently uses std=sqrt(2)
# (this corrupted the lp champion). Enforce NCH >= 1.15*NSUB on every decoded vector. ---
_decode_raw = decode
def decode(u):
    d = _decode_raw(u)
    if "NCH" in d and "NSUB" in d and d["NCH"] < 1.15 * d["NSUB"]:
        d["NCH"] = 1.15 * d["NSUB"]
    return d


def clamp_coherent(params):
    """Enforce NCH >= 1.15*NSUB (channel implant peak STRICTLY above background).
    NCH == NSUB is NOT enough: SDE's check is 'peak must be GREATER than the
    value at junction', so equality still trips the std=sqrt(2) fallback. The
    1.15x factor matches the decode() override so the search space and the
    verify path agree. Returns a corrected copy. Phase-4c coherence guard."""
    p = dict(params)
    if "NCH" in p and "NSUB" in p and p["NCH"] < 1.15 * p["NSUB"]:
        p["NCH"] = 1.15 * p["NSUB"]
    return p
