"""l1_spec.paramspace -- the search space, built from a Problem Spec.

Generalizes the hardcoded space.py: dimensions, bounds, log/lin scaling, and
coupled-constraint clamps all come from the YAML. Encoding convention matches the
existing optimizer: each free parameter maps to [0,1] (log10 for log-scaled), so
gp.py / propose_batch plug in unchanged.

WHAT CHANGED IN v1.1.6 -- EXACT PARAMETER TIES
----------------------------------------------
Until now a spec could say three things about a parameter: search it (give a
range), pin it (`{fixed: v}`), or clamp it against another one with an
inequality (`coupled: ["A >= 1.15 * B"]`). There was no way to say the fourth
thing, which several compact models require:

    THIS PARAMETER IS NOT INDEPENDENT. IT IS ALWAYS EQUAL TO THAT ONE.

BSIM-CMG does not merely permit that relation, it DECLARES it. From the
Verilog-A parameter source that ships with the model:

    bsimcmg_parameters.include:1813
        `MPRnb(cfd, cfs, "F/m", "Outer fringe capacitance at drain side")

    bsimcmg_parameters.include:1230
        `MPRnb(pclmcv, pclm, "", "CLM parameter for short-channel CV")

    bsimcmg_parameters.include:1822
        `MPRcz(cgdo, cgso, "F/m", "User-designated non-LDD region drain-gate
                                   overlap capacitance per unit channel width")

    bsimcmg_parameters.include:1834
        `MPRnb(cgdl, cgsl, "F/m", "Overlap capacitance between gate and
                                   lightly-doped drain region")

    bsimcmg_parameters.include:1855
        `MPRnb(ckappad, ckappas, "V", "Coefficient of bias-dependent overlap
                                       capacitance for the drain side")

The DEFAULT VALUE of the second parameter of each pair is the NAME of the
first. The BSIM-CMG 112.1.0 Technical Manual's own parameter table says the
same thing in its Default column -- for CFD it prints, literally, "CFS". So a
card that writes CFS and leaves CFD alone gets a symmetric device, which is
what the model intends for a device with symmetric source and drain.

WHY THIS MATTERED ENOUGH TO CHANGE THE ENGINE. Our card writes both, because
`write_card` writes every key it is given. The moment a stage fits CFS and
leaves CFD at the number that happens to be in the card, the model stops being
symmetric -- silently, with no warning from anywhere, and with the drain-side
fringe capacitance frozen at a default the fit has just moved away from. The
fit then reports a CFS that is only half of the parameter it was really
measuring. Tying is the only correct way to search a pair the model declares
as one number.

A tie is NOT the same as an inequality clamp and is not expressible as one.
`A >= B` and `A <= B` together would pin the pair only if both were evaluated,
in an order that happens to converge; and the follower would still need a range
of its own, which would put a phantom dimension in the search space. A tie adds
no dimension at all: the follower is not searched, it is computed.

    tied:
      cfd: cfs                 # cfd = cfs
      pclmcv: pclm             # pclmcv = pclm
      cgdo: [cgso, 1.0]        # cgdo = 1.0 * cgso
      vsat1: {follows: vsat, k: 1.0}

Refused, loudly, at construction time rather than silently at decode time:
a follower that is also free (it cannot be both searched and computed), a
follower that is also fixed (two values for one name), a leader that does not
exist in the space at all (the tie would have nothing to follow), a chain
(A follows B follows C -- legal to want, but the ORDER of evaluation would then
decide the answer, so it is refused until someone needs it and can say what the
order should be), and a follower that also appears in a coupled clamp (the
clamp runs first, so the tie would silently overwrite it).

$Id: paramspace.py, 2026/09/17 [YOUR NAME] $
"""
import re
import math
import random


def _f(x):
    return float(x)


def _parse_tie(name, spec):
    """One entry of the `tied` map -> (follower, leader, k).

    Accepts 'cfs', ['cfs'], ['cfs', 1.0], ('cfs', 1.0),
    {'follows': 'cfs'} and {'follows': 'cfs', 'k': 1.0}.
    """
    k = 1.0
    if isinstance(spec, dict):
        leader = spec.get("follows", spec.get("leader"))
        if leader is None:
            raise ValueError(
                "tied: %s -- a dict form needs a 'follows' key naming the "
                "parameter this one follows" % name)
        if "k" in spec:
            k = _f(spec["k"])
    elif isinstance(spec, (list, tuple)):
        if not spec:
            raise ValueError("tied: %s -- empty list" % name)
        leader = spec[0]
        if len(spec) > 1:
            k = _f(spec[1])
        if len(spec) > 2:
            raise ValueError(
                "tied: %s -- a list form is [leader] or [leader, k], got %d "
                "entries" % (name, len(spec)))
    else:
        leader = spec
    leader = str(leader)
    if not re.match(r"^[A-Za-z_]\w*$", leader):
        raise ValueError("tied: %s -- '%s' is not a parameter name"
                         % (name, leader))
    if leader == name:
        raise ValueError("tied: %s cannot follow itself" % name)
    if not (k == k) or k in (float("inf"), float("-inf")):
        raise ValueError("tied: %s -- the factor must be a finite number, "
                         "got %r" % (name, k))
    return (str(name), leader, k)


