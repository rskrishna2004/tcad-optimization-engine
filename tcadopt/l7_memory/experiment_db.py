"""l7_memory.experiment_db -- the experiment database (P0 keystone).

Generalizes the old master.csv into a queryable, provenanced store of EVERY trial
ever run, across all problems. Pure-stdlib (sqlite3 + json) so it runs on bare
Python 3.6.8; optional parquet export if pandas/pyarrow are present.

This is the substrate for "learn from every simulation": surrogate fits, transfer/
warm-start, and KB curation all read from here.

$Id: experiment_db.py, 2026/06/18 [YOUR NAME] $
"""
import os
import json
import time
import sqlite3
import hashlib
import subprocess
from datetime import datetime

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trials (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    problem_id       TEXT NOT NULL,
    campaign         TEXT,
    trial_id         TEXT,
    params_json      TEXT,
    encoded_json     TEXT,
    models_json      TEXT,
    fidelity_json    TEXT,
    metrics_json     TEXT,
    score            REAL,
    status           TEXT,          -- ok | failed | repaired
    failure_class    TEXT,
    repair_applied   TEXT,
    seed             INTEGER,
    code_version     TEXT,
    deck_hash        TEXT,
    wall_time        REAL,
    created_at       TEXT
);
CREATE INDEX IF NOT EXISTS idx_problem  ON trials(problem_id);
CREATE INDEX IF NOT EXISTS idx_status   ON trials(status);
CREATE INDEX IF NOT EXISTS idx_campaign ON trials(campaign);
"""


def code_version(repo_dir=None):
    """Best-effort provenance: short git hash, else 'nogit'."""
    try:
        out = subprocess.check_output(
            ["git", "-C", repo_dir or ".", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL)
        return out.decode().strip()
    except Exception:
        return "nogit"


def deck_hash(text):
    """Stable short hash of a rendered deck (reproducibility link)."""
    if text is None:
        return None
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def _dumps(obj):
    return None if obj is None else json.dumps(obj, sort_keys=True)


class ExperimentDB(object):
    """Thin, robust wrapper over a SQLite trials table."""

    def __init__(self, path):
        self.path = path
        d = os.path.dirname(os.path.abspath(path))
        if d and not os.path.isdir(d):
            os.makedirs(d)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    # -- write -------------------------------------------------------------
    def record(self, problem_id, params=None, metrics=None, status="ok",
               score=None, campaign=None, trial_id=None, encoded=None,
               models=None, fidelity=None, failure_class=None,
               repair_applied=None, seed=None, code_ver=None, deck=None,
               wall_time=None):
        """Insert one trial. Returns the row id. Dict fields are JSON-encoded."""
        row = (
            problem_id, campaign, trial_id,
            _dumps(params), _dumps(encoded), _dumps(models),
            _dumps(fidelity), _dumps(metrics), score, status,
            failure_class, repair_applied, seed,
            code_ver if code_ver is not None else code_version(),
            deck_hash(deck) if deck is not None else None,
            wall_time, datetime.now().isoformat(),
        )
        cur = self.conn.execute(
            "INSERT INTO trials (problem_id,campaign,trial_id,params_json,"
            "encoded_json,models_json,fidelity_json,metrics_json,score,status,"
            "failure_class,repair_applied,seed,code_version,deck_hash,wall_time,"
            "created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
        self.conn.commit()
        return cur.lastrowid

    def record_many(self, problem_id, rows, **common):
        """rows: iterable of dicts with keys matching record() kwargs."""
        ids = []
        for r in rows:
            kw = dict(common)
            kw.update(r)
            ids.append(self.record(problem_id, **kw))
        return ids

    # -- read --------------------------------------------------------------
    def _rows_to_dicts(self, rows):
        out = []
        for r in rows:
            d = dict(r)
            for k in ("params_json", "encoded_json", "models_json",
                      "fidelity_json", "metrics_json"):
                if d.get(k):
                    d[k[:-5]] = json.loads(d[k])   # params_json -> params
                del d[k]
            out.append(d)
        return out

    def query(self, problem_id=None, status=None, campaign=None, limit=None):
        sql = "SELECT * FROM trials"
        clauses, args = [], []
        if problem_id is not None:
            clauses.append("problem_id=?"); args.append(problem_id)
        if status is not None:
            clauses.append("status=?"); args.append(status)
        if campaign is not None:
            clauses.append("campaign=?"); args.append(campaign)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id"
        if limit:
            sql += " LIMIT %d" % int(limit)
        return self._rows_to_dicts(self.conn.execute(sql, args).fetchall())

    def best(self, problem_id, n=1, by="score", desc=True):
        """Top-n successful trials by a column (default highest score)."""
        order = "DESC" if desc else "ASC"
        sql = ("SELECT * FROM trials WHERE problem_id=? AND status='ok' "
               "AND %s IS NOT NULL ORDER BY %s %s LIMIT ?" % (by, by, order))
        return self._rows_to_dicts(
            self.conn.execute(sql, (problem_id, n)).fetchall())

    def history_encoded(self, problem_id, campaign=None):
        """Return (X, y) for surrogate fitting: encoded vectors + scores of
        successful trials. X is a list of lists, y a list of floats."""
        rows = self.query(problem_id=problem_id, status="ok", campaign=campaign)
        X, y = [], []
        for r in rows:
            if r.get("encoded") is not None and r.get("score") is not None:
                X.append(r["encoded"]); y.append(r["score"])
        return X, y

    def stats(self, problem_id=None):
        where = "" if problem_id is None else " WHERE problem_id=?"
        args = [] if problem_id is None else [problem_id]
        total = self.conn.execute(
            "SELECT COUNT(*) FROM trials" + where, args).fetchone()[0]
        byst = {}
        for st, c in self.conn.execute(
                "SELECT status, COUNT(*) FROM trials" + where +
                (" GROUP BY status" if where else " GROUP BY status"), args):
            byst[st] = c
        return {"total": total, "by_status": byst}

    # -- export ------------------------------------------------------------
    def export_parquet(self, path, problem_id=None):
        """Optional: flatten to parquet if pandas is available; else no-op+warn."""
        try:
            import pandas as pd
        except ImportError:
            print("[experiment_db] pandas not available; skipping parquet "
                  "(sqlite remains the source of truth).")
            return False
        recs = self.query(problem_id=problem_id)
        flat = []
        for r in recs:
            base = {k: r.get(k) for k in (
                "id", "problem_id", "campaign", "trial_id", "score", "status",
                "failure_class", "seed", "code_version", "deck_hash",
                "wall_time", "created_at")}
            for mk, mv in (r.get("metrics") or {}).items():
                base["metric." + mk] = mv
            for pk, pv in (r.get("params") or {}).items():
                base["param." + pk] = pv
            flat.append(base)
        pd.DataFrame(flat).to_parquet(path, index=False)
        return True

    def close(self):
        self.conn.close()


if __name__ == "__main__":
    # self-test (runs on bare stdlib)
    import tempfile
    p = os.path.join(tempfile.mkdtemp(), "exp.db")
    db = ExperimentDB(p)
    db.record("demo_problem",
              params={"LG": 0.056, "NSUB": 7.0e16, "NPOLY": 2.5e20},
              encoded=[0.1, 0.4, 0.55],
              metrics={"ION_A_per_um": 4.54e-4, "IOFF_A_per_um": 9.36e-8},
              score=-4.2823, status="ok", campaign="hp", seed=1, deck="* deck text")
    db.record("demo_problem",
              params={"LG": 0.059, "NSUB": 1.3e17},
              encoded=[0.2, 0.5, 0.30],
              metrics={"ION_A_per_um": 3.65e-4, "IOFF_A_per_um": 9.2e-9},
              score=-4.3849, status="ok", campaign="std", seed=2)
    db.record("demo_problem", params={"LG": 0.04}, status="failed",
              failure_class="convergence_stall", campaign="std", seed=3)
    print("stats:", db.stats("demo_problem"))
    print("best :", [(r["campaign"], r["score"]) for r in db.best("demo_problem", n=2)])
    X, y = db.history_encoded("demo_problem")
    print("history_encoded: X rows=%d y=%s" % (len(X), y))
    print("code_version:", code_version(), "| deck_hash:", deck_hash("* deck text"))
    db.close()
    print("experiment_db self-test OK ->", p)
