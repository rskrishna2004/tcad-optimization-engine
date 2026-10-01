"""l6_verify.inventory -- what parameters does this simulator ACTUALLY HAVE?
(TCADOpt v1.1.15)

WHY THIS FILE EXISTS
--------------------
`connectivity.py` answers "does this simulator USE the parameter I set?".
It cannot answer the question underneath it: "what parameters are there?"
Every census this project has run was a list I typed from memory of the
manual, and a parameter nobody thinks to type is a parameter that is never
tested. Step 16 found three that way -- CGSO, CGDO and CGBO had been zero
in every card since Step 1 -- and found them only because I happened to
list them.

The simulator has been printing the answer all along. Every deck this
engine writes carries `.option list node` (l2_decks/cardgen.py), and
PrimeSim HSPICE responds by echoing the COMPLETE model parameter table
into the .lis file: every name it implements at this LEVEL and VERSION,
with the value it is using. That listing is written next to every run and
has never been read.

This module reads it. Three functions, and the last one is the point:

    read_model_params(lis)   -> {name: value} as the simulator prints them
    raw_block(lis)           -> the same text, unparsed, so a human can
                                check the parser instead of trusting it
    diff_card(inv, card)     -> what the model HAS that the card never sets

Nothing here guesses. If the parser finds nothing it says so and hands
back the raw text, which is the correct behaviour for a tool whose whole
job is to stop people working from memory.

$Id: inventory.py, 2026/09/27 v1.1.15 $
"""
import os
import re

# a name=value pair as HSPICE prints them, several to a line
_PAIR = re.compile(r"([A-Za-z_][A-Za-z_0-9]*)\s*=\s*"
                   r"([-+]?(?:\d+\.?\d*|\.\d+)(?:[eEdD][-+]?\d+)?)")
_START = re.compile(r"model\s+parameters", re.I)
_SECTION = re.compile(r"^\s*\*{4,}")


def find_listing(res, prefer=None):
    """The .lis file a result wrote, or None."""
    rdir = (res or {}).get("run_dir")
    if not rdir or not os.path.isdir(rdir):
        return None
    names = sorted(f for f in os.listdir(rdir) if f.endswith(".lis"))
    if not names:
        return None
    if prefer:
        for n in names:
            if prefer in n:
                return os.path.join(rdir, n)
    return os.path.join(rdir, names[0])


def raw_block(lis_path, max_lines=None, after=_START):
    """The listing's model-parameter section, verbatim -- ALL of it.

    v1.1.15: `max_lines` now defaults to None, meaning "read to the end of
    the section". It used to default to 400 and that was a real bug, not a
    tuning choice: PrimeSim's table for BSIM-CMG 111.21 is 1878 lines long,
    so Step 17's inventory saw 396 parameters out of 1865 and reported the
    other 1469 -- ETA0CV, U0CV, UACV, PSATCV, ACH_UFCM, DVTP0 among them --
    as if the model did not have them. The section end is found the way it
    always was, by the next `******` banner line, so the cap is now only a
    runaway guard.
    """
    try:
        txt = open(lis_path).read()
    except Exception:
        return []
    cap = 200000 if max_lines is None else int(max_lines)
    lines = txt.split("\n")
    out, on = [], False
    for ln in lines:
        if not on:
            if after.search(ln):
                on = True
                out.append(ln.rstrip())
            continue
        if _SECTION.match(ln) and len(out) > 2:
            break
        out.append(ln.rstrip())
        if len(out) >= cap:
            break
    return out


def read_model_params(lis_path, max_lines=None):
    """{name: float} from the listing's model-parameter echo.

    Returns ({}, n_lines_seen) when the parser recognises nothing, which is
    a result, not an error: the format differs and the raw block should be
    read instead.

    v1.1.15: the section HEADER line is no longer parsed. It reads
    `****** mos model parameters tnom= 25.000 temp= 25.000 ******`, and
    feeding it to the pair regex invented two model parameters, TNOM and
    TEMP, that are not in the table at all.
    """
    block = raw_block(lis_path, max_lines=max_lines)
    out = {}
    for k, ln in enumerate(block):
        if k == 0 and _START.search(ln):
            continue
        for m in _PAIR.finditer(ln):
            nm = m.group(1).lower()
            v = m.group(2).replace("d", "e").replace("D", "e")
            try:
                out[nm] = float(v)
            except ValueError:
                continue
    return out, len(block)


