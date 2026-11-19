"""l9_report.overlay -- put the model and the reference on the SAME axes.

v1.1.21.  WHY THIS LIVES IN THE ENGINE AND NOT IN A SCRIPT
----------------------------------------------------------
Every number this project has produced so far is a scalar: an RMS, a per-cent
error, a threshold in millivolts.  Scalars are what a gate can judge, so that
is what the engine reported.  But a scalar cannot tell you WHERE a curve is
wrong, and a reviewer -- a professor, a senior modelling engineer, a committee
-- does not read scalars.  They read a figure with two lines on it.

So the overlay is a first-class engine output from v1.1.21 on.

It draws with NOTHING but the Python standard library and numpy.  matplotlib is
used when it happens to be installed and is never required: the SVG writer here
is the primary path, because an extraction run on a licensed CAD server is
exactly the place where `pip install matplotlib` is not available and a missing
figure is not an acceptable answer.  SVG opens in any browser, scales without
blurring, and PowerPoint, Word and LaTeX all take it directly.

Conventions, fixed here so every figure this engine ever draws matches:
  reference (TCAD)      solid, dark red   #8B0000, width 2.4
  compact model         dashed, black     #000000, width 1.7
The model is drawn SECOND, on top, so where the fit is good the black dashes
sit inside the red line and the eye reads "they agree" without a caption.
"""
import math
import os

import numpy as np

TCAD_COLOR = "#8B0000"
MODEL_COLOR = "#000000"
TCAD_WIDTH = 2.4
MODEL_WIDTH = 1.7
MODEL_DASH = "7,4"

_FONT = ("font-family=\"Helvetica,Arial,DejaVu Sans,sans-serif\"")


# ---------------------------------------------------------------------------
#  axis arithmetic
# ---------------------------------------------------------------------------
def _finite(a):
    a = np.asarray(a, float)
    return a[np.isfinite(a)]


def nice_step(span, want=5):
    """A 1 / 2 / 2.5 / 5 / 10 step that puts about `want` ticks across `span`."""
    if not (span > 0) or not np.isfinite(span):
        return 1.0
    raw = float(span) / max(int(want), 1)
    mag = 10.0 ** math.floor(math.log10(raw))
    for m in (1.0, 2.0, 2.5, 5.0, 10.0):
        if raw <= m * mag * 1.0000001:
            return m * mag
    return 10.0 * mag


def lin_ticks(lo, hi, want=5):
    """Tick positions inside [lo, hi], built by index so they do not drift."""
    lo, hi = float(lo), float(hi)
    if not (hi > lo):
        return [lo]
    step = nice_step(hi - lo, want)
    k0 = int(math.ceil(lo / step - 1e-9))
    out = []
    k = k0
    while k * step <= hi + 1e-9 * step:
        out.append(k * step)
        k += 1
        if len(out) > 40:
            break
    return out or [lo, hi]


def log_ticks(lo, hi, max_major=9):
    """Decade ticks inside [lo, hi]; every 2nd or 3rd decade if there are many.

    Returns (majors, minors).  Both are plain positive floats.
    """
    lo = max(float(lo), 1e-300)
    hi = max(float(hi), lo * 10.0)
    a = int(math.floor(math.log10(lo)))
    b = int(math.ceil(math.log10(hi)))
    dec = list(range(a, b + 1))
    every = 1
    while len(dec[::every]) > max_major and every < 6:
        every += 1
    majors = [10.0 ** k for k in dec[::every]
              if 10.0 ** k >= lo * 0.9999 and 10.0 ** k <= hi * 1.0001]
    minors = []
    if every == 1:
        for k in dec:
            for m in (2, 3, 4, 5, 6, 7, 8, 9):
                v = m * 10.0 ** k
                if lo * 0.9999 <= v <= hi * 1.0001:
                    minors.append(v)
    return (majors or [10.0 ** a]), minors


