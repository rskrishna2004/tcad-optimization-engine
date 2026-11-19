"""l4_knowledge.cgb_overlap -- solve the gate to substrate charge BEFORE
simulating it.

WHY THIS EXISTS, AND WHAT IT COST TO LEARN
-------------------------------------------
BSIM-CMG's gate to substrate charge, with bulkmod other than zero, is seven
lines of bsimcmg_body.include:

    3067   Qeg = cgbox * devsign * V(e, ge);
    3069   if (bulkmod != 0) begin
    3070       T2 = devsign * V(ge, e);
    3071       T3 = T2 - deltaPhi + Eg / 2.0 + phib - delvfbacc;
    3072       T0 = T3 + `DELTA_1;
    3073       vge_overlap = 0.5 * (T0 + sqrt(T0 * T0 + 4.0 * `DELTA_1));
    3074       Qeg = Qeg - NFINtotal * LeffCV * (CGBL_i * (T3 - vge_overlap
                      + 0.5 * CKAPPAB_i * (sqrt(1.0 + 4.0 * vge_overlap
                      / CKAPPAB_i) - 1.0)));
    3075   end

Read it and three facts fall out, none of which needs a simulator.

ONE. The capacitance this produces is

    Cgb(Vg) = cgbox + NFINtotal * LeffCV * cgbl * f'(T3)

with f' between 1 (accumulation, the whole overlap oxide) and 0 (inversion,
the substrate screened). So the whole curve is a CONSTANT plus a KNOWN SHAPE
times cgbl, and for a fixed ckappab and delvfbacc it is LINEAR in the two
numbers cgbox and cgbl. A linear least squares solves it exactly, in a
millisecond, with no HSPICE at all.

TWO. `NFINtotal * LeffCV * cgbl` is the CEILING of the bias dependent part.
On a device with LeffCV = 10.845 nm, cgbl = 2.8e-10 F/m puts that ceiling at
3.037 aF. If the measured Cgb of the whole device never leaves 1.41 to 1.93
aF, that value is not a starting point, it is twice the answer.

THREE. Nothing in those seven lines reads vds. The model's Cgb is the SAME
curve at every drain bias, so one curve has to serve both sweeps, and the
best it can do is bounded by how much the two measured sweeps differ from
each other.

WHAT WENT WRONG WITHOUT THIS MODULE
------------------------------------
A step seeded cgbl at 2.8e-10 F/m, which is the plate capacitance of the
3 nm bottom dielectric isolation plug under the gate worked out from the
structure, divided by the channel length. The physical plug really is about
3.0 aF. But the plug is in series with the substrate depletion and is
screened by the sheets, so its plate value is an UPPER BOUND on the path,
not the value of the path, and the measured Cgb is half of it.

The seeded card put the model's Cgb at 3.72 aF falling to 2.84, against a
device at 1.93 falling to 1.41. Its SPREAD across the sweep was 23.5 per
cent against the device's 27.1, which looked right and was the trap: the
shape was nearly correct while the level was double. The capacitance error
went from 0.0405 to about 0.19, a safety check refused the card, and the
run stopped at its first minute.

This module would have caught it in a millisecond. `presolve` on the same
device data returns cgbl near 9.0e-11, cgbo near 7.8e-11 and a residual
near 1.4 per cent, and `ceiling` prints the 3.037 aF for the seed next to
the device's own 1.93 aF maximum.

THE RULE IT ENCODES
--------------------
A dimension taken off a structure drawing gives you an upper bound and a
sanity check. The model equation decides the shape. The measurement decides
the value. Never let the first one be the third one.
"""
from __future__ import division

import math

import numpy as np

VERSION = "1.1.33"

EPS0 = 8.8541878128e-12
Q = 1.602176634e-19
KB = 1.380649e-23
DELTA_1 = 0.02          # bsimcmg_macros.include 24
CKAPPAB_FLOOR = 0.02    # bsimcmg_checking.include 414, clamped below this
EASUB = 4.05            # bsimcmg_parameters.include 128
BG0SUB = 1.12           # bsimcmg_parameters.include 130
TBGASUB = 7.02e-4       # bsimcmg_parameters.include 2032
TBGBSUB = 1.108e3       # bsimcmg_parameters.include 2033
NI0SUB = 1.1e16         # bsimcmg_parameters.include, ni0sub default


