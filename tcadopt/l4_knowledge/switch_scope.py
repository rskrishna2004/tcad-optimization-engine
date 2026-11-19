"""l4_knowledge.switch_scope -- what a BSIM-CMG mode switch turns on.

WHY THIS EXISTS
---------------
`cv_scope` answers "can this parameter affect that measurement". It answers it
for a PARAMETER, at a fixed set of mode switches. That is the easy half.

The hard half is the switch itself. A mode switch is not a knob, it is a
different model. Flipping one can:

  * bring parameters to life that were multiplied by zero before, so a census
    that called them dead was measuring the zero rather than the parameter
    (this project made that exact mistake three times with CKAPPAS/CKAPPAD);
  * add whole terms to the charge, so a capacitance fit that was finished is
    no longer finished;
  * perturb the DRAIN CURRENT, which means the stage cannot hide behind
    `FrozenGate` and the no-regression question has to be asked properly.

So before a run flips a switch it should be able to say, from the model source
and with line numbers, which of those three it is about to do. That is this
table. Then `verify_switch` MEASURES it, because a table is a reading and a
measurement is a fact.

HOW THE TABLE WAS BUILT
-----------------------
By grepping BSIM-CMG 112.1.0 `bsimcmg_body.include` (3659 lines),
`bsimcmg_parameters.include` and `bsimcmg_checking.include` for every
occurrence of each switch name and reading each branch. The line numbers are
that file's. A different model version needs the table rebuilt, which is why
nothing here is trusted without `verify_switch`.
"""

import numpy as np


# ---------------------------------------------------------------------------
#  BULKMOD
# ---------------------------------------------------------------------------
#  `MPIcc(bulkmod, 0, "", 0, 2, "0: SOI multi-gate; 1: Bulk multi-gate;
#                                2: for decoupled bulk multi-gate")
#                                        bsimcmg_parameters.include line 85
#
#  48 branches in the body reference it. Grouped by what they do, and by what
#  each one does ON A CARD WITH THE SUBSTRATE TIED TO THE SOURCE, which is how
#  a gate-all-around deck is wired (`M1 nd ng 0 0 nt nch`, so ves = 0).

