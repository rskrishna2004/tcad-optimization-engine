"""l3_exec.spice_exec -- run HSPICE on one candidate model card.

WHY A SECOND EVALUATOR EXISTS
-----------------------------
`optimizer/runner.run_one` hardcodes a TWO-STEP flow: run the structure tool,
check the mesh file appeared, then run the device tool. If the structure step
fails or its mesh is missing, the run is abandoned (runner.py lines 118-126).

A circuit simulator has no structure step. There is no mesh, so that check can
never pass, and the existing runner cannot be used for extraction without
changing behaviour the TCAD path depends on. Rather than weaken a proven code
path, extraction gets its own evaluator that presents the SAME interface --
`evaluate_batch(param_dicts, tag) -> list of result dicts` -- so `run_campaign`,
the physics guard, the experiment DB and the optimizer are all reached
unchanged. This is the interchangeability the architecture was built for; this
module is the proof it works.

WHAT ONE EVALUATION DOES
------------------------
1. Render the candidate into a BSIM-CMG model card (`l2_decks.cardgen`).
2. Write one HSPICE deck per target sweep.
3. Run HSPICE once per deck, each in its own directory, with a timeout and (on
   POSIX) its own process group so a hung run is killed whole.
4. Parse each listing into a curve (`l3_exec.hspice_parser`).
5. Return {sweep_name: (v, i)} plus a status.

Batches run in parallel exactly like the TCAD path.
"""
import os
import signal
import subprocess
import time
from multiprocessing import Pool

from ..l2_decks import cardgen
from .hspice_parser import has_error, parse_lis, sweep_columns

SPICE_TOOL = os.environ.get("TCADOPT_SPICE_TOOL", "hspice")
SPICE_ARGS = (os.environ.get("TCADOPT_SPICE_ARGS", "").split()
              if os.environ.get("TCADOPT_SPICE_ARGS") else [])
SPICE_TIMEOUT = int(os.environ.get("TCADOPT_SPICE_TIMEOUT", "300"))
RUNS = os.environ.get("TCADOPT_FIT_RUNS",
                      os.path.join(os.path.dirname(os.path.dirname(
                          os.path.dirname(os.path.abspath(__file__)))),
                          "runs_fit"))


def spice_command(deck):
    """`hspice -i deck.sp -o deck` unless overridden by the environment."""
    base = os.path.splitext(os.path.basename(deck))[0]
    return [SPICE_TOOL] + list(SPICE_ARGS) + ["-i", deck, "-o", base]


def _run(cmd, cwd, timeout, logname):
    """Run one tool safely: output to a file (no pipe deadlock), own process
    group so a timeout kills the whole group. Same policy as runner.run_tool."""
    with open(os.path.join(cwd, logname), "w") as logf:
        kw = dict(cwd=cwd, stdout=logf, stderr=subprocess.STDOUT)
        if os.name == "posix":
            kw["preexec_fn"] = os.setsid
        p = subprocess.Popen(cmd, **kw)
        try:
            return p.wait(timeout=timeout), False
        except subprocess.TimeoutExpired:
            try:
                if os.name == "posix":
                    os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                else:
                    p.kill()
            except OSError:
                pass
            p.wait()
            return -9, True


def _sweep_deck_args(t):
    """Turn one target sweep into the deck arguments that reproduce it.

    The model is swept at EXACTLY the reference biases: same start, same stop,
    and a step taken from the reference spacing. Comparing a model curve to a
    reference curve on a different grid is how a fit quietly becomes an
    interpolation artefact, so the grid is copied rather than chosen.
    """
    v = t["v"]
    lo, hi = float(v.min()), float(v.max())
    step = (hi - lo) / max(len(v) - 1, 1)
    kind = t.get("sweep_kind", "IdVg").lower()
    if t["kind"] == "cv":
        return "cv", dict(vd=abs(float(t["bias"])), freq=1.0e6,
                          vg_start=lo, vg_stop=hi, vg_step=step)
    if kind == "idvd":
        return "idvd", dict(vg=abs(float(t["bias"])),
                            vd_start=lo, vd_stop=hi, vd_step=step)
    return "idvg", dict(vd=abs(float(t["bias"])),
                        vg_start=lo, vg_stop=hi, vg_step=step)


