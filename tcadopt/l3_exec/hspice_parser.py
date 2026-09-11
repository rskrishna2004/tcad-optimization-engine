"""l3_exec.hspice_parser -- read HSPICE results into curves.

WHY THIS EXISTS
---------------
TCADOpt's only result parser is `optimizer/plt_parser.py`, which reads the
DF-ISE `.plt` files a TCAD device solver writes. Compact-model fitting runs
HSPICE instead, so the engine had no way to see its own model's output.

WHAT IT PARSES, AND WHY THAT CHOICE
-----------------------------------
It reads the **`.print` tables inside the `.lis` listing file**, not the binary
or ASCII `.sw0` sweep file.

That is a deliberate decision. A `.print` table is self-describing: it carries
its own column headers, so the parser learns the column layout from the file
itself and needs no knowledge of any vendor's byte layout. The `.sw0` format,
by contrast, is a fixed-field vendor format whose exact layout would have to be
taken on faith unless it is checked against the manual. We do not take file
formats on faith here, so `.sw0` support is deliberately absent rather than
guessed at.

Numbers in a `.lis` table come in two spellings and both are handled:

    2.8979e-12          scientific
    2.8979p             standard SPICE engineering suffix

The suffix table below is the standard SPICE scale-factor set. Note the two
that trip people up: `x` (and `meg`) mean 1e6, while a bare `m` means 1e-3.

USE
---
    curves = parse_lis("run.lis")
    # -> {"dc_0": {"x": array, "v(g)": array, "i(vd)": array}, ...}

    vg, idd = sweep_columns(curves, x_hint="v(g)", y_hint="i(vd)")
"""
import os
import re

import numpy as np

# Standard SPICE scale factors. 'meg' and 'x' are 1e6; a bare 'm' is 1e-3.
_SUFFIX = {
    "t": 1e12, "g": 1e9, "meg": 1e6, "x": 1e6, "k": 1e3,
    "m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12, "f": 1e-15, "a": 1e-18,
}
_NUM = re.compile(
    r"^[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?(meg|[tgxkmunpfa])?$", re.I)

# HSPICE prints 1e30 as the "no value" / end-of-data sentinel.
_SENTINEL = 1e29


def spice_float(tok):
    """One SPICE-spelled number -> float, or None if the token is not a number.

    Accepts '2.8979e-12', '2.8979p', '-1.5meg', '3', '.5n'. Returns None for
    anything else so a header cell never silently becomes a data point.
    """
    tok = tok.strip().rstrip(",")
    if not tok:
        return None
    m = _NUM.match(tok)
    if not m:
        return None
    suf = m.group(1)
    if suf:
        base = tok[: -len(suf)]
        try:
            return float(base) * _SUFFIX[suf.lower()]
        except (ValueError, KeyError):
            return None
    try:
        return float(tok)
    except ValueError:
        return None


def _is_data_row(tokens):
    """A data row is >= 2 tokens and EVERY token parses as a number."""
    if len(tokens) < 2:
        return False
    return all(spice_float(t) is not None for t in tokens)


def _is_header_row(tokens):
    """A header row is >= 2 tokens, none of which parse as a number, and at
    least one of which looks like a SPICE output name -- v(...), i(...), a
    sweep variable, or a .measure name."""
    if len(tokens) < 2:
        return False
    if any(spice_float(t) is not None for t in tokens):
        return False
    joined = " ".join(tokens).lower()
    return bool(re.search(r"\b[vi]\s*\(|\bvolts\b|\bsweep\b|\bx\b|\bpar\(",
                          joined)) or len(tokens) >= 2


