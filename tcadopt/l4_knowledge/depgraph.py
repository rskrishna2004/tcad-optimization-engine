# -*- coding: utf-8 -*-
"""l4_knowledge.depgraph -- proving, from the model source, what a parameter
can and cannot move.

WHY THIS MODULE EXISTS
----------------------
`cv_scope` already answers the question "can this parameter change the drain
current". It answers it from a table I wrote by hand, by grepping the model
source and reading each branch. That table has been right about everything it
covers, and it has been wrong in the only way a hand table can be: it is
incomplete, and nothing tells you which entry is missing.

Three parameters were missing. QM0 and PQM are the two numbers that shape the
charge centroid correction, QMTCENCV is the prefactor that switches it on,
and only QMTCENCV was on the list. So for twelve steps the engine knew it was
allowed to turn the correction on and did not know it was allowed to shape
it. QMTCENCV on its own is a straight multiplier -- it scales all three
channel charges by the same factor at every bias -- and a straight multiplier
cannot fix a curve whose SHAPE is wrong. QM0 and PQM are exactly the two that
can. They sat at their defaults through every capacitance fit this project
has run.

So this module stops writing the table by hand. It reads
`bsimcmg_body.include` and works the answer out.

HOW IT WORKS
------------
It walks the body in source order and keeps, for every variable, the set of
parameters that can reach it. Three things make the answer usable rather than
"everything depends on everything":

  * A plain assignment REPLACES the variable's history. The model reuses T0
    to T9 hundreds of times, and a tracer that unions instead of replacing
    smears the whole file into every one of them. `T0 = a + b` means T0 now
    depends on a and b, and on nothing it depended on one line earlier.

  * An if / else JOINS its arms, because only one arm runs and the tracer
    does not know which. But a variable written on EVERY arm cannot keep the
    value it had on entry, so for those the entry history is dropped. That
    one rule is what separates the charge half of the model from the current
    half: `Vdsat_cv` is computed in a two-arm if, both arms assign it, so it
    carries VSATCV and not the leftovers of the line above.

  * The MODE SWITCHES are supplied by the caller. A switch is not a knob, it
    is a different model, and a branch the switches make unreachable is
    dropped rather than joined. That is what makes the answer specific to one
    card. With `nqsmod = 0`, which is this project's card, `qmtcencv` cannot
    reach a single current contribution. With `nqsmod = 2` it reaches the
    drain current directly, because `xdpart = -qd_v / qg_v` makes the charge
    partition a current. The same parameter, two opposite answers, and only
    the switches decide which.

WHAT IT PROVED ON THIS PROJECT'S CARD
--------------------------------------
Four things that cost real time to not know:

  * QM0 and PQM are charge only, and were never on the free list.

  * `rdsmod = 1` does not scale our series resistance, it READS A DIFFERENT
    PARAMETER SET. rdsw and rdswmin leave the current path and rsw, rdw,
    rswmin, rdwmin, prwgd and thirty more enter it. Our fitted rdsw = 92.28
    is simply not read any more, and the replacements are at their defaults.
    That is the whole of Step 28's "+826 per cent".

  * `rgeomod = 1` does the same with rshs and rshd out and rgeoa to rgeoe,
    rhoc, rhorsd, hepi and cratio in. Setting rshs = rshd = 0 was the right
    instinct and had no effect, because with rgeomod = 1 those two are not
    read at all. That is Step 28's "+637 per cent", and it means the switch
    was never tested -- it was run with an unfitted resistance model.

  * `cgeomod = 1`, `2` and `3` add NOTHING to the current path: not one new
    parameter can reach a current contribution. So the 2.3 per cent current
    rise Step 28 measured for cgeomod = 2 and 3 cannot be a parameter
    effect. It is the solver seeing a different parasitic network.

LIMITS, STATED PLAINLY
----------------------
A "charge only" verdict here is SOUND: the walk over-approximates, so a
parameter it clears really cannot reach a current. The reverse is not true --
a "both" verdict can be the join being careful rather than a real path. And
a reading is still a reading, so `verify` measures the claim on the real
simulator before any stage leans on it.
"""
from __future__ import print_function

VERSION = "1.1.30"

import json
import os
import re

ID = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
KEYWORDS = set("""if else begin end case casex casez endcase default for while
repeat integer real parameter analog function endfunction module endmodule
inout return and or not""".split())

