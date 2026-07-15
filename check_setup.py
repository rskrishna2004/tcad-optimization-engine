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


def main():
    print("=" * 60)
    print("TCADOpt environment check")
    print("=" * 60)

    py_ok = check_python()
    pkgs = [("numpy", "numpy"), ("scipy", "scipy"), ("yaml", "PyYAML")]
    results = [check_package(imp, pip) for imp, pip in pkgs]

    print("-" * 60)
    if py_ok and all(results):
        print("Everything is installed. You can run the demo:")
        print("    python examples/synthetic_demo/run_demo.py")
        return 0

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
