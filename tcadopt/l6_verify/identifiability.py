"""l6_verify.identifiability -- can this data determine these parameters at all?

THE QUESTION THIS ANSWERS
-------------------------
An extraction produces a number for every parameter. That is not the same as
determining every parameter. If two parameters change the simulated curve in
the same way, then infinitely many pairs of values fit the data equally well,
and the two numbers the optimizer happens to report are one arbitrary choice out
of that infinite set. They will look precise and they will not transfer to a
different geometry, temperature or bias.

This is called a DEGENERACY (or a lack of identifiability), and it is the single
most common way a compact-model extraction is quietly wrong. It cannot be found
by looking at the fit error, because a degenerate fit fits perfectly. It has to
be measured separately, and this module measures it.

HOW
---
Around the extracted point, perturb each free parameter by a small amount and
record how the residual vector changes. That gives a sensitivity column per
parameter, and stacking them gives a Jacobian J.

Three readings come out of J:

  1. SENSITIVITY -- the norm of each column. A near-zero column means the data
     do not respond to that parameter at all: whatever value was reported is
     the optimizer's starting guess, not a measurement.

  2. COLLINEARITY -- the correlation between pairs of columns. A pair at |r|
     close to 1 changes the curve in the same direction: only their combination
     is determined, not the two separately.

  3. CONDITION NUMBER -- the ratio of the largest to smallest singular value of
     the normalized J. It says how many independent directions the data really
     constrains. A large number means the parameter set is bigger than the
     information in the measurement.

WHY IT BELONGS IN l6_verify
---------------------------
l6_verify is the layer that refuses to trust a result until it has been checked
by something other than the score that produced it. Mesh convergence does that
for a TCAD champion. This does it for an extracted parameter set. Same job,
different failure mode.
"""
import numpy as np

# A pair above this is reported as a degeneracy. 0.99 is deliberately strict:
# below it two parameters still share most of their effect but retain a little
# independent signal, which a wider bias range can often separate.
COLLINEAR_WARN = 0.99
COLLINEAR_NOTE = 0.90
# A column whose sensitivity is this small a fraction of the largest is
# effectively not measured at all.
DEAD_FRAC = 1.0e-3


def residual_vector(scorer, model_curves):
    """Flatten a set of curves into one residual vector, using the same
    log/linear split the scorer itself uses, so the Jacobian is the Jacobian
    of the objective that was actually optimized -- not of some other quantity
    that merely resembles it."""
    v = []
    for t in scorer.targets:
        mc = model_curves.get(t["name"])
        if mc is None:
            return None
        from ..l1_spec.curve_scorer import _interp_model
        iq = _interp_model(t["v"], mc[0], mc[1])
        if iq is None:
            return None
        a_ref = np.abs(np.asarray(t["i"], float))
        a_mod = np.abs(iq)
        good = np.isfinite(a_mod) & np.isfinite(a_ref) & (a_ref > scorer.rel_floor)
        a_ref, a_mod = a_ref[good], np.maximum(a_mod[good], 1e-30)
        w = float(t.get("weight", 1.0)) ** 0.5
        if t.get("kind") == "cv":
            v.append(w * (a_mod - a_ref) / a_ref)
        else:
            sub = a_ref < scorer.i_split
            r = np.empty_like(a_ref)
            r[sub] = np.log10(a_mod[sub]) - np.log10(a_ref[sub])
            r[~sub] = (a_mod[~sub] - a_ref[~sub]) / a_ref[~sub]
            v.append(w * r)
    return np.concatenate(v) if v else None