# BSIM-CMG spells the geometry dependence of a parameter P as LP, NP, PP,
# WP and P2P, and its variants as PCV (the capacitance's own copy), PR (the
# reverse-mode copy), PTHIN / PTNI / PIR (the thin-body copies) and
# PN1 / PN2 / PLT (body-doping and temperature). Every one of those is a
# separate echoed name, which is why the table has 1865 entries and only a
# few hundred distinct physical knobs.
_GEO_PREFIX = ("p2", "l", "n", "p", "w", "t", "a", "b", "k")
_VARIANT_SUFFIX = ("cva", "cv", "thin", "tni", "ir", "rsd", "acc",
                   "n1", "n2", "lt", "r", "1", "2")


def core_names(inv):
    """The names in the listing that are not a derived variant of another.

    A name is DERIVED when stripping one of the model's own geometry
    prefixes leaves a name that is also in the listing: LVSATCV -> VSATCV,
    WUACV -> UACV. Everything else is a knob in its own right. On this
    device's listing this turns 1865 echoed names into about 300 to read,
    which is the difference between a report and a wall of text.
    """
    have = set(inv or {})
    core = []
    for n in sorted(have):
        derived = False
        for pre in _GEO_PREFIX:
            if n.startswith(pre) and n[len(pre):] in have:
                derived = True
                break
        if not derived:
            core.append(n)
    return core


def variants(inv, stem):
    """Every echoed name built on `stem`, with its value."""
    have = dict(inv or {})
    out = {}
    for n, v in have.items():
        if n == stem:
            out[""] = v
        elif n.endswith(stem) and n[:-len(stem)] in _GEO_PREFIX:
            out[n[:-len(stem)].upper() + "-"] = v
        elif n.startswith(stem) and n[len(stem):] in _VARIANT_SUFFIX:
            out["-" + n[len(stem):].upper()] = v
    return out


def twins(inv, card, suffix="cv", rtol=2.0e-3, core_only=True):
    """C-V parameters that are silently TRACKING their DC namesakes.

    BSIM-CMG gives the capacitance its own copy of the transport parameter
    set -- VSATCV, U0CV, UACV, ETA0CV, PSATCV, DELTAVSATCV -- and each one
    DEFAULTS TO the DC parameter of the same name. Nobody sets them, so
    nobody notices; but every time a fit moves VSAT it is also moving
    VSATCV, and the capacitance changes for a reason that is nowhere in the
    card.

    This finds them by measurement, not by memory: a name ending in
    `suffix` whose echoed value equals the echoed value of its stem, to
    `rtol`, is reported as a twin, together with whether the card sets the
    stem (so the tracking is live) or not.

    Returns [{"cv": name, "dc": stem, "value": v, "card_sets_dc": bool}].

    `core_only` drops the geometry-dependence copies (LUACV tracking LUA
    and so on) so the report is the dozen names a person can act on rather
    than a hundred and twenty they cannot.
    """
    have = dict(inv or {})
    hascard = set(k.lower() for k in (card or {}))
    cores = set(core_names(have)) if core_only else set(have)
    out = []
    for n in sorted(have):
        if not n.endswith(suffix) or len(n) <= len(suffix):
            continue
        stem = n[:-len(suffix)]
        if stem not in have:
            continue
        if core_only and stem not in cores:
            continue
        a, b = have[n], have[stem]
        if a == b or abs(a - b) <= rtol * max(abs(a), abs(b), 1e-300):
            out.append({"cv": n, "dc": stem, "value": float(a),
                        "card_sets_dc": stem in hascard})
    return out


def format_twins(rows, suffix="CV"):
    L = ["  the capacitance's own copies of the transport parameters,",
         "  and which of them are TRACKING a value this card fits",
         "",
         "  %-16s %-16s %-14s %s"
         % ("the %s name" % suffix, "it is tracking", "shared value",
            "the card fits the DC one?"),
         "  " + "-" * 74]
    live = 0
    for r in rows:
        flag = "YES -- it moves when the fit moves" if r["card_sets_dc"] \
               else "no"
        live += 1 if r["card_sets_dc"] else 0
        L.append("  %-16s %-16s %-14.6g %s"
                 % (r["cv"], r["dc"], r["value"], flag))
    L.append("")
    L.append("  %d of %d are tracking a parameter THIS CARD FITS." %
             (live, len(rows)))
    if live:
        L.append("  Each of those is a capacitance knob the card has never")
        L.append("  written down and the fit has been moving anyway. Setting")
        L.append("  it explicitly breaks the tie and hands the capacitance")
        L.append("  a parameter of its own that no current can see.")
    return "\n".join(L)


