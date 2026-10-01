"""l4_knowledge.cv_scope -- which parameters CANNOT move the drain current.

WHY THIS MODULE EXISTS
----------------------
Nineteen steps of this project have fought the same fight: a stage improves
the capacitance, the no-regression gate measures the drain current, the
current has moved, and the whole stage is thrown away. Step 20 lost its best
result exactly that way -- a fit that took the sixteen-curve residual from
6.996 to 0.050 was rejected because the ten current sweeps got 51% worse.

But that fight is not always necessary. BSIM-CMG has a set of parameters
that are MATHEMATICALLY INCAPABLE of changing the drain current, because
every line of the model that reads them is inside the charge calculation.
Those parameters can be fitted as hard as you like, to convergence, with no
gate and no risk -- and the current is bit-identical afterwards.

This module is the list, and every entry carries the line of
`bsimcmg_body.include` (BSIM-CMG 112.1.0, released 04/28/2026) that proves
it. It is a CITATION, not an opinion. And because a citation can still be
misread, `verify_scope` MEASURES the claim on the real simulator before any
stage relies on it: each parameter is pushed hard and every current sweep is
compared with the baseline. A parameter that moves a current is ejected from
the free zone and sent back to the gated set, and the run says so.

THE TWO THAT LOOK FREE AND ARE NOT
----------------------------------
KSATIV and MEXP have no `CV` in their names and every instinct says they are
current parameters. They are -- and the charge uses them too:

    line 1901   T6 = KSATIV_a * (qis + 2.0 * Vtm)          <- the I-V Vdsat
    line 2089   T6 = KSATIV_a * (qis_cv + 2.0 * Vtm)       <- the C-V Vdsat
    line 1916   T7 = pow((vds / Vdsat)    + 1e-6, MEXP_a)  <- the I-V Vdseff
    line 2103   T7 = pow((vds / Vdsat_cv) + 1e-6, MEXP_a)  <- the C-V Vdseff

They are the bridge between the two halves of the model, and on this device
they are also the two knobs the capacitance most wants to move. So they are
listed here explicitly as SHARED, so that no future step can mistake them
for free.

QMFACTORCV is the other trap. Its name says C-V, and it is not free: it
enters the surface-potential solve itself (lines 1818, 1835-1845, 1926,
1943), which both the current and the charge are built on. Step 14 measured
it moving the drain current by 0.66 and that measurement is now explained.

WHAT `CVMOD` ACTUALLY DOES, SETTLED
-----------------------------------
The whole `_cv` branch -- lines 1981 to about 2270 of `bsimcmg_body.include`
-- is inside `if (cvmod == 1)`. At CVMOD = 0 the charge is built from the
I-V's own `qia` and `dqi`:

    2449  if (cvmod == 1) begin
    2450      T11 = (2.0 * qia_cv + nVtm) / DvsatCV;
    2451      qg_v = qia_cv + dqi_cv * dqi_cv / (6.0 * T11);
    2452      qd_v = -0.5 * (qia_cv - (dqi_cv / 6.0) * (...));
    2453  end else begin
    2454      T11 = (2.0 * qia + nVtm) / DvsatCV;
    2455      qg_v = qia + dqi * dqi / (6.0 * T11);
    2456      qd_v = -0.5 * (qia - (dqi / 6.0) * (...));
    2457  end

So at CVMOD = 0, VSATCV / U0CV / UACV / UCCV / UDCV / ETA0CV reach nothing at
all: the quantities they feed (`Vdsat_cv`, `Vdseff_cv`, `qis_cv`, `qid_cv`)
are never computed. The parameter file says the same thing in words -- its
descriptions read "cvmod = 1 low-field mobility", "cvmod = 1 DIBL
coefficient" (lines 727, 312).

Measured on the real simulator in Step 20, at Vg = 0.60 V, Vd = 50 mV, as
the swing of the drain's share of the channel charge over VSATCV's whole
box:

    at CVMOD = 0   0.0319 percentage points        (nothing)
    at CVMOD = 1   6.4542 percentage points        (a factor of 202)

PSATCV, DELTAVSATCV, PCLMCV and ASAT are different: they act at BOTH
settings, because `DvsatCV` (2367-2382) and `MclmCV` (2386) are computed
outside the switch.
"""