BULKMOD_1 = {
    "turns_on": [
        ("the bias-dependent gate-to-substrate capacitance", "3069-3076",
         ("Qeg gains  -NFINtotal*LeffCV*CGBL*(T3 - vge_overlap"
          " + 0.5*CKAPPAB*(sqrt(1+4*vge_overlap/CKAPPAB) - 1))."
          " This is the ONLY bias-dependent Cgb term in the model.")),
        ("an accumulation-charge branch", "2176-2242",
         ("a full surface-potential solve in accumulation, feeding"
          " qi_acc_for_QM, added to the terminal charges at 2477-2484.")),
        ("the accumulation QM correction", "2245-2249",
         "needs QMTCENCVA != 0 as well, so it stays off unless asked for."),
        ("the substrate junction diodes", "3040-3061",
         ("needs ASEJ/ADEJ/PSEJ/PDEJ, all of which default to 0, so zero"
          " area and therefore no junction current and no junction charge.")),
        ("a GIDL substrate component", "2864, 2921",
         "needs GIDLMOD = 2 or 3 as well."),
    ],
    "perturbs_the_current": [
        ("the surface potential, source side", "1815-1819",
         ("T3 = -K1_t/(2*nVtm)*(sqrt(hypsmooth(2*phib+vch-ves,0.1))"
          " - sqrt(2*phib)) is subtracted inside T0 and T1.")),
        ("the surface potential, drain side", "1923-1927",
         "the same term at the drain end."),
    ],
    "does_nothing_here": [
        ("the body-effect mobility term, current", "1877",
         "UA_a + UC_a*veseff. UC defaults to 0 AND veseff = 0."),
        ("the body-effect mobility term, charge", "2065",
         "UACV_t + UCCV_t*veseff. UCCV defaults to UC = 0 AND veseff = 0."),
        ("the effective mobility term", "2266",
         "same, UC_a*veseff."),
        ("PHIBE", "1712, 2360",
         ("1712 is vesmax = 0.95*PHIBE, a clamp on ves which is 0; 2360 is"
          " inside bulkmod == 2 and evaluates sqrt(PHIBE-0)-sqrt(PHIBE) = 0.")),
        ("K2, the bulkmod = 2 body effect", "2356-2362",
         "inside bulkmod == 2 only, and K2 defaults to 0."),
    ],
    # The parameters that are multiplied by zero, or not read at all, until
    # bulkmod != 0. Each appears ONLY inside a bulkmod branch -- verified by
    # grepping the whole body for each name.
    "newly_live": {
        "cgbl": ("F/m", 0.0,
                 "the bias-dependent Cgb magnitude. body 3074 ONLY."
                 " Defaults to 0, so the term is still multiplied by zero"
                 " until you set it."),
        "ckappab": ("V", 0.6,
                    "where the Cgb bend sits. body 3074 ONLY."),
        "delvfbacc": ("V", 0.0,
                      "accumulation flatband offset, which slides the bend"
                      " along the gate axis. body 2179 and 3071 ONLY."),
        "dlcacc": ("m", 0.0,
                   "the length the accumulation charge is computed on."
                   " body 169 -> LeffCV_acc."),
        "dwcacc": ("m", 0.0,
                   "the GAA width the accumulation charge is computed on."
                   " body 351 -> WeffCV_acc, geomod = 5 branch."),
        "qmtcencva": ("", 0.0,
                      "accumulation charge-centroid thickness. body 2248."),
    },
    # Things the model will refuse, from bsimcmg_checking.include.
    "checks": [
        ("K1 >= 1.0e-6 is FATAL-enforced", "checking 48-53",
         ("`if (bulkmod != 0) if (K1_i < 1.0e-6) $error(...)`. So K1 cannot"
          " be set to zero to make the current perturbation vanish. The"
          " default IS 1.0e-6, which is the smallest legal value, and that"
          " is why the current moves by about a part in a million rather"
          " than not at all.")),
        ("PHIBE is clamped to [0.2, 1.2]", "checking 152-160",
         "a warning, not an error. PHIBE defaults to 0.7 and is inert here."),
    ],
    "verdict": ("NOT a free-zone change. The current moves, by a very small"
                " amount that cannot be made zero, so this stage belongs"
                " behind the ordinary no-regression gate and not behind"
                " FrozenGate."),
}

SWITCHES = {
    ("bulkmod", 1): BULKMOD_1,
    ("bulkmod", 2): dict(BULKMOD_1,
                         verdict=("everything bulkmod = 1 does, plus the K2"
                                  " body effect at body 2356-2362. K2"
                                  " defaults to 0.")),
}


def newly_live(switch, value=1):
    """The parameters that become readable when `switch` is set to `value`."""
    e = SWITCHES.get((switch, int(value)))
    return dict(e["newly_live"]) if e else {}


def format_switch(switch, value=1, width=78):
    """A readable account of what the switch does, with source lines."""
    e = SWITCHES.get((switch, int(value)))
    if not e:
        return "  no entry for %s = %s" % (switch, value)
    L = ["  %s = %s, from BSIM-CMG 112.1.0's own source" % (switch.upper(),
                                                            value),
         "",
         "  WHAT IT TURNS ON"]
    for name, line, why in e["turns_on"]:
        L.append("    %-44s body %s" % (name, line))
        for seg in _wrap(why, width - 8):
            L.append("        " + seg)
    L.append("")
    L.append("  WHAT IT DOES TO THE DRAIN CURRENT")
    for name, line, why in e["perturbs_the_current"]:
        L.append("    %-44s body %s" % (name, line))
        for seg in _wrap(why, width - 8):
            L.append("        " + seg)
    L.append("")
    L.append("  BRANCHES THAT OPEN BUT EVALUATE TO NOTHING ON THIS CARD")
    for name, line, why in e["does_nothing_here"]:
        L.append("    %-44s body %s" % (name, line))
        for seg in _wrap(why, width - 8):
            L.append("        " + seg)
    L.append("")
    L.append("  PARAMETERS THAT COME ALIVE")
    L.append("    %-12s %-10s %-12s %s" % ("name", "unit", "default", "scope"))
    for k in sorted(e["newly_live"]):
        unit, dflt, why = e["newly_live"][k]
        L.append("    %-12s %-10s %-12s" % (k, unit or "-", "%.6g" % dflt))
        for seg in _wrap(why, width - 8):
            L.append("        " + seg)
    L.append("")
    L.append("  WHAT THE MODEL WILL REFUSE")
    for name, line, why in e["checks"]:
        L.append("    %-44s %s" % (name, line))
        for seg in _wrap(why, width - 8):
            L.append("        " + seg)
    L.append("")
    L.append("  VERDICT")
    for seg in _wrap(e["verdict"], width - 4):
        L.append("    " + seg)
    return "\n".join(L)