def fmt_lin(v, step):
    """Tick label with exactly as many decimals as the step needs."""
    if abs(v) < 1e-12:
        return "0"
    d = 0
    s = abs(step)
    while d < 6 and abs(round(s, d) - s) > 1e-12 * max(1.0, s):
        d += 1
    if abs(v) >= 1e4 or (abs(v) < 1e-3):
        return "%.3g" % v
    return ("%." + str(d) + "f") % v


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _pow_label(v):
    """`10` plus a raised exponent, as SVG text pieces: (mantissa, exponent)."""
    e = int(round(math.log10(abs(v)))) if v else 0
    return ("10", "%d" % e)


# ---------------------------------------------------------------------------
#  the two objects a caller builds
# ---------------------------------------------------------------------------
class Series(object):
    def __init__(self, x, y, label="", color=TCAD_COLOR, dash=None,
                 width=TCAD_WIDTH, marker=None, msize=2.6):
        self.x = np.asarray(x, float)
        self.y = np.asarray(y, float)
        self.label = label
        self.color = color
        self.dash = dash
        self.width = width
        self.marker = marker
        self.msize = msize


def tcad(x, y, label="TCAD (Sentaurus)"):
    return Series(x, y, label, TCAD_COLOR, None, TCAD_WIDTH)


def model(x, y, label="compact model (BSIM-CMG)"):
    return Series(x, y, label, MODEL_COLOR, MODEL_DASH, MODEL_WIDTH)


class Panel(object):
    def __init__(self, series=None, title="", xlabel="", ylabel="",
                 ylog=False, xlim=None, ylim=None, note="", note2=""):
        self.series = list(series or [])
        self.title = title
        self.xlabel = xlabel
        self.ylabel = ylabel
        self.ylog = bool(ylog)
        self.xlim = xlim
        self.ylim = ylim
        self.note = note
        self.note2 = note2

    # -- data limits -------------------------------------------------------
    def limits(self):
        xs, ys = [], []
        for s in self.series:
            ok = np.isfinite(s.x) & np.isfinite(s.y)
            if self.ylog:
                ok = ok & (s.y > 0)
            if not ok.any():
                continue
            xs.append(s.x[ok])
            ys.append(s.y[ok])
        if not xs:
            return (0.0, 1.0, 1.0, 10.0) if self.ylog else (0.0, 1.0, 0.0, 1.0)
        x = np.concatenate(xs)
        y = np.concatenate(ys)
        x0, x1 = float(x.min()), float(x.max())
        y0, y1 = float(y.min()), float(y.max())
        if self.xlim:
            x0, x1 = self.xlim
        if x1 <= x0:
            x1 = x0 + 1.0
        if self.ylim:
            y0, y1 = self.ylim
        elif self.ylog:
            y0 = 10.0 ** math.floor(math.log10(max(y0, 1e-300)))
            y1 = 10.0 ** math.ceil(math.log10(max(y1, y0 * 10.0)))
        else:
            pad = 0.06 * (y1 - y0) if y1 > y0 else max(abs(y1), 1.0) * 0.1
            # A drain current that starts at zero should be drawn from zero:
            # an axis that begins at -2 uA/um to make room for a pad invents
            # a negative current the device never has.  Only a quantity whose
            # whole range sits well above zero -- a capacitance going from 30
            # to 59 aF -- keeps its padded lower limit, because forcing that
            # one to zero would squeeze the shape being judged into the top
            # third of the panel.
            if y0 >= 0.0 and y0 <= 0.15 * y1:
                y0 = 0.0
            else:
                y0 = y0 - pad
            y1 = y1 + pad
        if y1 <= y0:
            y1 = y0 + 1.0
        return x0, x1, y0, y1


# ---------------------------------------------------------------------------
#  the SVG writer
# ---------------------------------------------------------------------------
PAD_L, PAD_R, PAD_T, PAD_B = 80, 20, 48, 52