def jacobian(evaluator, scorer, params, names, rel_step=0.02, log_names=()):
    """Central-difference Jacobian of the residual w.r.t. each named parameter.

    Central differences cost 2N simulations instead of N, and they are worth it:
    a one-sided difference on a noisy simulator biases every column in the same
    direction, which shows up as false collinearity -- the exact thing this
    module exists to detect.
    """
    cols, used = [], []
    for n in names:
        p_hi, p_lo = dict(params), dict(params)
        base = float(params[n])
        if n in log_names and base > 0:
            p_hi[n] = base * (1.0 + rel_step)
            p_lo[n] = base / (1.0 + rel_step)
            h = np.log(p_hi[n] / p_lo[n])
        else:
            span = abs(base) if abs(base) > 1e-12 else 1.0
            p_hi[n] = base + rel_step * span
            p_lo[n] = base - rel_step * span
            h = p_hi[n] - p_lo[n]
        r = evaluator.evaluate_batch([p_hi, p_lo], tag="jac_%s" % n)
        if any(x.get("status") != "ok" for x in r):
            continue
        v_hi = residual_vector(scorer, r[0]["curves"])
        v_lo = residual_vector(scorer, r[1]["curves"])
        if v_hi is None or v_lo is None or len(v_hi) != len(v_lo):
            continue
        cols.append((v_hi - v_lo) / h)
        used.append(n)
    if not cols:
        return None, []
    return np.column_stack(cols), used


def analyse(J, names):
    """Turn a Jacobian into the three readings."""
    if J is None or J.size == 0:
        return {"ok": False, "reason": "no usable Jacobian"}
    norms = np.linalg.norm(J, axis=0)
    nmax = float(norms.max()) if norms.size else 0.0
    dead = [names[i] for i, v in enumerate(norms)
            if nmax > 0 and v / nmax < DEAD_FRAC]

    safe = np.where(norms > 0, norms, 1.0)
    Jn = J / safe                                   # unit columns
    C = Jn.T @ Jn
    pairs = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            r = float(C[i, j])
            if abs(r) >= COLLINEAR_NOTE:
                pairs.append((names[i], names[j], r))
    pairs.sort(key=lambda t: -abs(t[2]))

    sv = np.linalg.svd(Jn, compute_uv=False)
    cond = float(sv[0] / sv[-1]) if sv[-1] > 0 else float("inf")
    # effective rank: how many directions carry >0.1% of the leading one
    eff = int(np.sum(sv > sv[0] * 1e-3))
    return {"ok": True, "names": list(names),
            "sensitivity": dict(zip(names, [float(x) for x in norms])),
            "dead": dead, "collinear": pairs,
            "condition_number": cond, "singular_values": [float(x) for x in sv],
            "effective_rank": eff, "n_free": len(names)}


def report(a):
    if not a.get("ok"):
        return "identifiability: %s" % a.get("reason", "unavailable")
    L = ["identifiability of the extracted parameter set",
         "  free parameters : %d" % a["n_free"],
         "  effective rank  : %d   (independent directions the data constrains)"
         % a["effective_rank"],
         "  condition number: %.3g" % a["condition_number"]]
    if a["effective_rank"] < a["n_free"]:
        L.append("  -> %d parameter(s) MORE than the data can determine."
                 % (a["n_free"] - a["effective_rank"]))
    order = sorted(a["sensitivity"], key=lambda k: -a["sensitivity"][k])
    L.append("  sensitivity (largest first):")
    top = a["sensitivity"][order[0]] if order else 1.0
    for n in order:
        v = a["sensitivity"][n]
        L.append("     %-10s %.3e   (%.2e of the strongest)"
                 % (n, v, v / top if top else 0.0))
    if a["dead"]:
        L.append("  NOT MEASURED by this data: %s" % ", ".join(a["dead"]))
        L.append("     their reported values are starting guesses, not results.")
    if a["collinear"]:
        L.append("  degenerate pairs (only their combination is determined):")
        for x, y, r in a["collinear"]:
            tag = "DEGENERATE" if abs(r) >= COLLINEAR_WARN else "strongly coupled"
            L.append("     %-10s ~ %-10s  r = %+.4f   %s" % (x, y, r, tag))
    else:
        L.append("  no pair exceeds |r| = %.2f: the set is separable." % COLLINEAR_NOTE)
    return "\n".join(L)
