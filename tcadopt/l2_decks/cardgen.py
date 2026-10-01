"""l2_decks.cardgen -- render a candidate into a BSIM-CMG model card + HSPICE deck.

WHY THIS EXISTS
---------------
`l2_decks` shipped as an empty interface stub: the architecture document calls
it "the seam where the engine meets your simulator", and it contained no code.
Parameter extraction is exactly that seam, so this is where it goes.

The existing renderer, `optimizer/runner.render_params`, writes a flat file of
`name = value` lines for a structure deck to read. A SPICE model card is not
that. It is a `.model` statement whose parameters continue across lines with a
leading `+`, and it must carry a `VERSION` and the fixed structural parameters
alongside the ones being fitted.

TWO HARD-WON FACTS ARE BAKED IN HERE
------------------------------------
1. `VERSION` must be written explicitly. LEVEL 72 defaults to VERSION 106.1,
   which has no gate-all-around module, so `GEOMOD=5` is rejected outright with
   "Out of range from [0:3]". Writing `VERSION = 111.21` is what makes GEOMOD=5
   and NGAA=4 legal. This was found the hard way, by a deck that failed.

2. `NF` is an INSTANCE-only parameter. In the Verilog-A source it is declared
   `IPIco(nf, ...)`, so it belongs on the element line (`X1 d g s e nsfet_n
   NF=1`), not inside the `.model` card. Putting it in the card is an error,
   not a style choice.

The first line of the generated deck is the TITLE line. HSPICE treats the very
first line of any netlist as the title no matter what it contains, so a comment
banner placed above it silently becomes the title and shifts the whole deck down
by one -- which is how four probe decks were once lost to a `B`-element syntax
error. Every deck this module writes therefore starts with a `*` line that is
MEANT to be the title.
"""
import os
import time

# Structural parameters that describe the device itself. They are measured from
# the TCAD structure and are NEVER fitted -- fitting them would let the model
# "explain" a current error by silently changing the transistor's dimensions.
DEFAULT_STRUCTURE = {
    "version": 111.21,      # see note 1 above: without this, GEOMOD=5 is illegal
    "geomod": 5,            # 5 = gate-all-around
    "bulkmod": 0,
    "tgaa": 5.0e-9,         # nanosheet thickness
    "wgaa": 10.0e-9,        # nanosheet width
    "tsus": 10.0e-9,        # sheet-to-sheet suspension pitch
    "ngaa": 4,              # sheets per stack
    "nfin": 1,
    "l": 12.0e-9,
    "lsp": 5.0e-9,
    "eot": 0.734e-9,
    "toxp": 2.0e-9,
    "epsrox": 3.9,
    "epsrsp": 7.5,
    "nbody": 1.0e21,
    "nsd": 1.0e26,
    # Self-heating OFF. The reference TCAD runs solve Poisson + continuity +
    # quantum potential and NO lattice-temperature equation (confirmed in their
    # own log), so the reference data is isothermal. Turning SHMOD on here would
    # make the model predict less current than a reference that has no
    # self-heating, and the optimizer would hide the discrepancy by inflating
    # mobility. Fit isothermal; add self-heating afterwards against data that
    # actually contains it.
    "shmod": 0,
}

# Integer-valued BSIM-CMG parameters: writing 5.000000e+00 where the model
# expects an integer selector is a parse risk, so these are formatted as ints.
_INT_PARAMS = {"geomod", "bulkmod", "ngaa", "nfin", "nf", "shmod", "rdsmod",
               "cgeomod", "cgeo1sw", "igcmod", "igbmod", "gidlmod", "rgatemod",
               "rgeomod", "capmod", "diomod", "nqsmod", "tempmod", "coremod",
               "asymmod", "quantumod", "nsegdrift"}


def fmt_value(name, value):
    """Format one parameter the way a SPICE card expects it."""
    n = name.lower()
    if n == "version":
        return "%.2f" % float(value)          # 111.21, not 1.112100e+02
    if n in _INT_PARAMS:
        return "%d" % int(round(float(value)))
    return "%.6e" % float(value)


def render_card(model_name, params, polarity="nmos", structure=None,
                header=None):
    """Return the text of one `.model` card.

    params    : the parameters being fitted this stage {name: value}
    structure : fixed structural parameters (DEFAULT_STRUCTURE if omitted)
    """
    st = dict(DEFAULT_STRUCTURE if structure is None else structure)
    st.update(params or {})
    st.pop("nf", None)                        # see note 2: instance-only
    lines = []
    if header:
        for h in str(header).splitlines():
            lines.append("* %s" % h)
    lines.append(".model %s %s level = 72" % (model_name, polarity))
    # VERSION first: everything after it is validated against that revision.
    if "version" in st:
        lines.append("+ version = %s" % fmt_value("version", st.pop("version")))
    for k in sorted(st):
        lines.append("+ %s = %s" % (k, fmt_value(k, st[k])))
    return "\n".join(lines) + "\n"


