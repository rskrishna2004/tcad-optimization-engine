"""l1_spec.guard -- no single curve may be sacrificed to improve a total.

WHY THIS EXISTS, AND WHAT IT COST TO LEARN
------------------------------------------
Every objective in this project is a TOTAL: a weighted mean of each sweep's
root mean square, or a sum of squares over all of them. A total is the right
thing to minimise and the wrong thing to trust on its own, because a total
can fall while one curve inside it is destroyed.

Step 30 measured exactly that. Its PART 3 fitted the charge side with the two
channel totals weighted 8, and reported:

    the two channel gaps added together   0.3486 -> 0.1165   (two thirds shut)
    Cgd at Vd = 0.05 V                    6.330  -> 19.852 per cent rms

The number being chased got much better. One of the eight capacitance curves
got three times worse, with cgdl pinned at the top of its declared range. The
gate that judged the card looked at the drain current, the four figures of
merit and the capacitance TOTAL, and the capacitance total did not fall far
enough to refuse it on its own, so the damage was found afterwards by reading
a table rather than at the moment it happened.

A per curve guard is the cheap fix, and it belongs in the engine rather than
in one step's script, because the same mistake is available to every fit that
has more than one curve in it.

    THE RULE: no curve may end more than `allow` of its OWN error worse than
    it started.

It is a relative rule on purpose. An absolute one would let a curve already
at 20 per cent drift to 21 while refusing a curve at 0.4 per cent going to
0.5, which is backwards: the second is a tenth of the damage. Ten per cent of
a curve's own error is below what is visible on a plot and well above the
give and take of an honest joint fit, and it is stated before the fit runs.

WHAT IT IS NOT
--------------
It is not a replacement for the gate or for the objective. It cannot tell a
good card from a bad one. All it can do is refuse a card that bought its
improvement by wrecking one curve, which is the one thing a total cannot see.
"""
from __future__ import division

import numpy as np

VERSION = "1.1.31"


def curve_pct(curves, targets, name):
    """One named curve's error against the device, as a per cent rms.

    Points where the device value is numerically zero are dropped, scaled
    against that curve's own largest value, so a sweep that passes through
    zero does not produce an infinite relative error.
    """
    g = (curves or {}).get(name)
    t = (targets or {}).get(name)
    if g is None or t is None:
        return None
    mv = np.asarray(g[1], float)
    tv = np.asarray(t["i"], float)
    if mv.shape != tv.shape or tv.size == 0:
        return None
    sc = float(np.max(np.abs(tv)))
    m = np.abs(tv) > max(sc * 1.0e-9, 1.0e-30)
    if m.sum() == 0:
        return None
    return float(np.sqrt(np.mean(((mv[m] - tv[m]) / tv[m] * 100.0) ** 2)))


class CurveGuard(object):
    """Hold a card's per curve errors, and refuse a card that wrecks one.

    `base_curves` is the card the fit STARTS from, which is the only honest
    reference: a guard taken against some earlier card would charge this fit
    for damage another one did, and a guard taken against the device would
    refuse every card that is not already perfect.
    """

    def __init__(self, base_curves, targets, names, labels=None, allow=0.10):
        self.targets = targets or {}
        self.names = list(names)
        self.labels = list(labels) if labels else list(names)
        self.allow = float(allow)
        self.base = dict((n, curve_pct(base_curves, self.targets, n))
                         for n in self.names)

    def present(self, curves):
        return dict((n, curve_pct(curves, self.targets, n))
                    for n in self.names)

    def check(self, curves):
        """The curves that broke the rule, worst first.

        Each entry is (label, before, after, rise) with `rise` a fraction of
        the curve's own starting error. An empty list means the card passed.
        """
        out = []
        now = self.present(curves)
        for nm, lab in zip(self.names, self.labels):
            a, b = self.base.get(nm), now.get(nm)
            if not a or b is None:
                continue
            rise = b / a - 1.0
            if rise > self.allow:
                out.append((lab, float(a), float(b), float(rise)))
        out.sort(key=lambda r: -r[3])
        return out

    def worst(self, curves):
        """The single biggest rise, whether or not it broke the rule."""
        now = self.present(curves)
        best = None
        for nm, lab in zip(self.names, self.labels):
            a, b = self.base.get(nm), now.get(nm)
            if not a or b is None:
                continue
            rise = b / a - 1.0
            if best is None or rise > best[3]:
                best = (lab, float(a), float(b), float(rise))
        return best

    def table(self, curves, title=None, before="before", after="after"):
        now = self.present(curves)
        L = [title or "      every curve, as a per cent rms:",
             "        %-12s %10s %10s %10s" % ("curve", before, after,
                                               "change")]
        for nm, lab in zip(self.names, self.labels):
            a, b = self.base.get(nm), now.get(nm)
            L.append("        %-12s %10s %10s %10s"
                     % (lab,
                        "-" if a is None else "%8.3f" % a,
                        "-" if b is None else "%8.3f" % b,
                        "-" if not (a and b) else "%+7.1f %%"
                        % (100.0 * (b / a - 1.0))))
        return "\n".join(L)

    def why(self, curves):
        """One line naming what the guard refused, or an empty string."""
        bad = self.check(curves)
        if not bad:
            return ""
        return "the guard refused %s" % ", ".join(
            "%s %.3f -> %.3f" % (b[0], b[1], b[2]) for b in bad)
