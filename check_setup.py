#!/usr/bin/env python3
"""
check_setup.py
==============

Run this first, right after cloning, before anything else:

    python check_setup.py

It checks that Python and the three required packages (numpy, scipy, PyYAML)
are installed and importable, and tells you the exact command to fix it if
not. This is the single most common first-run problem for new users, so this
script exists to catch it in one step instead of a confusing traceback from
deep inside the engine.

Since v1.1.0 it also reports whether the engine imports and which simulator
tools are configured, for both the design-optimization path and the
compact-model extraction path.
"""
import sys

MIN_PYTHON = (3, 6)


def check_python():
    ok = sys.version_info[:2] >= MIN_PYTHON
    print("Python  : %s  (%s)" % (
        sys.version.split()[0], "OK" if ok else "TOO OLD, need 3.6+"))
    return ok


def check_package(import_name, pip_name):
    try:
        mod = __import__(import_name)
        ver = getattr(mod, "__version__", "unknown version")
        print("%-8s: found (%s)" % (import_name, ver))
        return True
    except ImportError:
        print("%-8s: MISSING" % import_name)
        return False


def check_engine():
    """Import the engine itself and report its version. A missing dependency
    shows up above; this catches a broken or partial checkout."""
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import tcadopt
        print("%-8s: v%s" % ("tcadopt", tcadopt.__version__))
        return True
    except Exception as exc:
        print("%-8s: FAILED TO IMPORT (%s)" % ("tcadopt", exc))
        return False


def check_tools():
    """Report which simulator tools are configured. Neither is needed to run
    the self-check demo; both are optional here and reported, not required."""
    import os
    print("-" * 60)
    print("Simulator tools (optional -- only needed for real runs)")
    struct = os.environ.get("TCADOPT_STRUCTURE_TOOL", "")
    device = os.environ.get("TCADOPT_DEVICE_TOOL", "")
    spice = os.environ.get("TCADOPT_SPICE_TOOL", "")
    print("  design optimization : structure=%s  device=%s"
          % (struct or "NOT SET", device or "NOT SET"))
    print("  model extraction    : spice=%s" % (spice or "NOT SET"))
    if not (struct and device):
        print("    -> set TCADOPT_STRUCTURE_TOOL and TCADOPT_DEVICE_TOOL "
              "to run design campaigns (docs/WORKFLOW.md)")
    if not spice:
        print("    -> set TCADOPT_SPICE_TOOL to run extractions "
              "(docs/PARAMETER_EXTRACTION.md)")


def main():
    print("=" * 60)
    print("TCADOpt environment check")
    print("=" * 60)

    py_ok = check_python()
    pkgs = [("numpy", "numpy"), ("scipy", "scipy"), ("yaml", "PyYAML")]
    results = [check_package(imp, pip) for imp, pip in pkgs]
    engine_ok = check_engine() if all(results) else False

    if py_ok and all(results):
        check_tools()
        print("-" * 60)
        print("Everything is installed. You can run the demo:")
        print("    python examples/synthetic_demo/run_demo.py")
        return 0 if engine_ok else 1
    print("-" * 60)

    print("Some requirements are missing. Fix with ONE command:")
    print("")
    print("    pip install -r requirements.txt")
    print("")
    print("If that command is not found, try one of these instead:")
    print("    pip3 install -r requirements.txt")
    print("    python -m pip install -r requirements.txt")
    print("    py -m pip install -r requirements.txt        (Windows)")
    print("")
    print("Then run this check again:")
    print("    python check_setup.py")
    return 1


if __name__ == "__main__":
    sys.exit(main())