def constants(card):
    """Everything body lines 157 to 1612 compute before the charge is built.

    Returns a dict. Every entry carries the line it comes from in its key's
    comment below, and every default used is the model's own.
    """
    tnom_c = float(card.get("tnom", 26.85))
    t_k = tnom_c + 273.15
    vtm = KB * t_k / Q                                    # thermal voltage
    eg = BG0SUB - TBGASUB * t_k * t_k / (t_k + TBGBSUB)   # body 1139
    ni = (NI0SUB * (t_k / 300.15) ** 1.5
          * math.exp(BG0SUB / (2.0 * (KB * 300.15 / Q)) - eg / (2.0 * vtm)))
    nbody = float(card.get("nbody", 1.0e22))
    phib = vtm * math.log(nbody / ni)                     # body 1602
    phig = float(card.get("phig", 4.61))
    delta_phi = phig - EASUB                              # body 1612, ntype
    lg = float(card.get("l", 1.2e-8))                     # body 157, xl = 0
    dlc = float(card.get("dlc", 0.0))
    leffcv = lg - 2.0 * dlc                               # body 165, 168
    nfin = float(card.get("nfin", 1.0))
    nf = float(card.get("nf", 1.0))
    nfintotal = nfin * nf
    return {"t_k": t_k, "vtm": vtm, "eg": eg, "ni": ni, "phib": phib,
            "delta_phi": delta_phi, "lg": lg, "leffcv": leffcv,
            "nfintotal": nfintotal, "k": nfintotal * leffcv}


def t3(vg, con, delvfbacc=0.0):
    """bsimcmg_body.include 3071, with V(ge, e) = Vg and the substrate at 0."""
    return (np.asarray(vg, float) - con["delta_phi"] + con["eg"] / 2.0
            + con["phib"] - float(delvfbacc))


def fprime(vg, con, ckappab=0.6, delvfbacc=0.0):
    """d/dVg of the bracket on body line 3074.

    The bracket is   T3 - vge_overlap + 0.5*ck*(sqrt(1 + 4*vge_overlap/ck) - 1)
    with vge_overlap the smoothed positive part from line 3073. Its slope is
    1 where T3 is well below zero, which is the full overlap oxide, and falls
    as 1/sqrt(1 + 4*T3/ck) above it, which is the substrate depleting.
    """
    ck = max(float(ckappab), CKAPPAB_FLOOR)
    x = t3(vg, con, delvfbacc)
    t0 = x + DELTA_1
    r = np.sqrt(t0 * t0 + 4.0 * DELTA_1)
    s = 0.5 * (t0 + r)
    ds = 0.5 * (1.0 + t0 / r)
    return 1.0 - ds + ds / np.sqrt(1.0 + 4.0 * s / ck)


def model_cgb(vg, con, cgbox, cgbl, ckappab=0.6, delvfbacc=0.0):
    """The capacitance body lines 3067 and 3074 produce, in farads."""
    return float(cgbox) + con["k"] * float(cgbl) * fprime(
        vg, con, ckappab, delvfbacc)


def ceiling(card, cgbl):
    """NFINtotal * LeffCV * cgbl, the largest the bias dependent part can be.

    This is the one number that makes a wrong seed obvious. Compare it with
    the device's own largest measured Cgb before using the value.
    """
    return constants(card)["k"] * float(cgbl)


def rel_rms(model, dev):
    model = np.asarray(model, float)
    dev = np.asarray(dev, float)
    return 100.0 * float(np.sqrt(np.mean(((model - dev) / dev) ** 2)))


def _linear(vg, dev, con, ckappab, delvfbacc, cgbo_floor=0.0):
    """Least squares on (cgbox, cgbl) with ckappab and delvfbacc fixed.

    Relative error is what the project scores on, so each row is divided by
    the device value before the solve. cgbo is declared MPRcz, clipped at
    zero (bsimcmg_parameters.include 1823), and cgbl is clamped at zero by
    bsimcmg_checking.include 398, so a solution with either negative is
    re-solved with that one pinned rather than returned as a number the
    model would refuse.
    """
    d = fprime(vg, con, ckappab, delvfbacc)
    dev = np.asarray(dev, float)
    a = np.vstack([np.ones_like(d) / dev, con["k"] * d / dev]).T
    sol, _r, _rk, _sv = np.linalg.lstsq(a, np.ones_like(dev), rcond=None)
    cgbox, cgbl = float(sol[0]), float(sol[1])
    if cgbox < cgbo_floor or cgbl < 0.0:
        if cgbl < 0.0:
            cgbl = 0.0
            cgbox = float(np.sum(1.0 / dev) / np.sum(1.0 / (dev * dev)))
        else:
            cgbox = float(cgbo_floor)
            a2 = (con["k"] * d / dev).reshape(-1, 1)
            s2, _r, _rk, _sv = np.linalg.lstsq(
                a2, np.ones_like(dev) - cgbox / dev, rcond=None)
            cgbl = max(0.0, float(s2[0]))
    m = cgbox + con["k"] * cgbl * d
    return cgbox, cgbl, rel_rms(m, dev), m