#  the contributions this project's card actually makes. A name that is not
#  assigned anywhere under the given switches is a contribution the card does
#  not have, and `classify` reports it rather than guessing.
CURRENT_SINKS = """ids_v idsgen_v igidl_v igisl_v igidlb igislb Iii igcs_v
 igcd_v igs_v igd_v igbinv_v igbacc_v igbs_v igbd_v Ies Ied gdpr gspr gvs_d
 gvs_s gcrg gtau xdpart Rdrain Rsource Rdsi grgeltd""".split()
CHARGE_SINKS = """qg_v qd_v qs_v qb_v qinv qgs_parasitic qgd_parasitic qgs_fr
 qgd_fr qds_fr qbov qbov_s Qes Qed Qeg qg_acc qb_acc""".split()

#  this project's card, so a caller that only wants the answer can get it
CARD_SWITCHES = {
    "bulkmod": 0, "geomod": 5, "cgeo1sw": 0, "rdsmod": 0, "hvmod": 0,
    "asymmod": 0, "cvmod": 1, "igcmod": 0, "igbmod": 0, "gidlmod": 0,
    "iimod": 0, "tnoimod": 0, "nqsmod": 0, "shmod": 0, "tempmod": 0,
    "rgatemod": 0, "rgeomod": 0, "cgeomod": 0, "fnmod": 0, "cryomod": 0,
    "sh_warn": 0, "igclamp": 1, "sdterm": 0, "subbandmod": 0, "type": 1,
}


# --------------------------------------------------------------------- input
def _read(path):
    fh = open(path)
    try:
        return fh.read()
    finally:
        fh.close()


def strip_comments(text):
    out = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
        elif c == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
        elif c == '"':
            i += 1
            while i < n and text[i] != '"':
                i += 1
            i += 1
            out.append(" ")
        else:
            out.append(c)
            i += 1
    return "".join(out)


def split_statements(text):
    """One statement, or one block keyword, per entry, in source order.

    Lines are never joined. Every statement in `bsimcmg_body.include` fits on
    one physical line -- checked: not one line of the 3659 has unbalanced
    parentheses -- and the macro calls carry NO semicolon, so joining lines
    would run `binning(A, a, ...)` and `binning(B, b, ...)` together into one
    statement whose left hand side is A and whose right hand side contains
    b. That single mistake makes every parameter look like it reaches
    everything, and it is the reason this function works a line at a time.
    """
    out = []
    for raw in strip_comments(text).split("\n"):
        s = raw.strip()
        if not s:
            continue
        parts, depth, buf = [], 0, []
        for ch in s:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            if ch == ";" and depth == 0:
                buf.append(ch)
                parts.append("".join(buf))
                buf = []
            else:
                buf.append(ch)
        if buf:
            parts.append("".join(buf))
        for p in parts:
            rest = p.strip()
            if not rest:
                continue
            while True:
                m = re.match(r"^(begin|end|else|endcase|endfunction)"
                             r"(?![A-Za-z_0-9])\s*", rest)
                if not m:
                    break
                out.append(m.group(1))
                rest = rest[m.end():]
            if rest:
                tail = None
                m = re.search(r"\s*begin\s*$", rest)
                if m:
                    tail = "begin"
                    rest = rest[:m.start()]
                if rest.strip():
                    out.append(rest.strip())
                if tail:
                    out.append(tail)
    return out


def parameters(src_dir):
    """Every name the model declares as a parameter, in declaration order."""
    txt = strip_comments(_read(os.path.join(src_dir,
                                            "bsimcmg_parameters.include")))
    names, seen = [], set()
    for m in re.finditer(r"`MP[RI][A-Za-z0-9_]*\s*\(\s*"
                         r"([A-Za-z_][A-Za-z_0-9]*)\s*,", txt):
        nm = m.group(1)
        if nm not in seen:
            seen.add(nm)
            names.append(nm)
    return names