def _panel_svg(p, w, h, ox, oy, out):
    """Draw one panel at offset (ox, oy) into the list of SVG strings `out`."""
    x0, x1, y0, y1 = p.limits()
    px, py = ox + PAD_L, oy + PAD_T
    pw, ph = w - PAD_L - PAD_R, h - PAD_T - PAD_B

    def X(v):
        return px + (float(v) - x0) / (x1 - x0) * pw

    if p.ylog:
        l0, l1 = math.log10(max(y0, 1e-300)), math.log10(max(y1, 1e-299))

        def Y(v):
            v = float(v)
            if not (v > 0) or not np.isfinite(v):
                return None
            return py + ph - (math.log10(v) - l0) / (l1 - l0) * ph
    else:
        def Y(v):
            v = float(v)
            if not np.isfinite(v):
                return None
            return py + ph - (v - y0) / (y1 - y0) * ph

    # plot box
    out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" '
               'fill="#ffffff" stroke="#222222" stroke-width="1.1"/>'
               % (px, py, pw, ph))

    # ---- x ticks and vertical grid
    xt = lin_ticks(x0, x1, 5)
    xstep = (xt[1] - xt[0]) if len(xt) > 1 else (x1 - x0)
    for v in xt:
        xx = X(v)
        out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
                   'stroke="#dddddd" stroke-width="0.8"/>'
                   % (xx, py, xx, py + ph))
        out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
                   'stroke="#222222" stroke-width="1.0"/>'
                   % (xx, py + ph, xx, py + ph - 5))
        out.append('<text x="%.1f" y="%.1f" %s font-size="12" '
                   'text-anchor="middle" fill="#111111">%s</text>'
                   % (xx, py + ph + 16, _FONT, _esc(fmt_lin(v, xstep))))

    # ---- y ticks and horizontal grid
    if p.ylog:
        maj, mino = log_ticks(y0, y1)
        for v in mino:
            yy = Y(v)
            if yy is None:
                continue
            out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
                       'stroke="#f0f0f0" stroke-width="0.7"/>'
                       % (px, yy, px + pw, yy))
        for v in maj:
            yy = Y(v)
            if yy is None:
                continue
            out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
                       'stroke="#dddddd" stroke-width="0.8"/>'
                       % (px, yy, px + pw, yy))
            out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
                       'stroke="#222222" stroke-width="1.0"/>'
                       % (px, yy, px + 5, yy))
            man, ex = _pow_label(v)
            out.append('<text x="%.1f" y="%.1f" %s font-size="12" '
                       'text-anchor="end" fill="#111111">%s'
                       '<tspan dy="-5" font-size="9">%s</tspan></text>'
                       % (px - 7, yy + 4, _FONT, man, _esc(ex)))
    else:
        yt = lin_ticks(y0, y1, 5)
        ystep = (yt[1] - yt[0]) if len(yt) > 1 else (y1 - y0)
        for v in yt:
            yy = Y(v)
            if yy is None:
                continue
            out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
                       'stroke="#dddddd" stroke-width="0.8"/>'
                       % (px, yy, px + pw, yy))
            out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
                       'stroke="#222222" stroke-width="1.0"/>'
                       % (px, yy, px + 5, yy))
            out.append('<text x="%.1f" y="%.1f" %s font-size="12" '
                       'text-anchor="end" fill="#111111">%s</text>'
                       % (px - 7, yy + 4, _FONT, _esc(fmt_lin(v, ystep))))

    # ---- the curves, reference first so the model sits on top
    for s in p.series:
        pts, run = [], []
        for xv, yv in zip(s.x, s.y):
            yy = Y(yv)
            xx = X(xv)
            inside = (yy is not None and np.isfinite(xx)
                      and x0 - 1e-12 <= xv <= x1 + 1e-12)
            if inside:
                yy = min(max(yy, py - 0.5), py + ph + 0.5)
                run.append("%.2f,%.2f" % (xx, yy))
            else:
                if len(run) > 1:
                    pts.append(run)
                run = []
        if len(run) > 1:
            pts.append(run)
        dash = ' stroke-dasharray="%s"' % s.dash if s.dash else ""
        for run in pts:
            out.append('<polyline points="%s" fill="none" stroke="%s" '
                       'stroke-width="%.2f"%s stroke-linejoin="round" '
                       'stroke-linecap="round"/>'
                       % (" ".join(run), s.color, s.width, dash))
        if s.marker:
            for xv, yv in zip(s.x, s.y):
                yy = Y(yv)
                if yy is None or not (x0 <= xv <= x1):
                    continue
                out.append('<circle cx="%.2f" cy="%.2f" r="%.2f" fill="%s" '
                           'stroke="none"/>' % (X(xv), yy, s.msize, s.color))

    # ---- titles and labels
    if p.title:
        out.append('<text x="%.1f" y="%.1f" %s font-size="13.5" '
                   'font-weight="bold" text-anchor="middle" '
                   'fill="#111111">%s</text>'
                   % (px + pw / 2.0, oy + 21, _FONT, _esc(p.title)))
    if p.xlabel:
        out.append('<text x="%.1f" y="%.1f" %s font-size="12.5" '
                   'text-anchor="middle" fill="#111111">%s</text>'
                   % (px + pw / 2.0, oy + h - 20, _FONT, _esc(p.xlabel)))
    if p.ylabel:
        out.append('<text x="%.1f" y="%.1f" %s font-size="12.5" '
                   'text-anchor="middle" fill="#111111" '
                   'transform="rotate(-90 %.1f %.1f)">%s</text>'
                   % (ox + 17, py + ph / 2.0, _FONT,
                      ox + 17, py + ph / 2.0, _esc(p.ylabel)))
    ny = oy + 38
    if p.note:
        out.append('<text x="%.1f" y="%.1f" %s font-size="11" '
                   'text-anchor="start" fill="#444444">%s</text>'
                   % (px, ny, _FONT, _esc(p.note)))
    if p.note2:
        out.append('<text x="%.1f" y="%.1f" %s font-size="11" '
                   'text-anchor="end" fill="#444444">%s</text>'
                   % (px + pw, ny, _FONT, _esc(p.note2)))