def _wrap(text, width):
    out, line = [], ""
    for w in str(text).split():
        if line and len(line) + 1 + len(w) > width:
            out.append(line)
            line = w
        else:
            line = (line + " " + w).strip()
    if line:
        out.append(line)
    return out


def verify_switch(curves_before, curves_after, iv_names, cv_names=(),
                  eps=1.0e-30):
    """MEASURE what a switch did, rather than believe the table.

    Returns {"iv_worst", "iv_where", "cv_worst", "cv_where", "iv_moved",
             "cv_moved", "per_sweep"} where the worsts are the largest
    point-by-point relative difference found.

    The point of reporting the current's movement as a NUMBER rather than a
    yes/no is that for a structural switch the honest answer is usually
    "yes, by this much", and whether that much matters is a decision someone
    has to make with the number in front of them.
    """
    per = {}
    for group, names in (("iv", tuple(iv_names)), ("cv", tuple(cv_names))):
        for n in names:
            a = (curves_before or {}).get(n)
            b = (curves_after or {}).get(n)
            if a is None or b is None:
                per[n] = {"group": group, "rel": None, "note": "missing"}
                continue
            ya = np.asarray(a[1], float)
            yb = np.asarray(b[1], float)
            m = min(len(ya), len(yb))
            if m < 1:
                per[n] = {"group": group, "rel": None, "note": "empty"}
                continue
            ya, yb = ya[:m], yb[:m]
            den = np.maximum(np.abs(ya), eps)
            rel = np.abs(yb - ya) / den
            k = int(np.argmax(rel))
            per[n] = {"group": group, "rel": float(rel[k]),
                      "at": float(np.asarray(a[0], float)[k]), "note": ""}
    out = {"per_sweep": per}
    for group in ("iv", "cv"):
        vals = [(v["rel"], n) for n, v in per.items()
                if v["group"] == group and v["rel"] is not None]
        if vals:
            worst, where = max(vals)
            out[group + "_worst"] = worst
            out[group + "_where"] = where
            out[group + "_moved"] = bool(worst > 0.0)
        else:
            out[group + "_worst"] = None
            out[group + "_where"] = None
            out[group + "_moved"] = None
    return out


def format_verify(res, title="what the switch actually moved"):
    L = ["  " + title,
         "    %-24s %-14s %s" % ("group", "worst rel", "worst sweep")]
    for group, label in (("iv", "drain current"), ("cv", "capacitance")):
        w = res.get(group + "_worst")
        L.append("    %-24s %-14s %s"
                 % (label,
                    "-" if w is None else "%.3e" % w,
                    res.get(group + "_where") or "-"))
    L.append("")
    L.append("    sweep                     worst rel      at Vsweep")
    for n in sorted(res.get("per_sweep", {})):
        v = res["per_sweep"][n]
        L.append("    %-25s %-14s %s"
                 % (n,
                    "-" if v.get("rel") is None else "%.3e" % v["rel"],
                    "-" if v.get("at") is None else "%.3f" % v["at"]))
    return "\n".join(L)
