"""l3_exec.execute -- the the TCAD simulator evaluator.

Wraps the proven runner.run_one / dispatch.run_batch (parallel, process-group-safe)
and attaches a failure class to each result. Presents a single evaluate_batch()
interface that the orchestrator calls; a synthetic evaluator with the same interface
is used for testing the loop without the TCAD simulator (see tests/).

If metric_config is given (from CompiledProblem.metric_config), the rich FoM library
re-parses each trial's IdVg .plt and merges the full metric set (gm/Id, Vt, SS, ...)
into result['metrics'] so the scorer can target any figure of merit.

$Id: execute.py, 2026/06/18 [YOUR NAME] $
"""
import os
import sys

from .failures import classify

_DEF_LEGACY = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "optimizer")


def _load_legacy(legacy_dir=None):
    legacy_dir = legacy_dir or os.environ.get("TCADOPT_LEGACY", _DEF_LEGACY)
    if legacy_dir not in sys.path:
        sys.path.insert(0, legacy_dir)
    import runner    # noqa: E402
    import dispatch  # noqa: E402
    return runner, dispatch


class TCADEvaluator(object):
    """evaluate_batch(param_dicts, tag) -> list of result dicts (order-preserving).

    Each result is runner.run_one's dict, augmented with failure_class and run_dir.
    When metric_config is set, the rich FoM set is merged into result['metrics'].
    """

    name = "tcad_simulator"

    def __init__(self, legacy_dir=None, n_parallel=8, metric_config=None,
                 plt_name="nmos_idvg.plt", deck="nmos"):
        self.runner, self.dispatch = _load_legacy(legacy_dir)
        self.n_parallel = n_parallel
        self.metric_config = metric_config or {}
        self.plt_name = plt_name
        self.deck = deck

    def _enrich(self, r):
        if not self.metric_config or r.get("status") != "ok":
            return
        plt = os.path.join(r["run_dir"], self.plt_name)
        if not os.path.exists(plt):
            return
        try:
            from .metrics import metrics_from_plt
            rich = metrics_from_plt(
                plt, vdd=self.metric_config.get("vdd", 1.0),
                vt_icrit=self.metric_config.get("vt_icrit", 1.0e-7),
                id_targets=tuple(self.metric_config.get("id_targets", ())))
            base = r.get("metrics") or {}
            base.update(rich)
            r["metrics"] = base
        except Exception as exc:
            r.setdefault("metric_warn", str(exc))

    def evaluate_batch(self, param_dicts, tag="b"):
        results = self.dispatch.run_batch(
            list(param_dicts), n_parallel=self.n_parallel, tag=tag, deck=self.deck)
        for r in results:
            run_dir = os.path.join(self.runner.RUNS, "run_%s" % r["run_id"])
            klass, detail = classify(r, run_dir=run_dir)
            r["failure_class"] = klass
            r["failure_detail"] = detail
            r["run_dir"] = run_dir
            self._enrich(r)
        return results
