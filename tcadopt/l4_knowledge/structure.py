# -*- coding: utf-8 -*-
"""l4_knowledge.structure -- the device the card is supposed to be modelling.

WHY THIS MODULE EXISTS
----------------------
Twenty nine steps of this project ran with `bulkmod = 0`, which in BSIM-CMG
means "SOI multi-gate: there is no substrate to talk to". The device is not
SOI. Its own Sentaurus Structure Editor script says so on one line:

    (define EnableBOX 0)                ; 1=SOI-style BOX, 0=bulk

There is a silicon substrate, it is boron doped at 1e15, and it has its own
contact. What sits under the gate is a 3 nm SiO2 BOTTOM DIELECTRIC ISOLATION
plug, which is a local plug to stop gate to substrate leakage, not a buried
oxide. The source and the drain are not isolated from the substrate at all:
they sit on p type counter doped pockets which sit on the substrate.

Nothing in the engine could have caught that, because the engine had never
been shown the structure. It was reading a model card, and a model card
cannot tell you whether its switches are the right switches. So the card and
the structure drifted apart and stayed apart for twenty nine steps.

This module closes that. The structure is written down here as numbers taken
from the SDE script, each with the line that defines it, and `check` compares
a card against it and says which settings disagree. From here on a step that
starts with a card the structure does not support says so in its first thirty
seconds, with the line of the structure file that contradicts it.

THE RULE THIS ENFORCES
-----------------------
A model card has two kinds of number in it. GEOMETRY AND MATERIAL numbers are
measurements of the device and are not free: wgaa, tgaa, ngaa, nfin, l, eot,
nbody, nsd. MODE SWITCHES choose which equations run and must match the
device's topology: bulkmod, geomod, cgeomod, rgeomod. Neither kind is ever a
fitting parameter, and both are checkable against the structure. Only the
third kind, the physical fitting parameters, belong to the optimiser.
"""
from __future__ import print_function

VERSION = "1.1.30"

#  Every entry: (value, unit, the line of the SDE script it comes from, note).
#  Read out of NS_SAM_Ascm(structure)file.txt, the 4 stacked nanosheet GAA FET
#  Sentaurus Structure Editor script, revision of 25 Jun 2026.
DEVICE = {
    "nanosheet_thickness_m": (5.0e-9, "m", "(define Tsi (* 5 1e-3))",
                              "sheet silicon thickness along Y"),
    "nanosheet_width_m": (10.0e-9, "m", "(define Wsi (* 10 1e-3))",
                          "sheet width along Z"),
    "n_sheets": (4, "", "(define Nch 4)", "sheets in the stack"),
    "n_stacks": (1, "", "one stack in the script", "fins / stacks in parallel"),
    "pitch_m": (15.0e-9, "m", "(define Pitch (* 15 1e-3))",
                "sheet centre to sheet centre"),
    "sheet_gap_m": (10.0e-9, "m", "Pitch - Tsi", "silicon to silicon gap"),
    "gate_length_m": (12.0e-9, "m", "2 * (define QuarterLch (* 6 1e-3))",
                      "the gate and the whole gate stack span +/- 6 nm"),
    "channel_silicon_length_m": (22.0e-9, "m", "(define Lch (* 22 1e-3))",
                                 "the silicon runs +/- 11 nm"),
    "ungated_each_side_m": (5.0e-9, "m", "HalfLch - QuarterLch = 11 - 6",
                            "channel silicon the gate does not cover"),
    "il_sio2_m": (0.5e-9, "m", "(define T_SiO2_IL (* 0.5 Tox))",
                  "interfacial SiO2"),
    "hk_hfo2_m": (1.5e-9, "m", "(define T_HfO2_HK (* 1.5 Tox))", "HfO2"),
    "gate_metal_m": (3.0e-9, "m", "(define Tg (* 3 1e-3))", "TiN"),
    "spacer_length_m": (5.0e-9, "m", "HalfLch - QuarterLch, Si3N4 spacers",
                        "Si3N4 spacer along X"),
    "spacer_material": ("Si3N4", "", '"Si3N4" "R.SpacerL"', "spacer"),
    "sd_epi_length_m": (8.0e-9, "m", "(define Lsd (* 8 1e-3))",
                        "source and drain epi block"),
    "channel_doping_cm3": (1.0e15, "cm^-3",
                           '"Const.BoronCh" "BoronActiveConcentration" 1e15',
                           "boron, p type"),
    "sd_doping_cm3": (1.0e20, "cm^-3",
                      '"Const.AsSD" "ArsenicActiveConcentration" 1e20',
                      "arsenic, n type"),
    "substrate_doping_cm3": (1.0e15, "cm^-3",
                             '"Const.BoronSub" 1e15', "boron, p type"),
    "pocket_doping_cm3": (1.0e19, "cm^-3",
                          "(define Pocket_DopingB (* 1 1e19))",
                          "boron counter doped pocket under source and drain"),
    "sd_gauss_depth_m": (1.0e-9, "m", "(define SdDiffDepth (* 1.0 1e-3))",
                         "arsenic decays to 1e15 one nm into the channel"),
    #  the three that decide the switches
    "is_soi": (False, "", "(define EnableBOX 0)  ; 1=SOI-style BOX, 0=bulk",
               "there is NO buried oxide. This is a bulk device"),
    "has_substrate_contact": (True, "",
                              '(sdegeo:set-contact ... "Substrate")',
                              "the substrate is a measured terminal"),
    "has_pts": (False, "", "(define EnablePTS 0)",
                "no punch through stopper region"),
    "bdi_thickness_m": (3.0e-9, "m", "(define BDI_Thickness (* 3 1e-3))",
                        "SiO2 bottom dielectric isolation plug UNDER THE GATE "
                        "only, between the gate metal and the substrate"),
    "bdi_half_span_m": (6.6e-9, "m", "QuarterLch + BDI_Undercut = 6 + 0.6",
                        "the BDI plug and its undercut wings along X"),
    "gate_half_width_z_m": (10.0e-9, "m", "Zgate = Zox_HK + Tg",
                            "outer Z edge of the gate metal block"),
}

