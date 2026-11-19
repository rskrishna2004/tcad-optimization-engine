"""l4_knowledge.overlap -- the gate to drain and gate to source overlap charge,
solved as a CHANGE on top of a measured curve.

WHY THIS IS NOT A COPY OF cgb_overlap
--------------------------------------
`cgb_overlap` rebuilds the whole Cgb curve from scratch out of one expression.
On the real simulator that was wrong by a factor of thirteen, because a second
term it did not model, the accumulation charge on body line 2479, lands on the
same node and switches on when delvfbacc drags the sweep past flatband. The
arithmetic was right about its own term and blind to the other one.

This module does not make that mistake, and it cannot, because it never claims
to know the whole curve. It works on the DIFFERENCE.

    bsimcmg_body.include 2509   T0 = T2 - vfbsdcv_v + `DELTA_1;
    bsimcmg_body.include 2511   vgs_overlap = 0.5*(T0 - sqrt(T0*T0 + 4*`DELTA_1));
    bsimcmg_body.include 2516   qgd_ov = NFINtotal * WeffCV0 * (CGDL_i * (T2
                                  - vfbsdcv_v - vgd_overlap - 0.5*CKAPPAD_i
                                  * (sqrt(1 - 4*vgd_overlap/CKAPPAD_i) - 1))
                                  + CGDO_i * T2);          with T2 = V(ge, di)

Four parameters appear there and NOWHERE ELSE in the charge: cgdl, cgdo,
ckappad and vfbsdcv on the drain side, cgsl, cgso, ckappas and vfbsdcv on the
source side. cgdl is read again on line 838 only to DERIVE cgdo when cgdo is
not given, and our card gives it. So the overlap term is purely additive on
top of everything else the model computes:

    Cgd(Vg) = intrinsic(Vg) + WeffCV0 * (cgdl * g'(Vg) + cgdo)

and `intrinsic` does not contain any of the four. Therefore, given a MEASURED
Cgd curve from one real simulator run,

    Cgd_new(Vg) = Cgd_measured(Vg) - overlap_old(Vg) + overlap_new(Vg)

is EXACT. No term can be missed, because every term that is not in the overlap
is carried over from the measurement untouched. That is the whole idea, and it
is the direct lesson of the run before this one.

WHAT g' LOOKS LIKE, AND WHY vfbsdcv MATTERS
--------------------------------------------
Line 2511 is a smoothed MINIMUM, not a maximum, so the overlap runs the other
way round from the gate to substrate one: g' is near 1 when the gate is above
the drain's flatband voltage and tapers below it. vfbsdcv is where that knee
sits, and ckappad is how sharp it is.

That makes vfbsdcv the only parameter in the model that moves the SHAPE of the
drain overlap without moving its size. A curve that is too high in the middle
of the gate sweep and too low at the top cannot be fixed by scaling cgdl,
which makes the middle worse. It needs the knee moved. vfbsdcv is declared on
bsimcmg_parameters.include 1306 with a default of vfbsd, which is 0.0 on line
1305, and it is read only on body lines 2512 and 2516.

THE RANGE, AND WHERE IT COMES FROM
-----------------------------------
cgdl is a capacitance per unit channel width, multiplied by WeffCV0. The gate
cannot overlap the drain by more oxide than there physically is, so

    cgdl  <=  cox * L_overlap

with L_overlap the spacer plus the lightly doped ungated channel beside it,
both of which the structure script gives. That is a BOUND taken from the
drawing, which is what a drawing is good for. The VALUE still comes from the
measurement.
"""
from __future__ import division

import math

import numpy as np

VERSION = "1.1.33"
EPS0 = 8.8541878128e-12
DELTA_1 = 0.02          # bsimcmg_macros.include 24
CKAPPA_FLOOR = 0.02     # bsimcmg_checking.include 402 and 408


def constants(card):
    """WeffCV0 and cox, the two numbers line 2516 is built on."""
    wgaa = float(card.get("wgaa", 1.0e-8))
    tgaa = float(card.get("tgaa", 5.0e-9))
    ngaa = float(card.get("ngaa", 1.0))
    nfin = float(card.get("nfin", 1.0))
    nf = float(card.get("nf", 1.0))
    weff = 2.0 * (wgaa + tgaa) * ngaa * nfin        # body 285, geomod 5
    cox = float(card.get("epsrox", 3.9)) * EPS0 / float(card.get("eot", 1e-9))
    return {"weff": weff, "weffcv0": weff - float(card.get("deltawcv", 0.0)),
            "cox": cox, "nfintotal": nfin * nf}