def tokenise(src_dir):
    txt = _read(os.path.join(src_dir, "bsimcmg_body.include"))
    txt = txt.replace('`include "bsimcmg_checking.include"', "")
    toks, skip = [], False
    for s in split_statements(txt):
        #  the Verilog-A helper functions (lexp, hypsmooth, ...) take no
        #  parameters, so their bodies cannot carry one
        if re.match(r"^analog\s+function\b", s):
            skip = True
            continue
        if skip:
            if s == "endfunction":
                skip = False
            continue
        if s == "begin":
            toks.append(("open", s))
        elif s == "end":
            toks.append(("close", s))
        elif s == "else":
            toks.append(("else", s))
        elif s in ("endcase", "endfunction"):
            toks.append(("endcase", s))
        else:
            s2 = s.rstrip(";").strip()
            if re.match(r"^if\s*\(", s2):
                toks.append(("if", s2))
            elif re.match(r"^(case|casex|casez)\s*\(", s2):
                toks.append(("case", s2))
            elif re.match(r"^(for|while|repeat)\s*\(", s2):
                toks.append(("if", s2))
            elif re.match(r"^[^=<>!]*:$", s2) and len(s2) < 60:
                toks.append(("label", s2))
            else:
                toks.append(("stmt", s2))
    return toks


# ------------------------------------------------------------------- parsing
def parse(toks):
    """Token list -> nested blocks, so if / else arms are real arms."""
    pos, n = [0], len(toks)

    def block():
        body = []
        while pos[0] < n:
            kind, text = toks[pos[0]]
            if kind in ("close", "else", "endcase"):
                return body
            if kind == "open":
                pos[0] += 1
                body.extend(block())
                if pos[0] < n and toks[pos[0]][0] == "close":
                    pos[0] += 1
                continue
            if kind == "if":
                body.append(cond_chain())
                continue
            if kind == "case":
                body.append(case_stmt())
                continue
            pos[0] += 1
            body.append(("stmt", text))
        return body

    def arm():
        if pos[0] < n and toks[pos[0]][0] == "open":
            pos[0] += 1
            b = block()
            if pos[0] < n and toks[pos[0]][0] == "close":
                pos[0] += 1
            return b
        if pos[0] < n:
            kind, text = toks[pos[0]]
            if kind == "if":
                return [cond_chain()]
            if kind == "case":
                return [case_stmt()]
            pos[0] += 1
            return [("stmt", text)]
        return []

    def cond_chain():
        branches = []
        cond = toks[pos[0]][1]
        pos[0] += 1
        branches.append((cond, arm()))
        while pos[0] < n and toks[pos[0]][0] == "else":
            pos[0] += 1
            if pos[0] < n and toks[pos[0]][0] == "if":
                c = toks[pos[0]][1]
                pos[0] += 1
                branches.append((c, arm()))
            else:
                branches.append((None, arm()))
                break
        return ("cond", branches)

    def case_stmt():
        ctrl = toks[pos[0]][1]
        pos[0] += 1
        arms = []
        while pos[0] < n and toks[pos[0]][0] != "endcase":
            kind, text = toks[pos[0]]
            if kind == "label":
                pos[0] += 1
                arms.append((text.rstrip(":").strip(), arm()))
            elif kind == "open":
                arms.append((None, arm()))
            else:
                pos[0] += 1
        if pos[0] < n:
            pos[0] += 1
        return ("case", ctrl, arms)

    return block()


# -------------------------------------------------------- switch evaluation
_CMP = re.compile(r"^\s*([A-Za-z_][A-Za-z_0-9]*)\s*(==|!=|<=|>=|<|>)\s*"
                  r"(-?\d+)\s*$")


def _eval_expr(e, sw):
    e = e.strip()
    while e.startswith("(") and e.endswith(")"):
        depth, whole = 0, True
        for i, c in enumerate(e):
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0 and i != len(e) - 1:
                    whole = False
                    break
        if not whole:
            break
        e = e[1:-1].strip()

    def _or(a, b):
        if a is True or b is True:
            return True
        if a is False and b is False:
            return False
        return None

    def _and(a, b):
        if a is False or b is False:
            return False
        if a is True and b is True:
            return True
        return None

    for op, fn in (("||", _or), ("&&", _and)):
        depth = 0
        for i in range(len(e) - 1):
            c = e[i]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            elif depth == 0 and e[i:i + 2] == op:
                return fn(_eval_expr(e[:i], sw), _eval_expr(e[i + 2:], sw))
    m = _CMP.match(e)
    if m:
        nm, op, lit = m.group(1), m.group(2), int(m.group(3))
        if nm not in sw:
            return None
        v = sw[nm]
        return {"==": v == lit, "!=": v != lit, "<=": v <= lit,
                ">=": v >= lit, "<": v < lit, ">": v > lit}[op]
    m = re.match(r"^([A-Za-z_][A-Za-z_0-9]*)$", e)
    if m and m.group(1) in sw:
        return sw[m.group(1)] != 0
    return None