#  What the card MUST say, and why, with the structure entry that decides it.
SWITCH_RULES = [
    ("bulkmod", 1,
     "is_soi",
     "The structure is BULK with a substrate contact, so the body terminal "
     "exists and the gate to substrate charge is bias dependent. bulkmod = 0 "
     "tells BSIM-CMG there is no substrate at all, which makes Cgb a "
     "constant (body line 3067, with the bias dependent part behind "
     "`if (bulkmod != 0)` at 3069). A 3 nm BDI plug under the gate is a "
     "local isolation plug, NOT a buried oxide, and it does not make the "
     "device SOI."),
    ("geomod", 5, "n_sheets",
     "Rectangular sheets with the gate all around, so geomod = 5, which is "
     "the one that reads wgaa, tgaa and ngaa."),
]

#  Geometry the card must carry, taken straight from the structure.
GEOMETRY_RULES = [
    ("tgaa", "nanosheet_thickness_m", 1.0e-12),
    ("wgaa", "nanosheet_width_m", 1.0e-12),
    ("ngaa", "n_sheets", 0.5),
    ("nfin", "n_stacks", 0.5),
    ("l", "gate_length_m", 1.0e-12),
    ("tsus", "sheet_gap_m", 1.0e-12),
    ("lsp", "spacer_length_m", 1.0e-12),
]


def eot_from_stack(eps_hk, il_m=None, hk_m=None, eps_ox=3.9):
    """The equivalent oxide thickness of the IL plus high k stack."""
    il = DEVICE["il_sio2_m"][0] if il_m is None else il_m
    hk = DEVICE["hk_hfo2_m"][0] if hk_m is None else hk_m
    return il + hk * eps_ox / float(eps_hk)


def implied_eps_hk(eot, il_m=None, hk_m=None, eps_ox=3.9):
    """The high k permittivity a given EOT implies. Our card says 0.734 nm,
    which needs exactly 25.0, and that is an ASSUMPTION until the SDEVICE
    deck is read, because the SDE script names the material and not its
    permittivity."""
    il = DEVICE["il_sio2_m"][0] if il_m is None else il_m
    hk = DEVICE["hk_hfo2_m"][0] if hk_m is None else hk_m
    if eot <= il:
        return None
    return hk * eps_ox / (eot - il)


def weff_geomod5(card=None):
    """The model's own electrical width for geomod = 5, body line 285:
        Weff1 = 2 * (WGAAeff + tgaa) + dws1,  times ngaa sheets."""
    c = card or {}
    w = float(c.get("wgaa", DEVICE["nanosheet_width_m"][0]))
    t = float(c.get("tgaa", DEVICE["nanosheet_thickness_m"][0]))
    n = float(c.get("ngaa", DEVICE["n_sheets"][0]))
    nf = float(c.get("nfin", DEVICE["n_stacks"][0]))
    return nf * n * 2.0 * (w + t)