def gprime(vg, vd, ckappa=0.02, vfbsdcv=0.0):
    """d/dVg of the bracket on bsimcmg_body.include 2516.

    Near 1 where the gate sits above the drain's flatband, tapering below it
    as 1/sqrt(1 - 4u/ckappa). Line 2511's smoothed minimum is what makes it
    run the opposite way round from the gate to substrate overlap.
    """
    ck = max(float(ckappa), CKAPPA_FLOOR)
    u = np.asarray(vg, float) - float(vd) - float(vfbsdcv)
    t0 = u + DELTA_1
    r = np.sqrt(t0 * t0 + 4.0 * DELTA_1)
    v = 0.5 * (t0 - r)
    dv = 0.5 * (1.0 - t0 / r)
    return 1.0 - dv + dv / np.sqrt(1.0 - 4.0 * v / ck)


def overlap_c(vg, vd, con, cgl, cgo, ckappa=0.02, vfbsdcv=0.0):
    """The overlap's contribution to the capacitance, in farad."""
    return con["nfintotal"] * con["weffcv0"] * (
        float(cgl) * gprime(vg, vd, ckappa, vfbsdcv) + float(cgo))


def ceiling(con, cgl):
    """NFINtotal * WeffCV0 * cgl, the most the bias dependent part can add."""
    return con["nfintotal"] * con["weffcv0"] * float(cgl)


def structure_bound(card, l_overlap):
    """cox * L_overlap: the largest cgdl the device's own geometry allows."""
    return constants(card)["cox"] * float(l_overlap)


def rel_rms(model, dev):
    model = np.asarray(model, float)
    dev = np.asarray(dev, float)
    return 100.0 * float(np.sqrt(np.mean(((model - dev) / dev) ** 2)))


def delta_presolve(sweeps, con, base, cgl_max, n_ck=60, n_vfb=81,
                   ck_range=(CKAPPA_FLOOR, 5.0), vfb_range=(-0.5, 1.0)):
    """Best (cgl, cgo, ckappa, vfbsdcv) for one side, from MEASURED curves.

    `sweeps` is a list of (vg, vd, measured_C, device_C), one per drain bias.
    `base` is (cgl, cgo, ckappa, vfbsdcv) as they were when those curves were
    measured, so the old overlap can be subtracted off exactly.

    For fixed ckappa and vfbsdcv the result is linear in cgl and cgo, so those
    two come out of a least squares. The other two are gridded. A few hundred
    thousand floating point operations, no simulator, and the answer is a
    prediction that can be checked by one run.
    """
    b_cgl, b_cgo, b_ck, b_vfb = base
    k = con["nfintotal"] * con["weffcv0"]
    rows = []
    for vg, vd, meas, dev in sweeps:
        vg = np.asarray(vg, float)
        rows.append((vg, float(vd), np.asarray(meas, float),
                     np.asarray(dev, float),
                     gprime(vg, vd, b_ck, b_vfb)))
    best = None
    cks = np.exp(np.linspace(math.log(max(ck_range[0], CKAPPA_FLOOR)),
                             math.log(ck_range[1]), int(n_ck)))
    vfbs = np.linspace(vfb_range[0], vfb_range[1], int(n_vfb))
    for ck in cks:
        for vfb in vfbs:
            A, y = [], []
            for vg, vd, meas, dev, g_old in rows:
                g_new = gprime(vg, vd, ck, vfb)
                #  stripped = the curve with the OLD overlap removed
                stripped = meas - k * (b_cgl * g_old + b_cgo)
                #  want  stripped + k*(cgl*g_new + cgo)  ==  dev
                A.append(np.vstack([k * g_new / dev,
                                    np.ones_like(g_new) * k / dev]).T)
                y.append((dev - stripped) / dev)
            A = np.vstack(A)
            y = np.concatenate(y)
            sol, _r, _rk, _sv = np.linalg.lstsq(A, y, rcond=None)
            cgl, cgo = float(sol[0]), float(sol[1])
            cgl = min(max(cgl, 0.0), float(cgl_max))
            cgo = max(cgo, 0.0)
            tot, n = 0.0, 0
            per = []
            for vg, vd, meas, dev, g_old in rows:
                m = (meas - k * (b_cgl * g_old + b_cgo)
                     + k * (cgl * gprime(vg, vd, ck, vfb) + cgo))
                e = rel_rms(m, dev)
                per.append((vd, e, m))
                tot += float(np.sum(((m - dev) / dev) ** 2))
                n += len(dev)
            e_all = 100.0 * math.sqrt(tot / n)
            if best is None or e_all < best["rms_pct"]:
                best = {"cgl": cgl, "cgo": cgo, "ckappa": float(ck),
                        "vfbsdcv": float(vfb), "rms_pct": e_all, "per": per,
                        "at_bound": bool(cgl >= float(cgl_max) * 0.999)}
    return best