def eval_cond(text, sw):
    """True, False, or None when the switches do not settle it."""
    m = re.match(r"^(?:if|while)\s*\((.*)\)$", text.strip())
    if not m:
        return None
    return _eval_expr(m.group(1), sw)


def eval_case(ctrl_text, label_text, sw):
    m = re.match(r"^(?:case|casex|casez)\s*\((.*)\)$", ctrl_text.strip())
    if not m:
        return None
    nm = m.group(1).strip()
    if nm not in sw:
        return None
    if label_text is None or label_text == "default":
        return "default"
    try:
        return sw[nm] == int(label_text)
    except ValueError:
        return None


# ------------------------------------------------------------------ walking
def _ids(text):
    return [x for x in ID.findall(text) if x not in KEYWORDS]


def _deps(env, ids):
    acc = set()
    for i in ids:
        d = env.get(i)
        if d:
            acc |= d
    return frozenset(acc)


def _join(a, b):
    out = dict(a)
    for k, v in b.items():
        out[k] = frozenset(out[k] | v) if k in out else v
    return out


def _run(block, env, sw):
    written = set()
    for node in block:
        if node[0] == "stmt":
            text = node[1]
            m = re.match(r"^`([A-Za-z_][A-Za-z_0-9]*)\s*\((.*)\)$", text)
            if m and m.group(1) != "include":
                ids = _ids(m.group(2))
                if ids:
                    lhs = ids[0]
                    #  a macro may read its own target (`length_scaling` does
                    #  X = X + ...), so its history is kept
                    env[lhs] = frozenset(_deps(env, ids)
                                         | env.get(lhs, frozenset()))
                    written.add(lhs)
                continue
            m = re.match(r"^([A-Za-z_][A-Za-z_0-9]*)\s*=\s*([^=].*)$", text)
            if m and m.group(1) not in KEYWORDS:
                lhs = m.group(1)
                env[lhs] = _deps(env, _ids(m.group(2)))
                written.add(lhs)
            continue

        if node[0] == "cond":
            branches = node[1]
            live, certain = [], False
            for cond, body in branches:
                v = True if cond is None else eval_cond(cond, sw)
                if v is False:
                    continue
                live.append((v, body))
                if v is True:
                    certain = True
                    break
            if not live:
                continue
            if certain and len(live) == 1:
                written |= _run(live[0][1], env, sw)
                continue
            entry = dict(env)
            outs, ws = [], []
            for _v, body in live:
                e2 = dict(entry)
                ws.append(_run(body, e2, sw))
                outs.append(e2)
            acc = dict(entry)
            for o in outs:
                acc = _join(acc, o)
            if any(c is None for c, _b in branches) and len(live) == len(branches):
                allw = set(ws[0])
                for w in ws[1:]:
                    allw &= w
                for v in allw:
                    u = set()
                    for o in outs:
                        if v in o:
                            u |= o[v]
                    acc[v] = frozenset(u)
            env.clear()
            env.update(acc)
            for w in ws:
                written |= w
            continue

        if node[0] == "case":
            ctrl, arms = node[1], node[2]
            live, exact = [], None
            for label, body in arms:
                r = eval_case(ctrl, label, sw)
                if r is True:
                    exact = (label, body)
                if r is False:
                    continue
                live.append((label, body))
            if exact is not None:
                written |= _run(exact[1], env, sw)
                continue
            if not live:
                continue
            entry = dict(env)
            outs, ws = [], []
            for _label, body in live:
                e2 = dict(entry)
                ws.append(_run(body, e2, sw))
                outs.append(e2)
            acc = dict(entry)
            for o in outs:
                acc = _join(acc, o)
            env.clear()
            env.update(acc)
            for w in ws:
                written |= w
    return written