def presolve(vg, dev_cgb, card, n_ck=160, n_dv=161,
             ck_range=(CKAPPAB_FLOOR, 20.0), dv_range=(-2.0, 2.0)):
    """The best (cgbo, cgbl, ckappab, delvfbacc) for a measured Cgb curve.

    `vg` and `dev_cgb` may be one sweep or several concatenated, because the
    model's Cgb does not depend on vds and one curve has to serve them all.

    The search is a grid on the two parameters the expression is NOT linear
    in, with an exact least squares on the two it IS linear in at every grid
    point. That is a few hundred thousand floating point operations and no
    simulator call at all, and it returns a starting point that is already
    within a per cent of the best the model can do, instead of a guess.
    """
    con = constants(card)
    vg = np.asarray(vg, float)
    dev = np.asarray(dev_cgb, float)
    best = None
    cks = np.exp(np.linspace(math.log(max(ck_range[0], CKAPPAB_FLOOR)),
                             math.log(ck_range[1]), int(n_ck)))
    dvs = np.linspace(dv_range[0], dv_range[1], int(n_dv))
    for ck in cks:
        for dv in dvs:
            cgbox, cgbl, e, m = _linear(vg, dev, con, ck, dv)
            if best is None or e < best["rms_pct"]:
                best = {"cgbox_F": cgbox, "cgbo": cgbox / con["lg"],
                        "cgbl": cgbl, "ckappab": float(ck),
                        "delvfbacc": float(dv), "rms_pct": e,
                        "model": m, "con": con}
    return best


def format_presolve(best, card, dev_cgb, seed_cgbl=None, splits=None):
    """The pre-solve as a block of text with every number in it checkable."""
    con = best["con"]
    dev = np.asarray(dev_cgb, float)
    L = []
    L.append("    the model's own arithmetic, body lines 3067 to 3075:")
    L.append("")
    L.append("      Cgb(Vg) = cgbox + NFINtotal * LeffCV * cgbl * f'(T3)")
    L.append("")
    L.append("      LeffCV   = l - 2*dlc            %.4f nm"
             % (con["leffcv"] * 1e9))
    L.append("      NFINtotal * LeffCV              %.4e m" % con["k"])
    L.append("      phib     = Vtm*ln(nbody/ni)     %.6f V" % con["phib"])
    L.append("      deltaPhi = phig - easub         %.6f V" % con["delta_phi"])
    L.append("      Eg/2                            %.6f V" % (con["eg"] / 2.0))
    L.append("      so T3 = Vg %+.6f V, which is above zero over the"
             % (-con["delta_phi"] + con["eg"] / 2.0 + con["phib"]))
    L.append("      whole gate sweep, so f' never reaches 1.")
    L.append("")
    L.append("      the device's Cgb runs %.4f aF down to %.4f aF"
             % (dev.max() * 1e18, dev.min() * 1e18))
    if seed_cgbl is not None:
        cap = con["k"] * float(seed_cgbl)
        L.append("      a cgbl of %.4e puts the bias dependent part's"
                 % float(seed_cgbl))
        L.append("      CEILING at %.4f aF on its own, which is %.2f times"
                 % (cap * 1e18, cap / dev.max()))
        L.append("      the device's whole Cgb at its largest.")
    L.append("")
    L.append("    the best this expression can do on that curve, solved in")
    L.append("    closed form with no simulator:")
    L.append("")
    L.append("      ckappab    %.4f V%s"
             % (best["ckappab"],
                "   (at the model's own floor, checking line 414)"
                if best["ckappab"] <= CKAPPAB_FLOOR * 1.001 else ""))
    L.append("      delvfbacc  %+.4f V" % best["delvfbacc"])
    L.append("      cgbo       %.6e F/m   (cgbox = %.4f aF)"
             % (best["cgbo"], best["cgbox_F"] * 1e18))
    L.append("      cgbl       %.6e F/m" % best["cgbl"])
    L.append("      model Cgb  %.4f aF down to %.4f aF"
             % (best["model"].max() * 1e18, best["model"].min() * 1e18))
    L.append("      residual   %.3f per cent rms" % best["rms_pct"])
    if splits:
        for lab, sl in splits:
            L.append("        %-10s %.3f per cent"
                     % (lab, rel_rms(best["model"][sl], dev[sl])))
    return "\n".join(L)