class ParamSpace(object):
    def __init__(self, parameters, coupled=None, tied=None):
        """parameters: ordered dict name -> [lo,hi,scale,unit] OR {fixed: v}.
        coupled: list of strings like 'NCH >= 1.15 * NSUB'.
        tied:    dict follower -> leader (see the module docstring). A tied
                 parameter is not searched and adds no dimension; it is set to
                 k * leader every time a point is decoded."""
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
        self._ties = self._compile_tied(tied or {})
        self.tied_names = [t[0] for t in self._ties]

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

    # -- exact ties (v1.1.6) ----------------------------------------------
    def _compile_tied(self, tied):
        """Validate the `tied` map and return [(follower, leader, k), ...].

        Everything that could make a tie ambiguous is an error here, at
        construction, where the message can name the spec key that is wrong.
        A tie that fails quietly at decode time would produce a fitted number
        that looks perfectly reasonable and is wrong, which is the whole class
        of bug this mechanism exists to remove.
        """
        ties = []
        free_set = set(self.names)
        clamped = set()
        for (a, _op, _k, b) in self._clamps:
            clamped.add(a)
            clamped.add(b)
        parsed = [_parse_tie(name, spec) for name, spec in sorted(tied.items())]
        followers = set(t[0] for t in parsed)
        for (f, leader, k) in parsed:
            # Chains first: for A -> B -> C the leader-exists test below would
            # also fire (a follower is never free or fixed, so B is in neither
            # set), but it would say "B does not exist", which is true and
            # unhelpful. Checked here so the message names the real problem.
            if leader in followers:
                raise ValueError(
                    "tied: %s follows %s, which is itself tied. Chained ties "
                    "are refused because the order they are applied in would "
                    "decide the answer." % (f, leader))
            if f in free_set:
                raise ValueError(
                    "tied: %s is also given a search range. A parameter is "
                    "either searched or tied, never both -- if it is tied it "
                    "has no dimension of its own to search." % f)
            if f in self.fixed:
                raise ValueError(
                    "tied: %s is also {fixed: %g}. That is two values for one "
                    "name." % (f, self.fixed[f]))
            if leader not in free_set and leader not in self.fixed:
                raise ValueError(
                    "tied: %s follows %s, but %s is neither free nor fixed in "
                    "this stage, so there is nothing to follow. Give %s a "
                    "range or a {fixed: ...} value."
                    % (f, leader, leader, leader))
            if f in clamped:
                raise ValueError(
                    "tied: %s also appears in a coupled constraint. Clamps "
                    "are applied before ties, so the tie would silently "
                    "overwrite the clamp. Pick one." % f)
            ties.append((f, leader, k))
        return ties

    def apply_ties(self, params):
        """follower = k * leader, for every declared tie. Exact, not a clamp."""
        if not self._ties:
            return params
        p = dict(params)
        for (a, b, k) in self._ties:
            if b in p:
                p[a] = k * p[b]
        return p

    def describe_ties(self):
        """One human-readable line per tie, for a run log."""
        return ["%s = %s%s" % (a, ("%g * " % k) if k != 1.0 else "", b)
                for (a, b, k) in self._ties]

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
        """u in [0,1]^dim -> full params dict (free + fixed + tied), clamps
        applied. Order: free, then fixed, then clamps, then ties -- so a tie is
        exact in the dict that finally reaches the card, which is the only
        place it matters."""
        p = {}
        for i, (name, lo, hi, islog) in enumerate(self.free):
            t = min(1.0, max(0.0, u[i]))
            if islog:
                p[name] = 10.0 ** (math.log10(lo) + t * (math.log10(hi) - math.log10(lo)))
            else:
                p[name] = lo + t * (hi - lo)
        p.update(self.fixed)
        return self.apply_ties(self.apply_clamps(p))

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
        return "ParamSpace(dim=%d, fixed=%d, clamps=%d, ties=%d)" % (
            self.dim, len(self.fixed), len(self._clamps), len(self._ties))
