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
_IDVG = """* TCADOPT BSIM-CMG EXTRACTION  {tag}
* line 1 above IS the title line -- HSPICE takes the first line as the title
* no matter what it holds, so nothing may be placed above it.
{include}
.option post=0 nomod ingold=2 numdgt=7 accurate=1
.temp {temp}

vd d 0 dc {vd:.6f}
vg g 0 dc 0
vs s 0 dc 0
ve e 0 dc 0

X1 d g s e {model} NF={nf}

.dc vg {vg_start:.6f} {vg_stop:.6f} {vg_step:.6f}
.print dc v(g) i(vd)
.end
"""

_IDVD = """* TCADOPT BSIM-CMG EXTRACTION  {tag}
{include}
.option post=0 nomod ingold=2 numdgt=7 accurate=1
.temp {temp}

vd d 0 dc 0
vg g 0 dc {vg:.6f}
vs s 0 dc 0
ve e 0 dc 0

X1 d g s e {model} NF={nf}

.dc vd {vd_start:.6f} {vd_stop:.6f} {vd_step:.6f}
.print dc v(d) i(vd)
.end
"""

_CV = """* TCADOPT BSIM-CMG EXTRACTION  {tag}
{include}
.option post=0 nomod ingold=2 numdgt=7 dccap=1 accurate=1
.temp {temp}

vd d 0 dc {vd:.6f} ac 0
vg g 0 dc 0       ac 1
vs s 0 dc 0       ac 0
ve e 0 dc 0       ac 0

X1 d g s e {model} NF={nf}

* Cgg from the gate admittance at one low frequency: C = Im(Y) / (2*pi*f).
* The frequency is low enough that the quasi-static model's capacitance is the
* whole of the imaginary part, which is what the TCAD reference also measures.
.ac lin 1 {freq:.6e} {freq:.6e} sweep vg {vg_start:.6f} {vg_stop:.6f} {vg_step:.6f}
.print ac cgg=par('-ii(vg)/(6.283185307*{freq:.6e})')
.end
"""


def write_deck(path, kind, card_file, model, tag, temp=300.0, nf=1,
               section="", **kw):
    """Write one HSPICE deck. kind: 'idvg' | 'idvd' | 'cv'."""
    tpl = {"idvg": _IDVG, "idvd": _IDVD, "cv": _CV}[kind]
    base = os.path.basename(card_file)
    # `.lib` requires a section name. A bare model card has no sections, so it
    # is `.include`d; `.lib` is used only when the caller names a section.
    include = (".lib '%s' %s" % (base, section)) if section \
        else (".include '%s'" % base)
    txt = tpl.format(include=include, model=model, tag=tag,
                     temp=temp, nf=nf, **kw)
    with open(path, "w") as fh:
        fh.write(txt)
    return txt
