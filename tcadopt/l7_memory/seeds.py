"""l7_memory.seeds -- warm-start / transfer.

Two sources of known-good starting points for a new campaign:
  * load_seeds(paths)        -- champion param vectors from JSON files
  * seeds_from_db(db, ...)   -- best param vectors from past experiments (true
                                transfer: a new campaign warm-starts from history)

Seeding the initial design with these gives the optimizer a head start and
guarantees a warm-started campaign cannot do worse than the seeds it was given.

$Id: seeds.py, 2026/06/18 [YOUR NAME] $
"""
import json


def _as_params(obj):
    """Accept {'params': {...}}, {'metrics':..,'params':..}, or a bare params dict."""
    if isinstance(obj, dict) and "params" in obj and isinstance(obj["params"], dict):
        return obj["params"]
    return obj


def load_seeds(paths):
    """Load champion parameter dicts from a list of JSON file paths.
    Silently skips files that don't parse to a params dict."""
    seeds = []
    for p in paths:
        try:
            with open(p) as fh:
                d = json.load(fh)
            params = _as_params(d)
            if isinstance(params, dict):
                seeds.append(params)
        except (IOError, OSError, ValueError):
            continue
    return seeds


def seeds_from_db(db, problem_id, n=5, by="score"):
    """Warm-start a new campaign from the best n trials of past experiments on
    the same problem_id (true transfer). Returns a list of param dicts."""
    rows = db.best(problem_id, n=n, by=by)
    return [r["params"] for r in rows if r.get("params")]


def valid_seeds(space, seeds, verbose=True):
    """Keep only seeds that carry every free parameter of `space` (so they can be
    encoded). Applies coherence clamps. WARNS on any param outside the spec bounds
    -- encode() silently saturates those to the boundary, corrupting the seed, so
    an out-of-bounds seed means the search space does not contain it (widen the
    spec). Returns the cleaned list."""
    ok = []
    need = set(space.names)
    bnds = {n: (lo, hi) for (n, lo, hi, _islog) in space.free}
    for i, s in enumerate(seeds):
        if not need.issubset(set(s.keys())):
            if verbose:
                missing = need - set(s.keys())
                print("[seeds] skipping seed %d missing %d keys: %s"
                      % (i, len(missing), sorted(missing)[:4]))
            continue
        oob = [(n, s[n], lo, hi) for n, (lo, hi) in bnds.items()
               if s[n] < lo or s[n] > hi]
        if oob and verbose:
            for n, v, lo, hi in oob:
                print("[seeds] WARNING seed %d: %s=%.4g is OUTSIDE [%.4g, %.4g] -> "
                      "encode will clamp it (the space does not contain this seed; "
                      "widen the spec)." % (i, n, v, lo, hi))
        ok.append(space.apply_clamps(s))
    return ok