# name -> (what it does, the proving line(s) of bsimcmg_body.include,
#          True if it needs CVMOD = 1 to act at all)
FREE = {
    # ---- the parasitic floor: overlap, fringe, gate-to-substrate --------
    "cgso":     ("gate-source overlap, per unit width", "2512", False),
    "cgdo":     ("gate-drain overlap, per unit width", "2516", False),
    "cgsl":     ("bias-dependent gate-source overlap", "2512", False),
    "cgdl":     ("bias-dependent gate-drain overlap", "2516", False),
    "ckappas":  ("shapes CGSL's bias dependence", "2512", False),
    "ckappad":  ("shapes CGDL's bias dependence", "2516", False),
    "cfs":      ("outer fringe, source side", "2532", False),
    "cfd":      ("outer fringe, drain side", "2533", False),
    "cgbo":     ("gate-substrate overlap per gate contact", "931, 933", False),
    "cgbn":     ("gate-substrate overlap per fin", "931, 933", False),
    "cgbw":     ("GAA gate-substrate overlap per unit area", "933", False),
    "cgbl":     ("bias-dependent gate-substrate (bulkmod != 0)", "3074", False),
    "ckappab":  ("shapes CGBL (bulkmod != 0)", "3074", False),
    "vfbsdcv":  ("flatband reference of the overlap charge", "2512, 2516",
                 False),
    "covs":     ("source overlap, absolute (cgeomod = 1)", "2555", False),
    "covd":     ("drain overlap, absolute (cgeomod = 1)", "2556", False),
    "cgsp":     ("source fringe, absolute (cgeomod = 1)", "2560", False),
    "cgdp":     ("drain fringe, absolute (cgeomod = 1)", "2561", False),
    "cdsp":     ("drain-source fringe, all cgeomod", "2596", False),
    # ---- the C-V geometry ----------------------------------------------
    "deltawcv": ("width the charge is computed on", "349, 2471", False),
    "dlc":      ("length the charge is computed on", "168, 2471", False),
    "dlcacc":   ("accumulation length (bulkmod != 0)", "169", False),
    "qmtcencv": ("charge-centroid thickness -> coxeff", "2240, 2471", False),
    "qmtcencva": ("the same, accumulation (bulkmod != 0)", "2248", False),
    # ---- the C-V saturation family -------------------------------------
    "psatcv":   ("exponent of DvsatCV", "2374-2380", False),
    "deltavsatcv": ("linear-region term of DvsatCV", "2379-2380", False),
    "pclmcv":   ("channel-length modulation of the charge", "2386", False),
    "asat":     ("straight multiplier on DvsatCV", "2381-2382", False),
    "vsatcv":   ("saturation velocity of the charge", "2086, 2094, 2368",
                 True),
    "u0cv":     ("low-field mobility of the charge", "1988, 2086, 2368",
                 True),
    "uacv":     ("mobility degradation of the charge", "2066-2068, 2287",
                 True),
    "uccv":     ("body-effect mobility of the charge", "2066", True),
    "udcv":     ("Coulomb scattering of the charge", "2066-2068, 2287", True),
    "eta0cv":   ("DIBL of the charge", "1983", True),
    "atcv":     ("temperature coefficient of VSATCV", "1205, 1277", True),
}

# name -> (why it is NOT free, the line that proves it)
SHARED = {
    "ksativ": ("it sets BOTH saturation voltages: the current's at line 1901"
               " and the charge's at line 2089", "1901, 2089"),
    "mexp":   ("it smooths BOTH effective drain voltages: the current's at"
               " line 1916 and the charge's at line 2103", "1916, 2103"),
    "qmfactorcv": ("despite the name, it enters the surface-potential solve"
                   " that the CURRENT is built on", "1818, 1835-1845, 1926"),
    "eta1":   ("multiplies ETA0 and ETA0CV alike", "1983 and the I-V DIBL"),
}

SWITCHES = ("cvmod", "cgeomod", "bulkmod", "geomod", "rgatemod", "rdsmod",
            "nqsmod", "shmod", "subbandmod", "cgeo1sw", "asymmod",
            "mobscmod", "fnmod", "tnoimod", "tempmod", "cryomod")


def free_names(card=None, cvmod=0):
    """The free-zone names, optionally filtered to what can act right now.

    With `cvmod=0` the parameters marked CVMOD-only are left out, because at
    that setting the model never reads them and fitting them is fitting air.
    """
    out = []
    for n, (_w, _l, needs) in sorted(FREE.items()):
        if needs and int(cvmod) != 1:
            continue
        if card is not None and n not in card:
            pass
        out.append(n)
    return out


def format_table(cvmod=0):
    L = ["  the FREE ZONE -- parameters the drain current cannot see,",
         "  each with the line of bsimcmg_body.include that proves it",
         "",
         "  %-12s %-9s %-46s %s"
         % ("parameter", "needs", "what it does", "body.include"),
         "  %-12s %-9s %-46s %s" % ("", "CVMOD=1", "", "line"),
         "  " + "-" * 92]
    for n in sorted(FREE):
        w, ln, needs = FREE[n]
        L.append("  %-12s %-9s %-46s %s"
                 % (n, "yes" if needs else "-", w[:46], ln))
    L.append("")
    L.append("  and the ones that LOOK free and are NOT:")
    for n in sorted(SHARED):
        why, ln = SHARED[n]
        L.append("  %-12s %s" % (n, why))
        L.append("  %-12s   (bsimcmg_body.include line %s)" % ("", ln))
    if int(cvmod) != 1:
        L.append("")
        L.append("  CVMOD is 0 on this card, so the parameters marked"
                 " 'yes' above are")
        L.append("  not read by the model at all right now.")
    return "\n".join(L)


def verify_scope(curves_before, curves_after, iv_names, rel_tol=1.0e-9):
    """Did this parameter really leave every current sweep alone?

    Returns {"free": bool, "worst_rel": float, "where": name}. The comparison
    is point by point on the sweeps named in `iv_names`, as a relative
    difference, so it is independent of how large the current is.

    `rel_tol` is deliberately tiny. This is not asking "did the current
    change much"; it is asking "did the current change AT ALL". A parameter
    the model never reads produces a bit-identical listing, and anything else
    means the citation was misread and the parameter belongs in the gated
    set.
    """
    import numpy as np
    worst, where = 0.0, None
    for n in iv_names:
        a = (curves_before or {}).get(n)
        b = (curves_after or {}).get(n)
        if a is None or b is None:
            return {"free": False, "worst_rel": float("inf"), "where": n,
                    "missing": True}
        ya = np.abs(np.asarray(a[1], float))
        yb = np.abs(np.asarray(b[1], float))
        if len(ya) != len(yb):
            return {"free": False, "worst_rel": float("inf"), "where": n,
                    "ragged": True}
        d = np.abs(yb - ya) / np.maximum(ya, 1e-30)
        m = float(np.max(d)) if len(d) else 0.0
        if m > worst:
            worst, where = m, n
    return {"free": bool(worst <= rel_tol), "worst_rel": worst,
            "where": where}
