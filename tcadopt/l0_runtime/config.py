"""
tcadopt.l0_runtime.config
=========================

Central configuration for how TCADOpt invokes your TCAD simulator.

TCADOpt is simulator-agnostic. It does not hardcode any vendor's tool names.
Instead it builds two shell commands from the settings below:

    structure step :  <STRUCTURE_TOOL> <STRUCTURE_ARGS...> <structure_file>
    device step    :  <DEVICE_TOOL>    <DEVICE_ARGS...>    <device_file>

The structure step builds the device geometry and mesh. The device step runs
the electrical simulation and writes a results file. Point these at whatever
tools your simulator provides.

Configure without editing this file by setting environment variables:

    export TCADOPT_STRUCTURE_TOOL="my_structure_builder"
    export TCADOPT_STRUCTURE_ARGS="-batch -input"
    export TCADOPT_DEVICE_TOOL="my_device_solver"
    export TCADOPT_DEVICE_ARGS=""

Timeouts (seconds) can also be set:

    export TCADOPT_STRUCTURE_TIMEOUT=600
    export TCADOPT_DEVICE_TIMEOUT=3600

See docs/CONNECTING_A_SIMULATOR.md for the full integration guide.
"""
import os


def _env(name, default):
    return os.environ.get(name, default)


def _env_list(name, default):
    """Whitespace-separated argument list from an environment variable."""
    raw = os.environ.get(name)
    if raw is None:
        return list(default)
    raw = raw.strip()
    return raw.split() if raw else []


def _env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# --- the structure / mesh building tool ---------------------------------
STRUCTURE_TOOL = _env("TCADOPT_STRUCTURE_TOOL", "structure-tool-not-set")
STRUCTURE_ARGS = _env_list("TCADOPT_STRUCTURE_ARGS", [])
STRUCTURE_TIMEOUT = _env_int("TCADOPT_STRUCTURE_TIMEOUT", 900)

# --- the filename the engine writes the tuned parameters into ------------
# The engine renders each candidate design's parameter values into this file
# inside the run directory; your structure deck reads it. Change it if your
# toolchain expects a different include-file name or extension.
PARAM_FILE = _env("TCADOPT_PARAM_FILE", "params.txt")

# How each tuned parameter is written into the parameter file. {name} and
# {value} are substituted. The default suits many deck languages; change it
# for yours. Examples:
#   "{name} = {value}"          ->  NSD = 3.100000e+20
#   "(define {name} {value})"   ->  (define NSD 3.100000e+20)
#   "set {name} {value}"        ->  set NSD 3.100000e+20
PARAM_LINE_FORMAT = _env("TCADOPT_PARAM_LINE_FORMAT", "{name} = {value}")

# Comment marker for the auto-generated header line in the parameter file.
PARAM_COMMENT = _env("TCADOPT_PARAM_COMMENT", "#")

# --- the electrical device simulation tool -------------------------------
DEVICE_TOOL = _env("TCADOPT_DEVICE_TOOL", "device-tool-not-set")
DEVICE_ARGS = _env_list("TCADOPT_DEVICE_ARGS", [])
DEVICE_TIMEOUT = _env_int("TCADOPT_DEVICE_TIMEOUT", 5400)


def param_filename():
    """Name of the include file the engine writes tuned parameters into."""
    return PARAM_FILE


def render_param_line(name, value):
    """Format one tuned parameter as a line for the parameter file."""
    return PARAM_LINE_FORMAT.format(name=name, value="%.6e" % float(value))


def param_comment():
    """Comment marker for the parameter-file header."""
    return PARAM_COMMENT


def structure_command(structure_file):
    """Full command list for the structure/mesh build step."""
    return [STRUCTURE_TOOL] + list(STRUCTURE_ARGS) + [structure_file]


def device_command(device_file):
    """Full command list for the electrical simulation step."""
    return [DEVICE_TOOL] + list(DEVICE_ARGS) + [device_file]


def configured():
    """True if the user has set their simulator tools (not the placeholders)."""
    return ("not-set" not in STRUCTURE_TOOL) and ("not-set" not in DEVICE_TOOL)


def load_deck_sets(path=None):
    """Load the user's deck configuration from decks.yaml.

    Returns a dict: device_class -> {structure, device, mesh, result, vdd, ...}.
    The engine used to hardcode this; now it is user-editable data.
    """
    import yaml
    if path is None:
        here = os.path.dirname(os.path.abspath(__file__))
        root = os.path.abspath(os.path.join(here, "..", ".."))
        path = os.environ.get("TCADOPT_DECKS",
                              os.path.join(root, "decks.yaml"))
    if not os.path.exists(path):
        raise FileNotFoundError(
            "deck configuration not found: %s\n"
            "Copy decks.yaml into your repository root and edit it to point at "
            "your own deck files. See docs/CONNECTING_A_SIMULATOR.md." % path)
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    sets = data.get("deck_sets", data)
    if not sets:
        raise ValueError("no deck_sets defined in %s" % path)
    return sets


def describe():
    """Human-readable summary of the current simulator configuration."""
    status = "CONFIGURED" if configured() else \
        "NOT CONFIGURED  <-- set the two environment variables below"
    return (
        "TCADOpt simulator configuration  [%s]\n" % status +
        "  structure step : %s %s <structure_file>   (timeout %ds)\n"
        "  device step    : %s %s <device_file>      (timeout %ds)\n"
        "  param file     : %s\n"
        % (STRUCTURE_TOOL, " ".join(STRUCTURE_ARGS), STRUCTURE_TIMEOUT,
           DEVICE_TOOL, " ".join(DEVICE_ARGS), DEVICE_TIMEOUT, PARAM_FILE)
    )


if __name__ == "__main__":
    print(describe())