def _legend_svg(series, x, y, out, gap=250):
    for k, s in enumerate(series):
        xx = x + k * gap
        dash = ' stroke-dasharray="%s"' % s.dash if s.dash else ""
        out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
                   'stroke="%s" stroke-width="%.2f"%s/>'
                   % (xx, y, xx + 38, y, s.color, s.width + 0.4, dash))
        out.append('<text x="%.1f" y="%.1f" %s font-size="12.5" '
                   'fill="#111111">%s</text>'
                   % (xx + 45, y + 4.5, _FONT, _esc(s.label)))


def figure_svg(panels, path, ncols=2, panel_w=440, panel_h=330, title="",
               subtitle="", legend=None, footer=""):
    """Write a grid of overlay panels to one standalone .svg file."""
    panels = [p for p in panels if p is not None]
    n = len(panels)
    ncols = max(1, min(int(ncols), n)) if n else 1
    nrows = int(math.ceil(n / float(ncols)))
    head = 26 + (24 if title else 0) + (18 if subtitle else 0)
    legh = 30 if legend else 0
    foot = 20 if footer else 6
    W = ncols * panel_w + 20
    H = head + legh + nrows * panel_h + foot + 10
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
           'viewBox="0 0 %d %d">' % (W, H, W, H),
           '<rect width="%d" height="%d" fill="#ffffff"/>' % (W, H)]
    y = 24
    if title:
        out.append('<text x="%.1f" y="%.1f" %s font-size="17" '
                   'font-weight="bold" text-anchor="middle" fill="#111111">'
                   '%s</text>' % (W / 2.0, y, _FONT, _esc(title)))
        y += 22
    if subtitle:
        out.append('<text x="%.1f" y="%.1f" %s font-size="12.5" '
                   'text-anchor="middle" fill="#555555">%s</text>'
                   % (W / 2.0, y, _FONT, _esc(subtitle)))
        y += 16
    if legend:
        _legend_svg(legend, 20, y + 10, out)
        y += legh
    for k, p in enumerate(panels):
        r, c = divmod(k, ncols)
        _panel_svg(p, panel_w, panel_h, 10 + c * panel_w, y + r * panel_h, out)
    if footer:
        out.append('<text x="%.1f" y="%.1f" %s font-size="11" '
                   'text-anchor="start" fill="#666666">%s</text>'
                   % (14.0, H - 10, _FONT, _esc(footer)))
    out.append('</svg>')
    svg = "\n".join(out)
    if path:
        d = os.path.dirname(os.path.abspath(path))
        if d and not os.path.isdir(d):
            os.makedirs(d)
        with open(path, "w") as fh:
            fh.write(svg)
    return svg


