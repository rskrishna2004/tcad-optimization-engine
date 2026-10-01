"""l3_exec.hspice_parser -- read HSPICE results into curves.

WHY THIS EXISTS
---------------
TCADOpt's only result parser is `optimizer/plt_parser.py`, which reads the
DF-ISE `.plt` files a TCAD device solver writes. Compact-model fitting runs
HSPICE instead, so the engine had no way to see its own model's output.

WHAT IT PARSES, AND WHY THAT CHOICE
-----------------------------------
It reads the **`.print` tables inside the `.lis` listing file**, not the binary
or ASCII `.sw0` sweep file. A `.print` table is self-describing; a `.sw0` is a
fixed-field vendor format whose layout would have to be taken on faith.

THE ACTUAL FORMAT, TAKEN FROM A REAL LISTING
--------------------------------------------
This is not a guess. It is copied from a run of `t4_gaa.sp` on
PrimeSim HSPICE U-2023.03, which is the build this project uses:

     ****** dc transfer curves tnom=  25.000 temp=  25.000 ******
    x
    <blank>
     volt         current    voltage
                 m1         ng
        0.          1.4250p    0.
       10.00000m    2.0888p   10.0000m
       ...
      600.00000m   47.2826u  600.0000m
    y

Four features matter, and the first version of this parser got all four wrong:

1. **A bare `x` on its own line OPENS the table and a bare `y` CLOSES it.**
   These are the reliable delimiters. Everything between them is the table.

2. **There are TWO header lines, not one.** The first gives the physical
   QUANTITY of each column (`volt`, `current`, `voltage`); the second gives the
   NAME of each printed output (`m1`, `ng`).

3. **The name row is one entry SHORT**, because the swept variable -- the first
   column -- is unnamed. So `len(names) == len(units) - 1` is the normal case
   and the sweep column is synthesised as `x`.

4. **The names lose their wrapper.** `.print dc i(M1) v(ng)` comes back as
   `m1` and `ng`, not `i(m1)` and `v(ng)`. So a column cannot reliably be found
   by the name you asked for -- which is why `sweep_columns` matches against
   the QUANTITY row too. Asking for a current finds the column whose quantity
   is `current`, whatever HSPICE decided to call it.

THE AC LISTING IS A DIFFERENT SHAPE AGAIN, AND IT COST US A WHOLE STEP
---------------------------------------------------------------------
A `.print ac` table on the same build looks like this -- copied verbatim from
`p1_cv_B_prim.lis`, the first AC listing this project ever produced:

      ****** ac analysis tnom=  25.000 temp=  27.000 ******
       *** parameter 0:vg  =  -200.0000m       ***

    x

     freq         i real     i imag
                 vg         vg
        1.00000x    0.      -356.9422p
    y

Two things here break the DC assumptions above, and both broke this parser:

5. **A quantity can be TWO WORDS.** `i real` and `i imag` split into four
   tokens against three data columns, so the token-count rules in point 3
   matched nothing and every data row was discarded as ragged. The table came
   back EMPTY -- not wrong, empty -- and the run was scored as a failure.
   The fix does not guess: when the token counts do not line up, the column
   boundaries are taken from the CHARACTER POSITIONS of the numbers in the
   data row, and the two header rows are sliced at those same positions. The
   listing is fixed-width, so this is reading the format rather than inferring
   it.

6. **The swept variable is not a column at all.** In a nested
   `.ac ... sweep vg ...` HSPICE emits ONE TABLE PER GATE BIAS, each with a
   single data row, and puts the bias in a `*** parameter 0:vg = ... ***`
   line ABOVE the table. The `x` column holds frequency, which is constant.
   So the tables are stitched (their headers are identical) and the bias line
   is captured and re-attached as a real column named after the parameter --
   `vg` here. Without that the C-V curve has no voltage axis.

Numbers come in two spellings and both are handled:

    2.8979e-12          scientific
    2.8979p             standard SPICE engineering suffix

Note the two that trip people up: `x` and `meg` mean 1e6, a bare `m` is 1e-3.

USE
---
    curves = parse_lis("run.lis")
    # -> {"dc_0": {"_units": [...], "x": array, "m1": array, "ng": array}}

    vg, idd = sweep_columns(curves, x_hint="volt", y_hint="current")
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


def _spans(line):
    """Character spans of the whitespace-separated tokens in `line`."""
    out, i, n = [], 0, len(line)
    while i < n:
        while i < n and line[i].isspace():
            i += 1
        if i >= n:
            break
        j = i
        while j < n and not line[j].isspace():
            j += 1
        out.append((i, j))
        i = j
    return out


def _headers_by_position(units_line, names_line, data_line):
    """Split two header rows using the DATA row's column positions.

    HSPICE listings are fixed-width, so when a quantity is two words -- `i real`,
    `i imag` -- counting tokens fails but character positions do not.

    The rule is NEAREST CENTRE: every header word is assigned to the data column
    whose number's centre is closest to that word's centre, and the words landing
    on one column are joined with a space. Measured against the real AC table in
    `p1_cv_B_prim.lis`, whose columns sit at character centres 8.0 / 17.0 / 29.0:

        units  freq(3) i(14.5) real(18) i(25.5) imag(29) -> 'freq' 'i real' 'i imag'
        names          vg(14.0)         vg(25.0)         -> ''     'vg'     'vg'

    and against the DC table, which the token-count path already handles, so the
    two agree where both apply. Returns (units, names) sized to the data row, or
    (None, None) if the data row has no tokens.
    """
    dspans = _spans(data_line)
    if not dspans:
        return None, None
    centres = [(a + b) / 2.0 for a, b in dspans]

    def assign(row):
        cells = [[] for _ in centres]
        if row is None:
            return ["" for _ in centres]
        for a, b in _spans(row):
            c = (a + b) / 2.0
            k = min(range(len(centres)), key=lambda j: abs(centres[j] - c))
            cells[k].append(row[a:b])
        return [" ".join(x).strip().lower() for x in cells]

    return assign(units_line), assign(names_line)


def _uniquify(names):
    """Column keys must be unique -- an AC table names two columns `vg`."""
    seen, out = {}, []
    for n in names:
        n = n or "c"
        if n in seen:
            seen[n] += 1
            out.append("%s#%d" % (n, seen[n]))
        else:
            seen[n] = 1
            out.append(n)
    return out


_PARAM_LINE = re.compile(
    r"\*\*\*\s*parameter\s+(?:\d+:)?([A-Za-z_]\w*)\s*=\s*(\S+)\s*\*\*\*")


def _is_data_row(tokens):
    """A data row is >= 2 tokens and EVERY token parses as a number."""
    if len(tokens) < 2:
        return False
    return all(spice_float(t) is not None for t in tokens)


def _all_words(tokens):
    """True when no token parses as a number -- i.e. this could be a header."""
    return bool(tokens) and all(spice_float(t) is None for t in tokens)


def _merge_split_tables(blocks):
    """Put back together what HSPICE's printed-page layout took apart.

    THE FAULT THIS FIXES COST STEP 19 ITS ENTIRE RUN
    ------------------------------------------------
    HSPICE prints AT MOST FOUR DATA COLUMNS per table. Ask for more and it
    silently splits the request across several tables, one after another,
    under the SAME bias heading. Copied verbatim from `cv_listing.lis`,
    the Step-19 run, at the first gate bias:

         ****** ac analysis tnom=  25.000 temp=  26.850 ******
          *** parameter 0:vg  =  -200.0000m       ***
        x
         freq         i real     i imag     i real     i imag
                     vg         vg         vd         vd
            1.00000x    0.      -190.2367p  -85.4327f   94.2630p
        y
        x
         freq         i real     i imag     i real     i imag
                     vs         vs         ve         ve
            1.00000x   85.4327f   94.2630p    0.         1.7107p
        y

    Two tables, one bias. Up to v1.1.16 the stitcher joined two tables only
    when their column lists were IDENTICAL, so these two were filed as
    separate blocks; 91 biases became 182 one-row blocks; the C-V curve came
    back as a single point and was rejected; and every stage that needed a
    C-V residual crashed or rolled back.

    THE RULE, AND WHY IT CANNOT MISFIRE
    -----------------------------------
    Two consecutive tables are merged SIDE BY SIDE only when all four hold:

      * they carry the same `*** parameter ... ***` heading, VALUE INCLUDED
        -- so two different biases can never be glued into one row;
      * that heading is not None -- a plain DC sweep has none, so a DC
        listing is untouched and every earlier result reproduces exactly;
      * their column names are DIFFERENT -- identical columns mean a long
        table continued on a new page, which is the vertical case below;
      * they have the same number of rows -- side-by-side only makes sense
        for tables that describe the same rows.

    After that, consecutive tables with identical columns are stacked
    VERTICALLY, which is the original v1.1.0 behaviour and is what turns 91
    one-row bias tables into one 91-row sweep.

    Columns already present are not overwritten: `freq` appears in both
    halves with the same value, and the first one wins.
    """
    # --- pass 1: side by side, within one bias ----------------------------
    merged = []
    for cols, units, data, param in blocks:
        if merged:
            pc, pu, pd, pp = merged[-1]
            nrows_prev = len(next(iter(pd.values())))
            nrows_this = len(next(iter(data.values())))
            if (param is not None and pp is not None and param == pp
                    and pc != cols and nrows_prev == nrows_this):
                for i, c in enumerate(cols):
                    if c in pd:
                        continue
                    pd[c] = list(data[c])
                    pc.append(c)
                    pu.append(units[i] if i < len(units) else "")
                continue
        merged.append((list(cols), list(units), dict(data), param))

    # --- pass 2: stacked, across biases (v1.1.0 behaviour) ----------------
    out = []
    for cols, units, data, param in merged:
        if out and out[-1][0] == cols:
            for c in cols:
                out[-1][2][c].extend(data[c])
            continue
        out.append((list(cols), list(units), dict(data), param))
    return out


def parse_lis(path):
    """Parse every `.print` table in an HSPICE `.lis` file.

    Returns {block_name: {column_name: numpy array}}, plus a `_units` entry per
    block giving the quantity row verbatim. Blocks are named 'dc_0', 'dc_1', ...
    in the order they appear.

    The state machine follows the format documented at the top of this module:
    a bare `x` opens a table, two header lines follow, data runs until a bare
    `y`. A table that HSPICE splits across printed pages is stitched back into
    ONE block when the repeated headers are identical, which is what makes a
    long sweep come back whole instead of in fragments.
    """
    if not os.path.exists(path):
        raise IOError("no such HSPICE listing: %s" % path)
    with open(path, "r", errors="replace") as fh:
        lines = fh.read().splitlines()

    blocks = []                 # [(cols, units, {col: [vals]}, param)]
    state = "idle"              # idle -> units -> names -> data
    cols = units = data = None
    units_line = names_line = None
    pending_param = None        # ('vg', -0.2) from a '*** parameter ... ***' line
    block_param = None

    def flush():
        if cols and data and len(next(iter(data.values()))) > 0:
            blocks.append((list(cols), list(units or []), dict(data),
                           block_param))

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        low = stripped.lower()

        # A nested `.ac ... sweep vg ...` emits one table per bias and writes
        # the bias here instead of in a column. Capture it; it becomes a real
        # column below, which is what gives a C-V curve its voltage axis.
        m = _PARAM_LINE.search(low)
        if m:
            v = spice_float(m.group(2))
            if v is not None:
                pending_param = (m.group(1).lower(), v)
            continue

        if state == "idle":
            if low == "x":
                state, cols, units, data = "units", None, None, None
                units_line = names_line = None
                block_param = pending_param
            continue

        if not stripped:
            continue

        if low == "y":                      # end of table
            flush()
            state, cols, units, data = "idle", None, None, None
            continue

        toks = stripped.split()

        if state == "units":
            if _all_words(toks):
                units = [t.lower() for t in toks]
                units_line = line
                state = "names"
            continue

        if state == "names":
            if _all_words(toks):
                names = [t.lower() for t in toks]
                names_line = line
                # The swept variable's column carries no name, so the name row
                # is normally one entry short. Synthesise 'x' for it.
                if len(names) == len(units) - 1:
                    cols = ["x"] + names
                elif len(names) == len(units):
                    cols = list(names)
                else:
                    # Token counts do not line up: a quantity is more than one
                    # word (`i real`, `i imag`). Do NOT guess -- defer until the
                    # first data row, whose character positions give the real
                    # column boundaries.
                    cols = None
                if cols is not None:
                    cols = _uniquify(cols)
                    data = dict((c, []) for c in cols)
                state = "data"
                continue
            # No second header line: the first one WAS the names row.
            cols = _uniquify(list(units))
            data = dict((c, []) for c in cols)
            state = "data"
            # fall through and let the data branch handle this same line

        if state == "data":
            if _is_data_row(toks):
                if cols is None:
                    # Resolve the header from THIS row's column positions.
                    u2, n2 = _headers_by_position(units_line, names_line, line)
                    if u2 is None:
                        continue
                    units = u2
                    cols = _uniquify([n or ("x" if i == 0 else u2[i])
                                      for i, n in enumerate(n2)])
                    data = dict((c, []) for c in cols)
                if len(toks) != len(cols):
                    continue                 # ragged line: not this table
                vals = [spice_float(t) for t in toks]
                if any(v is None or abs(v) > _SENTINEL for v in vals):
                    continue                 # the 1e30 end-of-data marker
                for c, v in zip(cols, vals):
                    data[c].append(v)
                if block_param is not None:
                    pn, pv = block_param
                    # Both printed columns of an AC table are named `vg`, so the
                    # swept parameter gets its own reserved prefix rather than
                    # silently appending into a column that already exists --
                    # which is exactly what produced 180 values for 90 rows the
                    # first time this was written.
                    key = "sweep_" + pn
                    if key not in data:
                        cols.append(key)
                        units = list(units) + [pn]
                        data[key] = []
                    data[key].append(pv)
            elif _all_words(toks):
                # a repeated page header inside the same table: ignore it
                continue

    flush()
    blocks = _merge_split_tables(blocks)

    out = {}
    for i, (c, u, d, _p) in enumerate(blocks):
        blk = dict((k, np.asarray(v, float)) for k, v in d.items())
        blk["_units"] = u
        out["dc_%d" % i] = blk
    return out


def _pick(cols, units, hint, fallbacks=()):
    """Choose a column by name, by quantity, then by a fallback list.

    HSPICE strips the wrapper from a printed name -- `.print dc i(M1)` comes
    back as `m1` -- so a caller asking for a current cannot find it by name.
    The quantity row is therefore searched too, and is the reliable route.
    """
    u = list(units or [])
    if hint:
        h = hint.lower()
        if h in cols:
            return h
        for i, c in enumerate(cols):          # quantity row: exact
            if i < len(u) and u[i] == h:
                return c
        for c in cols:                        # name: substring
            if h in c:
                return c
        for i, c in enumerate(cols):          # quantity row: substring
            if i < len(u) and h in u[i]:
                return c
    for f in fallbacks:
        for i, c in enumerate(cols):
            if f in c or (i < len(u) and f in u[i]):
                return c
    return None


def sweep_columns(curves, x_hint=None, y_hint=None, block=None):
    """Pull one (x, y) sweep out of a parsed listing.

    x defaults to the swept variable; y defaults to the first current column.
    Returns (x, y) sorted by x with duplicate x removed -- the same
    strictly-increasing-x hygiene the TCAD path needs, applied at the source.
    """
    if not curves:
        raise ValueError("no printed tables found in the listing")
    key = block or sorted(curves)[0]
    tab = curves[key]
    units = tab.get("_units", [])
    cols = [c for c in tab if c != "_units"]
    xc = _pick(cols, units, x_hint, ("x", "volt", "sweep"))
    if xc is None:
        xc = cols[0]
    yc = _pick(cols, units, y_hint, ("current", "i("))
    if yc is None or yc == xc:
        cand = [c for c in cols if c != xc]
        if not cand:
            raise ValueError("listing has only one column")
        yc = cand[0]
    x, y = np.asarray(tab[xc], float), np.asarray(tab[yc], float)
    o = np.argsort(x)
    x, y = x[o], y[o]
    keep = np.concatenate(([True], np.diff(x) > 1e-12))
    return x[keep], y[keep]


def cv_columns(curves, freq, block=None, tol_real=1.0e-3):
    """Turn an AC gate-admittance listing into (Vg, Cgg).

    THE PHYSICS, WRITTEN OUT, BECAUSE IT IS ONE SIGN AWAY FROM BEING WRONG
    ---------------------------------------------------------------------
    The deck drives the gate with `vg g 0 dc 0 ac 1` and AC-grounds every other
    terminal, so the gate sees the whole device: Cgg = Cgs + Cgd + Cgb.

    SPICE reports the branch current of a voltage source as the current flowing
    from its + node INTO the source. The + node here is `g`, so

        I(vg) = -I_into_the_gate
        I_into_the_gate = Y_gate * V = j*omega*Cgg * 1
        => Im(I(vg)) = -omega*Cgg
        => Cgg = -Im(I(vg)) / (2*pi*f)

    That sign is not asserted, it is MEASURED. On the real listing
    `p1_cv_B_prim.lis`, raising CFS by 1e-10 F/m raised this quantity by
    +1.20000e-17 F, and eq. 3.700 of the BSIM-CMG manual says the rise must be
    NFIN * Weff * dCFS = 1 * 120e-9 * 1e-10 = 1.2e-17 F. Same magnitude, same
    sign, five figures. A flipped sign would have come out negative.

    The real part is checked too: with IGCMOD = IGBMOD = 0 there is no gate
    conduction, so Re(I(vg)) must be zero. Anything above `tol_real` of the
    imaginary part means the gate is carrying real current and the extracted
    capacitance is not what it claims to be.

    Returns (vg, cgg). Works with either deck form -- `.print ac ir(vg) ii(vg)`
    (the arithmetic is done here) or `.print ac cgg=par(...)` (HSPICE already
    did it) -- and decides which by the QUANTITY row, never by position.
    """
    if not curves:
        raise ValueError("no printed tables found in the listing")
    key = block or sorted(curves)[0]
    tab = curves[key]
    units = [str(u).lower() for u in tab.get("_units", [])]
    cols = [c for c in tab if c != "_units"]

    # --- the gate-bias axis -------------------------------------------------
    xc = None
    for c in cols:
        if c.startswith("sweep_"):
            xc = c
            break
    if xc is None:
        xc = _pick(cols, units, "volt", ("x",))
    if xc is None:
        raise ValueError("no gate-bias column: an `.ac ... sweep vg` listing "
                         "carries the bias in a '*** parameter 0:vg = ... ***' "
                         "line, and this listing has none")

    # --- capacitance, already formed by HSPICE? -----------------------------
    for i, c in enumerate(cols):
        u = units[i] if i < len(units) else ""
        if c == "cgg" or "cap" in u or "farad" in u:
            v = np.asarray(tab[xc], float)
            y = np.asarray(tab[c], float)
            o = np.argsort(v)
            return v[o], y[o]

    # --- otherwise from the raw admittance ---------------------------------
    #
    # THE FIRST PAIR, NOT THE LAST.  (v1.1.16)
    #
    # Until v1.1.16 the C-V deck printed exactly one current -- the gate's --
    # so this loop could overwrite `im` on every match and still be right by
    # accident. v1.1.16's deck prints the whole gate row, so the table now
    # carries FOUR imaginary columns: vg, vd, vs, ve in that order. Keeping
    # the last one would have returned Cgb under the name Cgg, silently, and
    # every number after it would have been wrong while looking perfectly
    # reasonable. The gate is printed first by construction, so the first
    # pair is the gate.
    im = re_ = None
    for i, c in enumerate(cols):
        u = units[i] if i < len(units) else ""
        if ("imag" in u or "imag" in c) and im is None:
            im = c
        elif ("real" in u or "real" in c) and re_ is None:
            re_ = c
    if im is None:
        raise ValueError(
            "no imaginary-current column in the AC listing. Columns are %s "
            "with quantities %s. This parser will not guess a column: a wrong "
            "guess here produces a capacitance that looks plausible and is not."
            % (cols, units))

    v = np.asarray(tab[xc], float)
    y = -np.asarray(tab[im], float) / (2.0 * np.pi * float(freq))
    if re_ is not None:
        r = np.abs(np.asarray(tab[re_], float))
        m = np.abs(np.asarray(tab[im], float))
        bad = r > tol_real * np.maximum(m, 1e-30)
        if bad.any():
            raise ValueError(
                "Re(I(vg)) is not negligible at %d of %d bias points (max %.3e "
                "vs Im %.3e). With IGCMOD=IGBMOD=0 the gate carries no real "
                "current, so this is not a clean capacitance measurement."
                % (int(bad.sum()), len(r), float(r.max()), float(m.max())))
    o = np.argsort(v)
    return v[o], y[o]


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


# --------------------------------------------------------------------------
#  THE GATE ROW  (TCADOpt v1.1.16)
# --------------------------------------------------------------------------
_TERMINALS = (("cgg", "vg"), ("cgd", "vd"), ("cgs", "vs"), ("cgb", "ve"))


def cv_gate_row(curves, freq, block=None, tol_real=1.0e-3):
    """Cgg AND its three parts, from one AC listing.

    WHY THIS EXISTS
    ---------------
    Cgg is a sum: Cgg = Cgd + Cgs + Cgb. Eighteen steps of this project fitted
    the sum. The sum hides the only thing that matters for a drain-bias split,
    because the three parts behave completely differently when the drain
    moves. On this device's own TCAD reference, at Vg = 0.6 V, going from
    Vd = 50 mV to Vd = 0.6 V:

        Cgg  59.441 -> 45.135 aF   -24.1%
        Cgd  28.570 -> 14.426 aF   -49.5%    <- all of the change
        Cgs  29.465 -> 29.200 aF    -0.9%
        Cgb   1.406 ->  1.509 aF    +7.3%

    The deck drives the gate with `ac 1` and AC-grounds the other three
    terminals, so every branch current in that listing is a column of the
    device's capacitance matrix:

        I(vg) = -j*omega*Cgg      ->  Cgg = -Im(I(vg)) / (2*pi*f)
        I(vd) = +j*omega*Cgd      ->  Cgd = +Im(I(vd)) / (2*pi*f)

    The SIGNS are opposite and that is not a convention, it is Kirchhoff:
    the current the gate source pushes in has to come back out of the other
    three, so I(vg) + I(vd) + I(vs) + I(ve) = 0 and therefore
    Cgg = Cgd + Cgs + Cgb identically. The function RETURNS that residual as
    `closure_pct` so the identity can be checked rather than assumed -- the
    reference CSV carries the same check and reads 0.000002%.

    Returns {"vg":..., "cgg":..., "cgd":..., "cgs":..., "cgb":..., "closure_pct":...}
    or None when the listing has only the gate column (a pre-v1.1.16 deck).
    """
    if not curves:
        return None
    key = block or sorted(curves)[0]
    tab = curves[key]
    units = [str(u).lower() for u in tab.get("_units", [])]
    cols = [c for c in tab if c != "_units"]

    xc = None
    for c in cols:
        if c.startswith("sweep_"):
            xc = c
            break
    if xc is None:
        xc = _pick(cols, units, "volt", ("x",))
    if xc is None:
        return None

    # Pair up (real, imag) in printed order; the deck writes vg, vd, vs, ve.
    pairs, cur = [], {}
    for i, c in enumerate(cols):
        u = units[i] if i < len(units) else ""
        if "real" in u or "real" in c:
            cur = {"re": c}
        elif ("imag" in u or "imag" in c) and cur.get("re") is not None:
            cur["im"] = c
            pairs.append(cur)
            cur = {}
    if len(pairs) < len(_TERMINALS):
        return None

    w = 2.0 * np.pi * float(freq)
    v = np.asarray(tab[xc], float)
    o = np.argsort(v)
    out = {"vg": v[o]}
    for k, (name, _node) in enumerate(_TERMINALS):
        im = np.asarray(tab[pairs[k]["im"]], float)
        sign = -1.0 if name == "cgg" else +1.0
        out[name] = (sign * im / w)[o]
        re_ = pairs[k].get("re")
        if name == "cgg" and re_ is not None:
            r = np.abs(np.asarray(tab[re_], float))
            m = np.abs(im)
            bad = r > tol_real * np.maximum(m, 1e-30)
            if bad.any():
                raise ValueError(
                    "Re(I(vg)) is not negligible at %d of %d bias points"
                    % (int(bad.sum()), len(r)))
    tot = out["cgd"] + out["cgs"] + out["cgb"]
    den = np.maximum(np.abs(out["cgg"]), 1e-30)
    out["closure_pct"] = 100.0 * (tot - out["cgg"]) / den
    return out


# ==========================================================================
#  THE GATE ROW, FROM THE OPERATING-POINT PRINT   (TCADOpt v1.1.17)
# ==========================================================================
#
#  ROW AND COLUMN ARE NOT THE SAME MATRIX ENTRY, AND STEP 19 CONFUSED THEM
#  ----------------------------------------------------------------------
#  A four-terminal device has a 4x4 small-signal capacitance matrix. Two
#  different slices of it both get called "the gate row" in conversation and
#  they are NOT equal when Vds is not zero:
#
#     the gate ROW      Cgd = -dQg/dVd,  Cgs = -dQg/dVs,  Cgb = -dQg/dVb
#     the gate COLUMN   Cdg = -dQd/dVg,  Csg = -dQs/dVg,  Cbg = -dQb/dVg
#
#  Both sum to Cgg -- the row because the gate charge cannot depend on a
#  common shift of every terminal, the column because charge is conserved --
#  so a closure check passes for EITHER and cannot tell them apart.
#
#  `cv_gate_row` below drives the gate with `ac 1`, grounds the rest and reads
#  the three other branch currents. That measures the COLUMN.
#  This function reads HSPICE's own operating-point print, which gives the ROW.
#
#  MEASURED, on `cv_listing.lis` from the Step-19 run, at Vg = 0.6 V,
#  Vd = 50 mV, one card, one listing, the same bias:
#
#      column (AC)         Cgg 50.4987   Cdg 23.9544   Csg 26.2721   Cbg 0.2723
#      row    (op-point)   Cgg 50.4987   Cgd 16.3579   Cgs 33.8685   Cgb 0.2723
#
#  Same Cgg to six figures, same Cgb, and a drain/source split that differs by
#  7.6 aF. They are different numbers because they are different derivatives.
#
#  THE REFERENCE IS A ROW. `targets/cv_targets.csv` carries Cgd_F, Cgs_F and
#  Cgb_F as NEGATIVE numbers summing to -Cgg, which is the sign convention of
#  a capacitance-matrix ROW, and its saturation behaviour confirms it: at
#  Vd = 0.6 V the reference's intrinsic Cgd keeps 4.2% of its linear-region
#  value, which is what -dQg/dVd does at pinch-off. -dQd/dVg does not: a 40/60
#  partition keeps it near 40% of the intrinsic Cgg.
#
#  So this function -- not `cv_gate_row` -- is the instrument that matches the
#  reference data, and it needs NO DECK CHANGE AT ALL. `.option list node` is
#  already in every deck this project has ever written, and the blocks it
#  prints are present in the Step-17 and Step-18 listings too: 92 of them, in
#  every `.lis` we have kept. The measurement has been sitting in the output
#  of every C-V run since Step 1.
#
#  WHAT HSPICE PRINTS, VERBATIM
#  ----------------------------
#     *** source        0:vg =    6.000E-01 ***
#     ...
#     **** mosfets
#      subckt
#      element  0:m1
#      model    0:nch
#      region   Linear
#       id        16.0208u
#       vth      451.6203m
#       vdsat     29.8408m
#       gm        73.6375u
#       gds       89.5692u
#       cdtot     17.7194a
#       cgtot     50.4987a
#       cstot     27.6336a
#       cbtot    2.723e-19
#       cgs       33.8685a
#       cgd       16.3579a
#
#  and cgs + cgd + cbtot = 33.8685 + 16.3579 + 0.2723 = 50.4987 = cgtot,
#  exactly, at every one of the 91 biases. That identity is returned as
#  `closure_pct` so it is checked on every run instead of trusted.
# --------------------------------------------------------------------------

_OP_SOURCE = re.compile(
    r"\*\*\*\s*source\s+(?:\d+:)?([A-Za-z_]\w*)\s*=\s*(\S+)\s*\*\*\*")
_OP_FIELD = re.compile(r"^ {1,3}([a-z][a-z0-9]*(?: [a-z0-9]+)?)\s+(\S+)\s*$")
_OP_WANT = ("id", "vgs", "vds", "vbs", "vth", "vdsat", "vod", "beta",
            "gm", "gds", "gmb", "cdtot", "cgtot", "cstot", "cbtot",
            "cgs", "cgd", "ibs", "ibd")


def op_records(path, element=None):
    """Every MOSFET operating-point block in a listing, in printed order.

    Returns a list of dicts. Each carries the swept source as
    `sweep_name` / `sweep_value` when HSPICE printed one above the block, the
    element name, the region string, and every numeric field of `_OP_WANT`
    that the block contained.

    A block with no swept-source line above it -- the plain `.op` HSPICE does
    once before a sweep begins -- comes back with `sweep_value` None, so the
    caller can drop it rather than mistake it for a bias point.
    """
    if not os.path.exists(path):
        raise IOError("no such HSPICE listing: %s" % path)
    out = []
    cur = None
    in_mos = False
    sweep = (None, None)
    with open(path, "r", errors="replace") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            low = line.lower()
            m = _OP_SOURCE.search(low)
            if m:
                v = spice_float(m.group(2))
                sweep = (m.group(1).lower(), v)
                continue
            if "**** mosfets" in low:
                in_mos = True
                cur = None
                continue
            if not in_mos:
                continue
            st = low.strip()
            if st.startswith("element"):
                parts = st.split()
                name = parts[-1].split(":")[-1] if len(parts) > 1 else "m?"
                if cur:
                    out.append(cur)
                cur = {"element": name, "sweep_name": sweep[0],
                       "sweep_value": sweep[1]}
                continue
            if cur is None:
                if st.startswith("****") or st.startswith("***"):
                    in_mos = False
                continue
            if st.startswith("region"):
                cur["region"] = line.strip().split(None, 1)[-1].strip()
                continue
            m = _OP_FIELD.match(low)
            if m:
                key = m.group(1).replace(" ", "_")
                if key in _OP_WANT:
                    val = spice_float(m.group(2))
                    if val is not None:
                        cur[key] = val
                continue
            if st.startswith("****") or (st.startswith("***") and cur):
                out.append(cur)
                cur = None
                in_mos = False
    if cur:
        out.append(cur)
    if element:
        out = [r for r in out if r.get("element") == element]
    return out


def op_gate_row(path, element=None, need=8):
    """The gate ROW of the capacitance matrix, swept, from the op-point print.

    Returns {"vg", "cgg", "cgd", "cgs", "cgb", "closure_pct",
             "vth", "vdsat", "id", "gm", "gds", "region", "n"}
    with every array sorted by the swept bias, or None when the listing does
    not carry enough complete blocks (`need` of them).

    `cgb` is HSPICE's `cbtot`. That identification is not an assumption: on
    the Step-19 listing `cgs + cgd + cbtot` reproduces `cgtot` to every printed
    digit at all 91 biases, and at Vg = -0.2 V `cbtot` equals CGBO * L exactly
    (2.2688e-11 F/m * 12 nm = 0.2723 aF), which is the gate-to-substrate
    overlap term and nothing else.
    """
    recs = op_records(path, element=element)
    keep = [r for r in recs
            if r.get("sweep_value") is not None
            and all(k in r for k in ("cgtot", "cgs", "cgd", "cbtot"))]
    if len(keep) < int(need):
        return None
    v = np.asarray([r["sweep_value"] for r in keep], float)
    o = np.argsort(v)
    get = lambda k: np.asarray([r.get(k, float("nan")) for r in keep], float)[o]
    cgg, cgd, cgs = get("cgtot"), get("cgd"), get("cgs")
    cgb = get("cbtot")
    den = np.maximum(np.abs(cgg), 1e-30)
    out = {"vg": v[o], "cgg": cgg, "cgd": cgd, "cgs": cgs, "cgb": cgb,
           "closure_pct": 100.0 * (cgd + cgs + cgb - cgg) / den,
           "n": int(len(keep)),
           "sweep_name": keep[0].get("sweep_name")}
    for k in ("vth", "vdsat", "id", "gm", "gds", "vds"):
        out[k] = get(k)
    out["region"] = [keep[i].get("region", "") for i in o]
    return out