def format_presolve(best, con, title, names, base, cgl_max, now=None):
    L = [title, ""]
    L.append("      NFINtotal * WeffCV0            %.4e m"
             % (con["nfintotal"] * con["weffcv0"]))
    L.append("      the structure's bound on %-6s %.4e F/m"
             % (names[0], cgl_max))
    L.append("")
    L.append("      %-10s %14s %14s" % ("", "now", "the solve"))
    for nm, b, v in ((names[0], base[0], best["cgl"]),
                     (names[1], base[1], best["cgo"]),
                     (names[2], base[2], best["ckappa"]),
                     ("vfbsdcv", base[3], best["vfbsdcv"])):
        L.append("      %-10s %14.6g %14.6g" % (nm, b, v))
    L.append("")
    for vd, e, _m in best["per"]:
        if now is not None and vd in now:
            L.append("      at Vd = %.2f V   %7.3f -> %7.3f per cent"
                     % (vd, now[vd], e))
        else:
            L.append("      at Vd = %.2f V   %7.3f per cent" % (vd, e))
    L.append("      over both        %7.3f per cent" % best["rms_pct"])
    if best["at_bound"]:
        L.append("")
        L.append("      *** the solve wants %s at the structure's own bound,"
                 % names[0])
        L.append("      *** so the measurement below decides whether that")
        L.append("      *** bound is the real limit or the range is.")
    return "\n".join(L)


def joint_presolve(fams, con, cgl_max, n_ck=26, n_vfb=61,
                   ck_range=(CKAPPA_FLOOR, 5.0), vfb_range=(-0.5, 1.0)):
    """Both sides at once, because vfbsdcv is ONE parameter for both.

    bsimcmg_body.include 2512 and 2516 read the same `vfbsdcv_v`. Solving the
    drain side and the source side separately gives two different answers for
    it, and only one of them can go on the card, so the two have to be solved
    together.

    `fams` is a list of {"name", "sweeps", "base"} with sweeps a list of
    (vg, vd, measured, device) and base (cgl, cgo, ckappa). ckappa is gridded
    per family, vfbsdcv once for all of them, and the cgl and cgo of every
    family come out of ONE least squares over every point of every curve.
    """
    k = con["nfintotal"] * con["weffcv0"]
    cks = np.exp(np.linspace(math.log(max(ck_range[0], CKAPPA_FLOOR)),
                             math.log(ck_range[1]), int(n_ck)))
    vfbs = np.linspace(vfb_range[0], vfb_range[1], int(n_vfb))
    nf = len(fams)
    prep = []
    for f in fams:
        rows = []
        for vg, vd, meas, dev in f["sweeps"]:
            vg = np.asarray(vg, float)
            meas = np.asarray(meas, float)
            dev = np.asarray(dev, float)
            _vfb_old = (f["base"][3] if len(f["base"]) > 3 else 0.0)
            g_old = gprime(vg, vd, f["base"][2], _vfb_old)
            rows.append((vg, float(vd), meas, dev,
                         meas - k * (f["base"][0] * g_old + f["base"][1])))
        prep.append(rows)
    best = None
    grid = [cks] * nf

    def walk(i, chosen):
        if i == nf:
            yield list(chosen)
            return
        for c in grid[i]:
            chosen.append(c)
            for r in walk(i + 1, chosen):
                yield r
            chosen.pop()

    for cklist in walk(0, []):
        for vfb in vfbs:
            A, y = [], []
            for fi, rows in enumerate(prep):
                for vg, vd, meas, dev, strip in rows:
                    g = gprime(vg, vd, cklist[fi], vfb)
                    blk = np.zeros((len(dev), 2 * nf))
                    blk[:, 2 * fi] = k * g / dev
                    blk[:, 2 * fi + 1] = k / dev
                    A.append(blk)
                    y.append((dev - strip) / dev)
            A = np.vstack(A)
            y = np.concatenate(y)
            sol, _r, _rk, _sv = np.linalg.lstsq(A, y, rcond=None)
            vals = []
            for fi in range(nf):
                vals.append((min(max(float(sol[2 * fi]), 0.0), float(cgl_max)),
                             max(float(sol[2 * fi + 1]), 0.0)))
            tot, n, per = 0.0, 0, []
            for fi, rows in enumerate(prep):
                cgl, cgo = vals[fi]
                for vg, vd, meas, dev, strip in rows:
                    m = strip + k * (cgl * gprime(vg, vd, cklist[fi], vfb)
                                     + cgo)
                    per.append((fams[fi]["name"], vd, rel_rms(m, dev), m))
                    tot += float(np.sum(((m - dev) / dev) ** 2))
                    n += len(dev)
            e = 100.0 * math.sqrt(tot / n)
            if best is None or e < best["rms_pct"]:
                best = {"vfbsdcv": float(vfb), "rms_pct": e, "per": per,
                        "fam": [{"name": fams[fi]["name"], "cgl": vals[fi][0],
                                 "cgo": vals[fi][1],
                                 "ckappa": float(cklist[fi])}
                                for fi in range(nf)]}
    return best