# ---------------------------------------------------------------------------
#  one HTML page that carries every figure, so there is one thing to open
# ---------------------------------------------------------------------------
def write_html(path, blocks, title="TCAD vs compact model", intro=""):
    """`blocks` is a list of (heading, svg_string, caption)."""
    out = ['<!doctype html><html><head><meta charset="utf-8">',
           '<title>%s</title>' % _esc(title),
           '<style>body{font-family:Helvetica,Arial,sans-serif;margin:26px;'
           'color:#111;max-width:1180px}h1{font-size:21px}h2{font-size:16px;'
           'margin-top:30px;border-bottom:1px solid #ddd;padding-bottom:5px}'
           'p{font-size:13.5px;line-height:1.55;color:#333}'
           'svg{border:1px solid #e3e3e3;background:#fff;max-width:100%%}'
           'pre{font-size:12px;background:#fafafa;border:1px solid #eee;'
           'padding:10px;overflow-x:auto}</style></head><body>',
           '<h1>%s</h1>' % _esc(title)]
    if intro:
        out.append('<p>%s</p>' % _esc(intro))
    for head, svg, cap in blocks:
        out.append('<h2>%s</h2>' % _esc(head))
        if cap:
            out.append('<p>%s</p>' % _esc(cap))
        out.append(svg.split("?>", 1)[-1] if svg.startswith("<?xml") else svg)
    out.append('</body></html>')
    with open(path, "w") as fh:
        fh.write("\n".join(out))
    return path


# ---------------------------------------------------------------------------
#  how far apart are the two lines?  the numbers that go under each panel
# ---------------------------------------------------------------------------
def _interp_to(xr, xm, ym, logy=False):
    """Model values read at the reference's own x positions."""
    o = np.argsort(xm)
    xm, ym = np.asarray(xm, float)[o], np.asarray(ym, float)[o]
    if logy:
        a = np.maximum(np.abs(ym), 1e-300)
        return 10.0 ** np.interp(xr, xm, np.log10(a), left=np.nan,
                                 right=np.nan)
    return np.interp(xr, xm, ym, left=np.nan, right=np.nan)


def curve_error(xr, yr, xm, ym, logy=False):
    """Agreement between one reference curve and one model curve.

    Returns a dict with
      rms_pct    root-mean-square of the per-point relative error, in per cent
      max_pct    the worst single point, in per cent
      at_max     the x where that happens
      rms_dec    root-mean-square error in DECADES (for a log quantity)
      n          points compared
    A relative error is the only fair measure here because a drain current
    covers six decades: an absolute error would be set entirely by the two or
    three points near Ion and would say nothing about the subthreshold slope.
    """
    xr = np.asarray(xr, float)
    yr = np.asarray(yr, float)
    mm = _interp_to(xr, xm, ym, logy=logy)
    ok = np.isfinite(mm) & np.isfinite(yr)
    if logy:
        ok = ok & (np.abs(yr) > 0) & (np.abs(mm) > 0)
    if not ok.any():
        return {"rms_pct": float("nan"), "max_pct": float("nan"),
                "at_max": float("nan"), "rms_dec": float("nan"), "n": 0}
    a, b, x = yr[ok], mm[ok], xr[ok]
    den = np.where(np.abs(a) > 0, np.abs(a), 1.0)
    rel = (b - a) / den * 100.0
    k = int(np.argmax(np.abs(rel)))
    dec = float("nan")
    if logy:
        dec = float(np.sqrt(np.mean((np.log10(np.abs(b))
                                     - np.log10(np.abs(a))) ** 2)))
    return {"rms_pct": float(np.sqrt(np.mean(rel ** 2))),
            "max_pct": float(rel[k]), "at_max": float(x[k]),
            "rms_dec": dec, "n": int(ok.sum())}