def _one(job):
    params, run_id, targets, models, structures, temp, nf = job
    rdir = os.path.join(RUNS, "fit_%s" % run_id)
    os.makedirs(rdir, exist_ok=True)
    res = {"run_id": str(run_id), "params": dict(params), "status": "fail",
           "stage": "init", "curves": {}, "metrics": None, "wall_s": 0.0,
           "run_dir": rdir}
    t0 = time.time()
    try:
        # one card per device polarity present in the targets
        res["stage"] = "card"
        cards = {}
        for dev in sorted(set(t["device"] for t in targets)):
            pol = "pmos" if dev.endswith("_p") else "nmos"
            cpath = os.path.join(rdir, "%s.lib" % dev)
            cardgen.write_card(cpath, models.get(dev, dev),
                               params.get(dev, params),
                               polarity=pol,
                               structure=(structures or {}).get(dev),
                               run_id=run_id)
            cards[dev] = cpath

        res["stage"] = "spice"
        errs = []
        for t in targets:
            kind, kw = _sweep_deck_args(t)
            base = t["name"]
            deck = os.path.join(rdir, "%s.sp" % base)
            cardgen.write_deck(deck, kind, cards[t["device"]],
                               models.get(t["device"], t["device"]),
                               base, temp=temp, nf=nf, **kw)
            rc, to = _run(spice_command("%s.sp" % base), rdir, SPICE_TIMEOUT,
                          "run_%s.log" % base)
            lis = os.path.join(rdir, "%s.lis" % base)
            bad, msg = has_error(lis)
            if to:
                errs.append("%s: timed out" % base)
                continue
            if bad:
                errs.append("%s: %s" % (base, msg[:120]))
                continue
            try:
                curves = parse_lis(lis)
                xh = "v(g)" if kind in ("idvg", "cv") else "v(d)"
                yh = "cgg" if kind == "cv" else "i(vd)"
                v, i = sweep_columns(curves, x_hint=xh, y_hint=yh)
                if len(v) < 3:
                    errs.append("%s: only %d points parsed" % (base, len(v)))
                    continue
                res["curves"][base] = (v, i)
            except Exception as exc:
                errs.append("%s: %s: %s" % (base, type(exc).__name__, exc))

        n_ok, n_all = len(res["curves"]), len(targets)
        res["status"] = ("ok" if n_ok == n_all
                         else "partial" if n_ok else "fail")
        if errs:
            res["error"] = "; ".join(errs[:4])
        res["stage"] = "done"
        return res
    except Exception as exc:
        res["error"] = "%s: %s" % (type(exc).__name__, exc)
        return res
    finally:
        res["wall_s"] = round(time.time() - t0, 1)


class HSpiceEvaluator(object):
    """Same interface as l3_exec.execute.TCADEvaluator, over one tool.

    `evaluate_batch(param_dicts, tag)` returns result dicts carrying
    `curves` -- {sweep_name: (v, i)} -- which the curve scorer consumes.
    """

    name = "hspice"

    def __init__(self, targets, models=None, structures=None, n_parallel=8,
                 temp=300.0, nf=1, scorer=None):
        self.targets = list(targets)
        self.models = models or {}
        self.structures = structures or {}
        self.n_parallel = int(n_parallel)
        self.temp = float(temp)
        self.nf = int(nf)
        self.scorer = scorer

    def evaluate_batch(self, param_dicts, tag="f"):
        jobs = [(p, "%s%03d" % (tag, i), self.targets, self.models,
                 self.structures, self.temp, self.nf)
                for i, p in enumerate(param_dicts)]
        if self.n_parallel > 1 and len(jobs) > 1:
            with Pool(processes=min(self.n_parallel, len(jobs))) as pool:
                results = pool.map(_one, jobs)
        else:
            results = [_one(j) for j in jobs]
        for r in results:
            if self.scorer is not None and r.get("curves"):
                try:
                    r["metrics"] = self.scorer.as_metrics(r["curves"])
                except Exception as exc:
                    r["metric_warn"] = str(exc)
            r.setdefault("failure_class",
                         "ok" if r["status"] == "ok" else "spice_error")
        ok = sum(1 for r in results if r["status"] == "ok")
        print("      batch done: %d/%d ok" % (ok, len(results)))
        return results