def write_card(path, model_name, params, polarity="nmos", structure=None,
               run_id=None):
    txt = render_card(
        model_name, params, polarity=polarity, structure=structure,
        header="auto-generated %s run %s by TCADOpt (BSIM-CMG extraction)"
               % (time.strftime("%Y/%m/%d %H:%M:%S"), run_id))
    with open(path, "w") as fh:
        fh.write(txt)
    return txt


# --------------------------------------------------------------------------
#  The HSPICE deck. One .sp per sweep, each self-contained apart from the card.
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
#  THE ELEMENT LINE
#
#  BSIM-CMG is reached in HSPICE through an **M element**, not a subcircuit
#  call.  This is not a style choice and it is not inferred from the manual:
#  it is what four probe decks actually ran with on PrimeSim HSPICE U-2023.03.
#
#      .model nch nmos level=72
#      M1 nd ng 0 0 nch            <- 4 nodes: drain gate source body
#      M1 nd ng 0 0 nt nch         <- 5 nodes: the 5th is the thermal node,
#                                     and only when SHMOD = 1
#
#  An `X` element would be a subcircuit call and there is no subcircuit to
#  call.  The first version of this module emitted `X1 d g s e <model>` and
#  would have failed on the very first deck.
#
#  NF is an instance-only parameter (`IPIco(nf, ...)` in the Verilog-A source)
#  and so belongs on this line rather than in the card.  It is emitted only
#  when it differs from 1, because 1 is the model's own default and the
#  probe decks that are known to work did not carry it.
# --------------------------------------------------------------------------

_IDVG = """* TCADOPT BSIM-CMG EXTRACTION  {tag}
* Line 1 above IS the title line. HSPICE takes the first line of a netlist as
* the title whatever it contains, so nothing may be placed above it.
{include}
.option list node
.temp {temp}

vd d 0 dc {vd:.6f}
vg g 0 dc 0
vs s 0 dc 0
ve e 0 dc 0

M1 d g s e {model}{inst}

.dc vg {vg_start:.6f} {vg_stop:.6f} {vg_step:.6f}
.print dc i(M1) v(g)
.end
"""

_IDVD = """* TCADOPT BSIM-CMG EXTRACTION  {tag}
{include}
.option list node
.temp {temp}

vd d 0 dc 0
vg g 0 dc {vg:.6f}
vs s 0 dc 0
ve e 0 dc 0

M1 d g s e {model}{inst}

.dc vd {vd_start:.6f} {vd_stop:.6f} {vd_step:.6f}
.print dc i(M1) v(d)
.end
"""

# --------------------------------------------------------------------------
#  THE C-V DECK -- no longer a guess.
#
#  This template was shipped in v1.1.0 carrying an honest warning that it had
#  never been run.  It has now been run, on PrimeSim HSPICE U-2023.03, and
#  `p1_cv_B_prim.lis` is the listing.  Three things were confirmed:
#
#   1. `.ac lin 1 f f sweep vg <start> <stop> <step>` is accepted, and it
#      produces ONE table per gate bias -- 90 of them for a 90-point sweep --
#      each holding a single row, with the bias written above the table as
#      `*** parameter 0:vg  =  -200.0000m ***`.
#
#   2. `.print ac ir(vg) ii(vg)` prints the real and imaginary parts of the
#      gate-source current under the two-word quantities `i real` and `i imag`.
#      Re was exactly 0. at all 90 points, as it must be with IGCMOD=IGBMOD=0.
#
#   3. The extraction C = -Im(I(vg)) / (2*pi*f) is right in magnitude AND sign:
#      raising CFS by 1e-10 F/m raised C by +1.20000e-17 F, and eq. 3.700 of
#      the BSIM-CMG manual requires NFIN*Weff*dCFS = 1 * 120e-9 * 1e-10
#      = 1.2e-17 F.  That same measurement is an independent confirmation that
#      Weff = 120.000 nm, which is eq. 3.53/3.54 for GEOMOD=5.
#
#  The primitives are printed rather than `cgg=par(...)` deliberately: both
#  forms run, but with the primitives the arithmetic lives in
#  `hspice_parser.cv_columns`, where it is documented, unit-tested and visible
#  in a diff, instead of inside a string that HSPICE evaluates.
# --------------------------------------------------------------------------
_CV = """* TCADOPT BSIM-CMG EXTRACTION  {tag}
{include}
.option list node
.temp {temp}

vd d 0 dc {vd:.6f} ac 0
vg g 0 dc 0       ac 1
vs s 0 dc 0       ac 0
ve e 0 dc 0       ac 0

M1 d g s e {model}{inst}

* THE WHOLE GATE ROW, not just its sum.  (TCADOpt v1.1.16)
*
* Cgg is not one capacitance. It is Cgd + Cgs + Cgb, and the three do
* completely different things when the drain bias changes: this device's own
* TCAD reference says that from Vd = 50 mV to Vd = 0.6 V, at Vg = 0.6 V,
*
*     Cgg  59.441 -> 45.135 aF   (-24.1%)
*     Cgd  28.570 -> 14.426 aF   (-49.5%)   <- the whole of it
*     Cgs  29.465 -> 29.200 aF   (-0.9%)
*     Cgb   1.406 ->  1.509 aF   (+7.3%)
*
* Eighteen steps of this project fitted the sum and never once looked at the
* parts. The gate is already driven with ac 1 and every other terminal is
* already AC-grounded, so the other three branch currents are free: the same
* sweep, three more printed columns, no extra simulation at all.
*
* Re(I(vg)) must be 0 here; cv_columns refuses the sweep if it is not.
.ac lin 1 {freq:.6e} {freq:.6e} sweep vg {vg_start:.6f} {vg_stop:.6f} {vg_step:.6f}
.print ac ir(vg) ii(vg){gate_row}
.end
"""