def error_table(pairs, title="agreement, curve by curve"):
    """`pairs` is a list of (label, xr, yr, xm, ym, logy).  Returns text."""
    w = max([len(p[0]) for p in pairs] + [12])
    lines = ["  " + title,
             "  " + "-" * (w + 52),
             "  %-*s %9s %9s %9s %7s" % (w, "curve", "rms %", "worst %",
                                         "at", "pts")]
    rows = []
    for lab, xr, yr, xm, ym, logy in pairs:
        e = curve_error(xr, yr, xm, ym, logy=logy)
        rows.append((lab, e))
        lines.append("  %-*s %9.3f %+9.3f %9.4f %7d"
                     % (w, lab, e["rms_pct"], e["max_pct"], e["at_max"],
                        e["n"]))
    fin = [e["rms_pct"] for _, e in rows if np.isfinite(e["rms_pct"])]
    if fin:
        lines.append("  " + "-" * (w + 52))
        lines.append("  %-*s %9.3f %9s" % (w, "worst of all", max(fin),
                                           ""))
    return "\n".join(lines), rows


# ---------------------------------------------------------------------------
#  matplotlib, if and only if it is already installed
# ---------------------------------------------------------------------------
def have_mpl():
    try:
        import matplotlib
        return matplotlib is not None
    except Exception:
        return False


def figure_mpl(panels, path, ncols=2, title="", legend=None, dpi=170):
    """The same figure through matplotlib, when it is available.

    Returns the path written, or None if matplotlib is not installed.  The
    SVG writer above is the primary path; this exists only so that a machine
    which does have matplotlib also gets a .png for pasting into slides.
    """
    if not have_mpl():
        return None
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    panels = [p for p in panels if p is not None]
    n = len(panels)
    if not n:
        return None
    ncols = max(1, min(int(ncols), n))
    nrows = int(math.ceil(n / float(ncols)))
    fig, axes = plt.subplots(nrows, ncols, figsize=(5.6 * ncols, 4.2 * nrows),
                             squeeze=False)
    for k, p in enumerate(panels):
        ax = axes[k // ncols][k % ncols]
        for s in p.series:
            kw = dict(color=s.color, linewidth=s.width, label=s.label)
            if s.dash:
                kw["linestyle"] = (0, tuple(float(t) for t in
                                            s.dash.split(",")))
            ax.plot(s.x, s.y, **kw)
        if p.ylog:
            ax.set_yscale("log")
        ax.set_title(p.title, fontsize=11, fontweight="bold")
        ax.set_xlabel(p.xlabel, fontsize=10)
        ax.set_ylabel(p.ylabel, fontsize=10)
        ax.grid(True, which="major", color="#dddddd", linewidth=0.7)
        if p.ylog:
            ax.grid(True, which="minor", color="#f2f2f2", linewidth=0.5)
        if p.note:
            ax.text(0.02, 0.03, p.note, transform=ax.transAxes, fontsize=8.5,
                    color="#444444")
        if p.note2:
            ax.text(0.98, 0.03, p.note2, transform=ax.transAxes, fontsize=8.5,
                    color="#444444", ha="right")
    for k in range(n, nrows * ncols):
        axes[k // ncols][k % ncols].axis("off")
    if panels and panels[0].series:
        axes[0][0].legend(fontsize=9, loc="best")
    if title:
        fig.suptitle(title, fontsize=13, fontweight="bold")
        fig.tight_layout(rect=(0, 0, 1, 0.96))
    else:
        fig.tight_layout()
    fig.savefig(path, dpi=dpi)
    plt.close(fig)
    return path
