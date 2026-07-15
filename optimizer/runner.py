# TCADOpt runner: renders one candidate design into a parameter file, runs the
# configured structure and device tools in an isolated working directory, and
# parses the electrical result into a metrics dictionary.
#
# This module is fully device- and vendor-independent:
#   * It optimizes ANY set of parameters. The names come from your problem
#     YAML; nothing here assumes a particular device or parameter list.
#   * It calls WHATEVER tools you configure (see tcadopt/l0_runtime/config.py
#     and decks.yaml). No tool names are hardcoded.
#
# Python 3.6+ compatible. Standard library plus numpy (via plt_parser).
import os
import sys
import json
import time
import shutil
import signal
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from plt_parser import extract_metrics  # noqa: E402

from tcadopt.l0_runtime.config import (  # noqa: E402
    load_deck_sets, param_filename, render_param_line, param_comment,
    structure_command, device_command,
    STRUCTURE_TIMEOUT, DEVICE_TIMEOUT)

ROOT = os.path.abspath(os.path.join(HERE, ".."))
TEMPLATES = os.environ.get("TCADOPT_TEMPLATES", os.path.join(ROOT, "templates"))
RUNS = os.environ.get("TCADOPT_RUNS", os.path.join(ROOT, "runs"))


def _deck(name):
    """Look up a device class in decks.yaml and normalize its keys."""
    sets = load_deck_sets()
    if name not in sets:
        raise KeyError(
            "device_class '%s' not found in decks.yaml. Add an entry for it. "
            "Available: %s" % (name, ", ".join(sorted(sets))))
    d = dict(sets[name])
    d.setdefault("structure", d.get("structure"))
    d.setdefault("device", d.get("des"))
    d.setdefault("result", d.get("plt"))
    d.setdefault("vdd", 1.0)
    missing = [k for k in ("structure", "device", "mesh", "result")
               if not d.get(k)]
    if missing:
        raise ValueError("deck '%s' is missing keys: %s (see decks.yaml)"
                         % (name, ", ".join(missing)))
    return d


def render_params(params, path, run_id):
    """Write the candidate's tuned parameters into the parameter file.

    Renders EVERY key the optimizer provides, in the order given, using the
    configurable line format. No parameter names are assumed.
    """
    header = "%s auto-generated %s run %s by TCADOpt" % (
        param_comment(), time.strftime("%Y/%m/%d %H:%M:%S"), run_id)
    lines = [header]
    for k in params:
        lines.append(render_param_line(k, params[k]))
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def run_tool(cmd, cwd, timeout, logname):
    """Run one external tool safely.

    stdout and stderr go to a log file (no pipes, so no pipe-buffer deadlock).
    On POSIX the tool runs in a new process group so a timeout kills the whole
    group with one signal. Returns (returncode, timed_out).
    """
    logf = open(os.path.join(cwd, logname), "w")
    popen_kwargs = dict(cwd=cwd, stdout=logf, stderr=subprocess.STDOUT)
    if os.name == "posix":
        popen_kwargs["preexec_fn"] = os.setsid
    p = subprocess.Popen(cmd, **popen_kwargs)
    try:
        rc = p.wait(timeout=timeout)
        return rc, False
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
    finally:
        logf.close()


def run_one(params, run_id=None, keep_output=False, deck=None):
    """Run one candidate design end to end and return its result dict."""
    if deck is None:
        raise ValueError("run_one requires a deck (the device_class name)")
    d = _deck(deck)
    if run_id is None:
        run_id = time.strftime("%Y%m%d_%H%M%S_") + str(os.getpid())
    rdir = os.path.join(RUNS, "run_%s" % run_id)
    os.makedirs(rdir, exist_ok=True)

    result = {"run_id": str(run_id), "params": dict(params),
              "status": "fail", "stage": "init", "metrics": None,
              "wall_s": 0.0}
    t0 = time.time()
    try:
        render_params(params, os.path.join(rdir, param_filename()), run_id)

        for f in (d["structure"], d["device"]):
            shutil.copy(os.path.join(TEMPLATES, f), rdir)

        result["stage"] = "structure"
        rc, to = run_tool(structure_command(d["structure"]),
                          rdir, STRUCTURE_TIMEOUT, "tool_structure.log")
        if to:
            result["error"] = "structure step timed out"
            return result
        if rc != 0 or not os.path.exists(os.path.join(rdir, d["mesh"])):
            result["error"] = "structure step failed (rc=%d)" % rc
            return result

        result["stage"] = "device"
        rc, to = run_tool(device_command(d["device"]),
                          rdir, DEVICE_TIMEOUT, "tool_device.log")
        res_file = os.path.join(rdir, d["result"])
        if not os.path.exists(res_file):
            result["error"] = ("device step produced no result file (rc=%d%s)"
                               % (rc, ", timed out" if to else ""))
            return result

        result["stage"] = "metrics"
        if d.get("kind") == "idvd":
            from plt_parser import extract_idvd
            lo = os.path.join(rdir, d["result_lo"])
            m = extract_idvd(res_file, lo, vdd=d["vdd"], dvg=d.get("dvg"))
            result["metrics"] = m
            full = (m.get("n_bias_points", 0) >= 10
                    and m.get("Idsat_A_per_um", 0) > 0
                    and m.get("gds_S_per_um", 0) == m.get("gds_S_per_um", 0))
        else:
            m = extract_metrics(res_file, vdd=d["vdd"])
            if "result_lin" in d or "plt_lin" in d:
                lin_name = d.get("result_lin", d.get("plt_lin"))
                lin = os.path.join(rdir, lin_name)
                if os.path.exists(lin):
                    try:
                        from plt_parser import extract_multibias
                        m.update(extract_multibias(
                            res_file, lin, vdd=d["vdd"],
                            vd_lin=d.get("vd_lin")))
                    except Exception as e:
                        m["multibias_error"] = "%s: %s" % (type(e).__name__, e)
            result["metrics"] = m
            full = m.get("n_bias_points", 0) >= 10 and m.get(
                "ION_A_per_um", 0) > 0

        result["status"] = "ok" if (full and rc == 0 and not to) else \
                           ("partial" if full else "fail")
        return result

    except Exception as e:
        result["error"] = "%s: %s" % (type(e).__name__, e)
        return result
    finally:
        result["wall_s"] = round(time.time() - t0, 1)
        try:
            with open(os.path.join(rdir, "metrics.json"), "w") as f:
                json.dump(result, f, indent=2)
        except OSError:
            pass


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: python runner.py <design.json> <device_class>")
        print("  <design.json>  a {parameter: value} dictionary")
        print("  <device_class> a key defined in decks.yaml")
        sys.exit(1)
    design = json.load(open(sys.argv[1]))
    device_class = sys.argv[2]
    print(json.dumps(run_one(design, run_id="smoketest",
                             deck=device_class), indent=2))