# v1.1.16: set False to write the Step-1..18 deck, byte for byte, if a
# simulator ever refuses the longer .print line.
#
# v1.1.17 -- WHAT THIS FLAG ACTUALLY BOUGHT, AND WHAT IT COST
# -----------------------------------------------------------
# It stays True, but for a smaller reason than v1.1.16 believed, and the
# record is worth keeping because it cost a whole step.
#
# 1. IT IS NOT HOW THE GATE ROW IS MEASURED. Driving the gate with `ac 1` and
#    reading the other three branch currents measures -dQd/dVg, -dQs/dVg,
#    -dQb/dVg: the gate COLUMN. The reference CSV holds -dQg/dVd, -dQg/dVs,
#    -dQg/dVb: the gate ROW. Both sum to Cgg, so a closure check passes for
#    either and cannot tell them apart. On one bias of one listing the two
#    differ by 7.6 aF out of 50. The row comes from HSPICE's own
#    operating-point print -- see `hspice_parser.op_gate_row` -- which needs
#    no deck change at all and is present in every listing back to Step 1.
#
# 2. IT BROKE THE PARSER. Eight printed columns do not fit in one HSPICE
#    table: the tool splits them across two, four columns each, under one bias
#    heading. v1.1.16's stitcher joined tables only when their columns were
#    identical, so 91 biases became 182 one-row blocks, the C-V curve came
#    back as a single point, and Step 19 lost every C-V-dependent stage.
#    `hspice_parser._merge_split_tables` now merges them, and is tested
#    against that exact listing.
#
# It stays True because the column is a genuinely useful diagnostic -- it is
# what shows the model's own drain/source charge partition -- and because it
# now costs nothing: same run, same time, a parser that handles it, and a
# fallback to the operating-point Cgg if the AC table ever fails again.
CV_GATE_ROW = True
_GATE_ROW_COLS = " ir(vd) ii(vd) ir(vs) ii(vs) ir(ve) ii(ve)"


def write_deck(path, kind, card_file, model, tag, temp=27.0, nf=1,
               section="", gate_row=None, **kw):
    """Write one HSPICE deck. kind: 'idvg' | 'idvd' | 'cv'.

    `temp` is in DEGREES CELSIUS, because that is what SPICE's `.temp` takes.
    It defaults to 27 C = 300.15 K, which is the temperature the reference TCAD
    runs were solved at (their log prints "Spice temperature: 3.0015e+02").
    HSPICE's own default is 25 C, so leaving this out would compare the model
    at 25 C against reference data at 27 C -- a 2 C error, which matters most
    in sub-threshold where current is exponential in temperature.
    """
    tpl = {"idvg": _IDVG, "idvd": _IDVD, "cv": _CV}[kind]
    if kind == "cv":
        # the extra printed columns, or "" for the Step-1..18 deck exactly
        want = CV_GATE_ROW if gate_row is None else bool(gate_row)
        kw["gate_row"] = _GATE_ROW_COLS if want else ""
    base = os.path.basename(card_file)
    # `.lib` requires a section name. A bare model card has no sections, so it
    # is `.include`d; `.lib` is used only when the caller names a section.
    include = (".lib '%s' %s" % (base, section)) if section \
        else (".include '%s'" % base)
    inst = "" if int(nf) == 1 else " NF=%d" % int(nf)
    txt = tpl.format(include=include, model=model, tag=tag,
                     temp=temp, inst=inst, **kw)
    with open(path, "w") as fh:
        fh.write(txt)
    return txt
