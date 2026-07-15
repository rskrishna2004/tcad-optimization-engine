"""l1_spec.paramspace -- the search space, built from a Problem Spec.

Generalizes the hardcoded space.py: dimensions, bounds, log/lin scaling, and
coupled-constraint clamps all come from the YAML. Encoding convention matches the
existing optimizer: each free parameter maps to [0,1] (log10 for log-scaled), so
gp.py / propose_batch plug in unchanged.

$Id: paramspace.py, 2026/06/18 [YOUR NAME] $
"""
import re
import math
import random


def _f(x):
    return float(x)


class ParamSpace(object):
    def __init__(self, parameters, coupled=None):
        """parameters: ordered dict name -> [lo,hi,scale,unit] OR {fixed: v}.
        coupled: list of strings like 'NCH >= 1.15 * NSUB'."""
        self.free = []          # (name, lo, hi, islog)
        self.fixed = {}         # name -> value
        for name, spec in parameters.items():
            if isinstance(spec, dict) and "fixed" in spec:
                self.fixed[name] = _f(spec["fixed"])
                continue
            lo, hi, scale = _f(spec[0]), _f(spec[1]), str(spec[2])
            if scale == "log" and (lo <= 0 or hi <= 0):
                raise ValueError("log-scaled %s needs positive bounds" % name)
            self.free.append((name, lo, hi, scale == "log"))
        self.names = [f[0] for f in self.free]
        self.dim = len(self.free)
        self._clamps = self._compile_coupled(coupled or [])

    # -- coupled constraints (clamps applied after decode) ----------------
    def _compile_coupled(self, exprs):
        """Support 'A >= [k *] B' and 'A <= [k *] B' as deterministic clamps."""
        clamps = []
        pat = re.compile(
            r"^\s*([A-Za-z_]\w*)\s*(>=|<=)\s*"
            r"(?:([0-9.eE+\-]+)\s*\*\s*)?([A-Za-z_]\w*)\s*$")
        for e in exprs:
            m = pat.match(e)
            if not m:
                # non-clamp coupled constraints (e.g. equality/material) are
                # metadata here; validation lives in l2 validator.
                continue
            a, op, k, b = m.group(1), m.group(2), m.group(3), m.group(4)
            k = float(k) if k else 1.0
            clamps.append((a, op, k, b))
        return clamps

    def apply_clamps(self, params):
        p = dict(params)
        for (a, op, k, b) in self._clamps:
            if a in p and b in p:
                bound = k * p[b]
                if op == ">=" and p[a] < bound:
                    p[a] = bound
                elif op == "<=" and p[a] > bound:
                    p[a] = bound
        return p

    # -- encode / decode ---------------------------------------------------
    def encode(self, params):
        """params dict -> u in [0,1]^dim (free params only, in self.names order)."""
        u = []
        for (name, lo, hi, islog) in self.free:
            v = params[name]
            if islog:
                t = (math.log10(v) - math.log10(lo)) / (math.log10(hi) - math.log10(lo))
            else:
                t = (v - lo) / (hi - lo)
            u.append(min(1.0, max(0.0, t)))
        return u

    def decode(self, u):
        """u in [0,1]^dim -> full params dict (free + fixed), clamps applied."""
        p = {}
        for i, (name, lo, hi, islog) in enumerate(self.free):
            t = min(1.0, max(0.0, u[i]))
            if islog:
                p[name] = 10.0 ** (math.log10(lo) + t * (math.log10(hi) - math.log10(lo)))
            else:
                p[name] = lo + t * (hi - lo)
        p.update(self.fixed)
        return self.apply_clamps(p)

    # -- sampling ----------------------------------------------------------
    def lhs(self, n, seed=0):
        """Latin-hypercube sample -> list of n decoded param dicts."""
        rng = random.Random(seed)
        cols = []
        for _ in range(self.dim):
            strata = [(j + rng.random()) / n for j in range(n)]
            rng.shuffle(strata)
            cols.append(strata)
        out = []
        for i in range(n):
            out.append(self.decode([cols[d][i] for d in range(self.dim)]))
        return out

    def random(self, n, seed=0):
        rng = random.Random(seed)
        return [self.decode([rng.random() for _ in range(self.dim)])
                for _ in range(n)]

    def __repr__(self):
        return "ParamSpace(dim=%d, fixed=%d, clamps=%d)" % (
            self.dim, len(self.fixed), len(self._clamps))