def diff_card(inventory, card, structure=None, skip=()):
    """Split what the simulator has into: set by this card, and never set.

    Returns {"in_card": [...], "never_set": [(name, value), ...],
             "not_in_model": [...]} -- the last one is the honest check
    in the other direction: names the card sets that the listing does not
    echo back at all.
    """
    inv = dict(inventory or {})
    have = set(k.lower() for k in (card or {}))
    have |= set(k.lower() for k in (structure or {}))
    have |= set(k.lower() for k in skip)
    in_card, never = [], []
    for k in sorted(inv):
        (in_card if k in have else never).append(k)
    miss = sorted(k for k in have if k not in inv)
    return {"in_card": in_card,
            "never_set": [(k, inv[k]) for k in never],
            "not_in_model": miss}


def group(names, groups=None):
    """Bucket parameter names by a keyword table, for a readable report."""
    groups = groups or DEFAULT_GROUPS
    out = {}
    for n in names:
        placed = False
        for label, keys in groups:
            # a short key must START the name, or "never_touched" lands in
            # "mobility" because it contains "uc".
            if any(((n.startswith(k) or n.endswith(k)) if len(k) <= 3
                    else (k in n)) for k in keys):
                out.setdefault(label, []).append(n)
                placed = True
                break
        if not placed:
            out.setdefault("everything else", []).append(n)
    return out


DEFAULT_GROUPS = [
    ("capacitance and charge", ("cgs", "cgd", "cgb", "cov", "cf", "cv",
                                "qm", "charge", "cap", "cgeo")),
    ("mobility", ("u0", "ua", "ub", "uc", "ud", "eu", "mob", "vsat",
                  "ksativ", "psat", "mexp", "ptwg")),
    ("short channel and DIBL", ("dvt", "eta", "dsub", "cdsc", "pclm",
                                "pdibl", "drout", "pvag", "scl")),
    ("leakage", ("gidl", "igc", "igs", "igd", "btbt", "agidl", "bgidl",
                 "cgidl", "egidl", "isb", "njs", "njd")),
    ("temperature", ("tnom", "kt", "at", "ute", "prt", "temp")),
    ("noise", ("noi", "ef", "em", "af", "kf", "fnmod", "tnoi")),
    ("geometry and structure", ("l", "w", "t", "nf", "ngaa", "geomod",
                                "nbody", "nsd", "eps", "hpff", "dws",
                                "dach")),
]


def format_inventory(inv, dif, title="what this simulator has, and what"
                                     " this card has never set"):
    L = ["  %s" % title,
         "  the listing echoed %d model parameters." % len(inv or {})]
    if not inv:
        L.append("  THE PARSER RECOGNISED NOTHING. The raw block is printed")
        L.append("  below -- read it, and the parser gets fixed next step.")
        return "\n".join(L)
    L.append("  %d of them this card sets; %d it has never touched."
             % (len(dif["in_card"]), len(dif["never_set"])))
    if dif["not_in_model"]:
        L.append("")
        L.append("  IN THE CARD BUT NOT ECHOED BACK BY THE MODEL: %s"
                 % ", ".join(dif["not_in_model"][:20]))
        L.append("  (an instance parameter, or a name the model does not")
        L.append("  have -- worth one look each.)")
    by = group([n for n, _v in dif["never_set"]])
    vals = dict(dif["never_set"])
    L.append("")
    L.append("  NEVER SET BY THIS CARD, grouped:")
    for label in sorted(by):
        L.append("")
        L.append("    %s (%d)" % (label, len(by[label])))
        row = []
        for n in sorted(by[label]):
            row.append("%s=%.6g" % (n, vals[n]))
            if len(row) == 4:
                L.append("      " + "  ".join(row))
                row = []
        if row:
            L.append("      " + "  ".join(row))
    return "\n".join(L)