def accumulation_risk(vg, card, delvfbacc, dwcacc=0.0, dlcacc=0.0,
                      eotacc=None):
    """Does this delvfbacc drag the sweep into the branch this module omits?

    v1.1.33. WHAT THIS EXISTS TO CATCH
    -----------------------------------
    `presolve` above models ONE term, the gate to substrate overlap on body
    line 3074. It was run on a real device, it returned delvfbacc = +1.0 and
    promised 1.39 per cent, and the simulator measured 1262 per cent on that
    card. The arithmetic was not wrong about its own term. It was blind to a
    second one.

        bsimcmg_body.include 2479   T1 = NFINtotal * WeffCV_acc
                                         * LeffCV_acc * cox_acc;
        bsimcmg_body.include 2485   qb_acc = T10;

    That is the channel's ACCUMULATION charge, and line 2485 puts it on the
    body node, which is to say inside Cgb. At the model's own defaults it is
    worth about 61 aF on this device, against a measured Cgb of under 2 aF.
    It is dormant while the channel is inverted and it switches on as the
    sweep crosses flatband, and delvfbacc is exactly the parameter that moves
    where flatband sits.

    So a delvfbacc large enough to push T3 below zero does not merely change
    the overlap. It opens a term forty times bigger than the thing being
    fitted. This function says when that is about to happen, and what the
    term is worth, so the caller can either keep delvfbacc small or put the
    accumulation parameters in the fit alongside it. The fit that followed
    did the second thing: it shrank WeffCV_acc with dwcacc and cox_acc with
    qmtcencva until the term was small, and then the overlap fit worked.
    """
    con = constants(card)
    x = t3(vg, con, delvfbacc)
    frac = float(np.mean(np.asarray(x, float) < 0.0))
    wgaa = float(card.get("wgaa", 1.0e-8))
    tgaa = float(card.get("tgaa", 5.0e-9))
    ngaa = float(card.get("ngaa", 1.0))
    weff = 2.0 * (wgaa + tgaa) * ngaa * con["nfintotal"]
    weff_acc = weff - 2.0 * ngaa * float(dwcacc)
    leff_acc = con["leffcv"] - float(dlcacc)
    eot = float(card.get("eot", 1.0e-9))
    cox = float(card.get("epsrox", 3.9)) * EPS0 / eot
    cox_acc = cox * eot / float(eotacc if eotacc else eot)
    worth = con["nfintotal"] * max(weff_acc, 0.0) * max(leff_acc, 0.0) * cox_acc
    return {"frac_accumulated": frac, "t3_min": float(np.min(x)),
            "t3_max": float(np.max(x)), "acc_ceiling_F": worth,
            "risky": bool(frac > 0.05)}


def format_risk(risk, dev_max_F):
    L = ["      the accumulation branch, body line 2479, which the solve",
         "      above does NOT model:"]
    L.append("        T3 runs %+.4f to %+.4f V, so %.0f per cent of the sweep"
             % (risk["t3_min"], risk["t3_max"],
                100.0 * risk["frac_accumulated"]))
    L.append("        is below flatband, where that branch is live.")
    L.append("        it is worth up to %.2f aF and it lands on the BODY"
             % (risk["acc_ceiling_F"] * 1e18))
    L.append("        node, body line 2485, against a measured Cgb of %.2f aF."
             % (dev_max_F * 1e18))
    if risk["risky"]:
        L.append("        *** THE SOLVE ABOVE CANNOT BE TRUSTED ON ITS OWN.")
        L.append("        *** Either hold delvfbacc where the sweep stays")
        L.append("        *** inverted, or put dwcacc, dlcacc, eotacc and")
        L.append("        *** qmtcencva in the fit so the branch can be")
        L.append("        *** shrunk. The ladder below measures which.")
    else:
        L.append("        the sweep stays inverted, so the branch is dormant")
        L.append("        and the solve above stands on its own.")
    return "\n".join(L)