def check(card, rules_switch=None, rules_geom=None):
    """Compare a card with the structure. Returns a list of findings.

    Each finding is {"what", "card", "structure", "severity", "why"}.
    severity is "WRONG" when the card contradicts the structure, "CHECK"
    when the card cannot be decided from the structure alone and a human
    has to confirm it, and "OK" when it agrees.
    """
    out = []
    for name, want, key, why in [(a, b, c, d) for a, b, c, d in
                                 (rules_switch or SWITCH_RULES)]:
        got = card.get(name)
        ok = (got is not None and int(round(float(got))) == int(want))
        out.append({"what": name, "card": got, "structure": want,
                    "severity": "OK" if ok else "WRONG",
                    "line": DEVICE[key][2], "why": why})
    for name, key, tol in (rules_geom or GEOMETRY_RULES):
        want = DEVICE[key][0]
        got = card.get(name)
        if got is None:
            out.append({"what": name, "card": None, "structure": want,
                        "severity": "WRONG", "line": DEVICE[key][2],
                        "why": "the structure defines it and the card does "
                               "not carry it"})
            continue
        ok = abs(float(got) - float(want)) <= tol
        out.append({"what": name, "card": float(got), "structure": want,
                    "severity": "OK" if ok else "WRONG",
                    "line": DEVICE[key][2], "why": DEVICE[key][3]})
    #  doping, in the model's units (m^-3) against the script's (cm^-3)
    for name, key in (("nbody", "channel_doping_cm3"),
                      ("nsd", "sd_doping_cm3")):
        want = DEVICE[key][0] * 1.0e6
        got = card.get(name)
        ok = (got is not None
              and abs(float(got) / want - 1.0) < 1.0e-6)
        out.append({"what": name, "card": got, "structure": want,
                    "severity": "OK" if ok else "WRONG",
                    "line": DEVICE[key][2],
                    "why": "%s in the script, which is %g m^-3"
                           % (DEVICE[key][2], want)})
    return out


#  Things the structure has and the card has no way to represent, so they are
#  carried by a fitted parameter instead. Printing these is the point: a
#  reader can then see what the fitted number is standing in for.
NOT_REPRESENTED = [
    ("5 nm of UNGATED channel silicon on each side",
     "Lch is 22 nm and the gate is 12 nm. The arsenic from the source and "
     "drain decays to the 1e15 background 1 nm in, so about 4 nm each side "
     "is lightly doped, ungated channel under the Si3N4 spacer. BSIM-CMG "
     "has no region for that: it is lumped into rdsw for the current and "
     "into cgsl, cgdl, cfs and deltawcv for the charge."),
    ("the 3 nm SiO2 BDI plug under the gate",
     "This is the gate to substrate path, and it is why the device's Cgb "
     "is 1.4 to 1.9 aF and falls by 27 per cent across the gate sweep. "
     "With bulkmod = 1 the model has cgbl, ckappab, eotacc and delvfbacc "
     "for exactly this. The physical plug is 3 nm of SiO2 over a "
     "13.2 nm by 20 nm footprint, which is 3.0 aF, the right order."),
    ("the p type 1e19 boron pockets under the source and drain",
     "They stop source and drain dopant reaching the substrate. In the "
     "compact model they would appear as the source and drain junction to "
     "the body, which is asej, adej, jss and jsd, all of which default to "
     "zero area and so contribute nothing until they are given one."),
    ("the counter doped pocket junction and the 5 nm over etch",
     "Geometry the compact model has no terminal for. It affects Ioff and "
     "the subthreshold slope, which the card absorbs into cdsc and cdscd."),
]


def format_check(findings, title=None):
    L = [title or "    does the card describe the device in the structure "
                  "file?", "",
         "      %-10s %-16s %-16s %s"
         % ("setting", "the card says", "the structure", "verdict"),
         "      " + "-" * 70]
    for f in findings:
        c = f["card"]
        s = f["structure"]
        cs = "missing" if c is None else ("%g" % c if isinstance(c, float)
                                          else str(c))
        ss = "%g" % s if isinstance(s, (int, float)) else str(s)
        L.append("      %-10s %-16s %-16s %s"
                 % (f["what"], cs, ss, f["severity"]))
    bad = [f for f in findings if f["severity"] == "WRONG"]
    L.append("      " + "-" * 70)
    if not bad:
        L.append("      every setting agrees with the structure.")
    else:
        L.append("      %d SETTING%s DISAGREE%s WITH THE STRUCTURE:"
                 % (len(bad), "" if len(bad) == 1 else "S",
                    "S" if len(bad) == 1 else ""))
        for f in bad:
            L.append("")
            L.append("        %s: the card has %s, the structure says %s"
                     % (f["what"], f["card"], f["structure"]))
            L.append("        the line that decides it:")
            L.append("          %s" % f["line"])
            for chunk in _wrap(f["why"], 62):
                L.append("        %s" % chunk)
    return "\n".join(L)


def _wrap(text, width):
    out, line = [], ""
    for w in str(text).split():
        if not line:
            line = w
        elif len(line) + 1 + len(w) <= width:
            line += " " + w
        else:
            out.append(line)
            line = w
    if line:
        out.append(line)
    return out


def format_not_represented(title=None):
    L = [title or "    what the structure has that the card cannot say:", ""]
    for what, why in NOT_REPRESENTED:
        L.append("      %s" % what)
        for chunk in _wrap(why, 64):
            L.append("        %s" % chunk)
        L.append("")
    return "\n".join(L)