def parse_lis(path):
    """Parse every `.print` table in an HSPICE `.lis` file.

    Returns {block_name: {column_name: numpy array}}. Blocks are named
    'dc_0', 'dc_1', ... in the order they appear. A sweep that HSPICE splits
    across several printed pages is stitched back into ONE block as long as
    the repeated page header has identical column names, which is what makes
    a long sweep come back whole instead of in fragments.
    """
    if not os.path.exists(path):
        raise IOError("no such HSPICE listing: %s" % path)
    with open(path, "r", errors="replace") as fh:
        lines = fh.read().splitlines()

    blocks = []           # [(cols, {col: [vals]})]
    cur_cols, cur_data = None, None

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            continue
        low = line.strip().lower()
        # page furniture and banners never carry data
        if low.startswith(("*", "$", "1***", "***", "hspice", "lic:")):
            continue
        toks = line.split()

        if _is_data_row(toks):
            if cur_cols is None:
                continue                     # numbers before any header: skip
            if len(toks) != len(cur_cols):
                continue                     # ragged line: not this table
            vals = [spice_float(t) for t in toks]
            if any(v is None or abs(v) > _SENTINEL for v in vals):
                continue                     # 1e30 end-of-data marker row
            for c, v in zip(cur_cols, vals):
                cur_data[c].append(v)
            continue

        if _is_header_row(toks):
            cols = [t.lower() for t in toks]
            if cur_cols is not None and cols == cur_cols:
                continue                     # repeated page header: same table
            if cur_cols is not None and cur_data and \
                    len(next(iter(cur_data.values()))) > 0:
                blocks.append((cur_cols, cur_data))
            cur_cols = cols
            cur_data = dict((c, []) for c in cols)

    if cur_cols is not None and cur_data and \
            len(next(iter(cur_data.values()))) > 0:
        blocks.append((cur_cols, cur_data))

    out = {}
    for i, (cols, data) in enumerate(blocks):
        out["dc_%d" % i] = dict((c, np.asarray(v, float))
                                for c, v in data.items())
    return out


def _pick(cols, hint, fallbacks=()):
    """Choose a column by exact name, then substring, then a fallback list."""
    if hint:
        h = hint.lower()
        if h in cols:
            return h
        for c in cols:
            if h in c:
                return c
    for f in fallbacks:
        for c in cols:
            if f in c:
                return c
    return None


def sweep_columns(curves, x_hint=None, y_hint=None, block=None):
    """Pull one (x, y) sweep out of a parsed listing.

    x defaults to the swept variable ('x', 'sweep', 'volts', or the first
    column); y defaults to the first current column. Returns (x, y) as arrays
    sorted by x with duplicate x removed -- the same strictly-increasing-x
    hygiene the TCAD path needs, applied here at the source.
    """
    if not curves:
        raise ValueError("no printed tables found in the listing")
    key = block or sorted(curves)[0]
    tab = curves[key]
    cols = list(tab)
    xc = _pick(cols, x_hint, ("x", "sweep", "volts", "v(g)", "v(d)"))
    if xc is None:
        xc = cols[0]
    yc = _pick(cols, y_hint, ("i(", "current"))
    if yc is None:
        yc = [c for c in cols if c != xc][0]
    x, y = np.asarray(tab[xc], float), np.asarray(tab[yc], float)
    o = np.argsort(x)
    x, y = x[o], y[o]
    keep = np.concatenate(([True], np.diff(x) > 1e-12))
    return x[keep], y[keep]


def parse_measures(path):
    """Read `.measure` results out of a `.lis`.

    Lines look like:  vth   =  3.7000E-01  targ= ...
    Returns {name: value}. Used for cheap scalar checks (Vt, Ion, Ioff)
    alongside the full curve.
    """
    out = {}
    if not os.path.exists(path):
        return out
    pat = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*([-+0-9.eE]+\w?)\s")
    with open(path, "r", errors="replace") as fh:
        for line in fh:
            m = pat.match(line)
            if not m:
                continue
            v = spice_float(m.group(2))
            if v is not None and abs(v) < _SENTINEL:
                out[m.group(1).lower()] = v
    return out


def has_error(path):
    """(errored, first_error_line). HSPICE reports fatal problems with
    '**error**'; a run that produced a table but also an error is not trusted."""
    if not os.path.exists(path):
        return True, "listing file absent"
    with open(path, "r", errors="replace") as fh:
        for line in fh:
            low = line.lower()
            if "**error**" in low or "**fatal**" in low:
                return True, line.strip()
    return False, ""