# ---------------------------------------------------------------- the answer
def classify(src_dir, switches=None, watch=None):
    """Which parameters can reach the current, the charge, both, neither.

    Returns a dict with the four name sets, the variable environment, the
    contributions this card does not have, and the parameter list.
    """
    sw = dict(CARD_SWITCHES)
    if switches:
        sw.update(switches)
    params = parameters(src_dir)
    pset = set(params)
    env = {}
    for p in params:
        env[p] = frozenset([p])
    _run(parse(tokenise(src_dir)), env, sw)

    cur, chg, absent = set(), set(), []
    for s in CURRENT_SINKS:
        d = env.get(s)
        if d is None:
            absent.append(("current", s))
        else:
            cur |= d
    for s in CHARGE_SINKS:
        d = env.get(s)
        if d is None:
            absent.append(("charge", s))
        else:
            chg |= d
    cur &= pset
    chg &= pset
    out = {"params": params, "switches": sw, "env": env, "absent": absent,
           "reaches_current": cur, "reaches_charge": chg,
           "charge_only": chg - cur, "current_only": cur - chg,
           "both": cur & chg, "neither": pset - cur - chg}
    if watch:
        out["watch"] = [s for s in CURRENT_SINKS
                        if watch in env.get(s, frozenset())]
    return out


# ---------------------------------------------------- the shipped conclusion
TABLE_FILE = "depgraph_bsimcmg_112.json"


def table_path(root=None, variant=None):
    name = TABLE_FILE if not variant else (
        TABLE_FILE.replace(".json", "_%s.json" % variant))
    return os.path.join(root or os.path.dirname(os.path.abspath(__file__)),
                        name)


def load(root=None, variant=None):
    """The frozen answer for this project's card.

    The run does not need the Verilog-A source on the server: `classify` is
    run once where the source is, and its answer is shipped next to this
    file. `rebuild` regenerates it when the model version changes.
    """
    path = table_path(root, variant)
    if not os.path.isfile(path):
        return None
    fh = open(path)
    try:
        return json.load(fh)
    finally:
        fh.close()


def rebuild(src_dir, switches=None, root=None, extra_switch_sets=None,
            variant=None):
    r = classify(src_dir, switches)
    out = {
        "model": "BSIM-CMG 112.1.0",
        "source": "bsimcmg_body.include, bsimcmg_parameters.include",
        "switches": r["switches"],
        "n_parameters": len(r["params"]),
        "charge_only": sorted(r["charge_only"]),
        "current_only": sorted(r["current_only"]),
        "both": sorted(r["both"]),
        "neither": sorted(r["neither"]),
        "absent_contributions": ["%s:%s" % (a, b) for a, b in r["absent"]],
        "by_switch": {},
    }
    for name, chg in (extra_switch_sets or {}).items():
        sw = dict(r["switches"])
        sw.update(chg)
        r2 = classify(src_dir, sw)
        out["by_switch"][name] = {
            "change": chg,
            "n_reaches_current": len(r2["reaches_current"]),
            "gained_current": sorted(r2["reaches_current"]
                                     - r["reaches_current"]),
            "lost_current": sorted(r["reaches_current"]
                                   - r2["reaches_current"]),
        }
    path = table_path(root, variant)
    fh = open(path, "w")
    try:
        json.dump(out, fh, indent=1, sort_keys=True)
    finally:
        fh.close()
    return out


def verdict(name, table=None):
    t = table or load()
    if not t:
        return "unknown"
    for k in ("charge_only", "current_only", "both", "neither"):
        if name in t.get(k) or []:
            return k
    return "not a parameter"


def free_names(table=None, card=None):
    """Charge-only names, optionally cut down to what is on a card."""
    t = table or load()
    if not t:
        return []
    names = list(t.get("charge_only") or [])
    if card is not None:
        names = [n for n in names if n in card]
    return sorted(names)


def verify(curves_before, curves_after, iv_names, rel_tol=1.0e-9):
    """Did this parameter really leave every current sweep alone?

    A reading of the source is a reading. This is the measurement, and it is
    what a stage is allowed to lean on.
    """
    worst, where = 0.0, None
    for nm in iv_names:
        a = (curves_before or {}).get(nm)
        b = (curves_after or {}).get(nm)
        if a is None or b is None:
            return {"free": False, "worst_rel": None, "where": nm,
                    "missing": True}
        ya, yb = a[1], b[1]
        if len(ya) != len(yb):
            return {"free": False, "worst_rel": None, "where": nm,
                    "ragged": True}
        for u, v in zip(ya, yb):
            den = max(abs(u), 1.0e-30)
            rel = abs(v - u) / den
            if rel > worst:
                worst, where = rel, nm
    return {"free": bool(worst <= rel_tol), "worst_rel": worst,
            "where": where}
