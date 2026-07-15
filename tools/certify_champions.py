"""Certify the champions of a completed campaign (best-per-cap from the experiment DB).

Run after a warm-started campaign:
  cd ~/tcad_opt && python3 -m tools.certify_champions problems/nmos_planar_caps.yaml
"""
import os
import sys
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tcadopt.l1_spec import compile                       # noqa: E402
from tcadopt.l7_memory import ExperimentDB                # noqa: E402
from tcadopt.l6_verify.certify import certify             # noqa: E402
from tcadopt.l8_orch.run_campaign import _default_db_path, _label  # noqa: E402


def main(spec_path, db_path=None):
    cp = compile(spec_path)
    db = ExperimentDB(db_path or _default_db_path())
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    certs = {}
    for cap in cp.cap_values:
        label = _label(cap)
        rows = [r for r in db.query(problem_id=cp.problem_id, status="ok",
                                    campaign=label) if r.get("score") is not None]
        if not rows:
            print("no champion recorded for %s" % label)
            continue
        champ = max(rows, key=lambda r: r["score"])
        print("\n" + "=" * 64)
        print("Certifying %s champion (score=%.4f) ..." % (label, champ["score"]))
        cert = certify(champ["params"], cp, label, cap, champ["metrics"])
        certs[label] = cert
        outp = os.path.join(ROOT, "results", "cert_%s.json" % label)
        json.dump(cert.to_dict(), open(outp, "w"), indent=1)
        print("  -> %s" % outp)
    print("\n" + "=" * 64)
    print("CERTIFICATION SUMMARY:",
          {k: ("PASS" if v.verdict else "FAIL") for k, v in certs.items()})


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m tools.certify_champions <spec.yaml>")
        sys.exit(1)
    main(sys.argv[1])
