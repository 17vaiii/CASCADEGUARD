"""SQLite persistence for simulation configurations and detection runs (experiment history).

Only configurations, hashes and results are stored. Datasets themselves are regenerated
from (configuration, seed), which is cheaper than storing them and doubles as a
reproducibility check (the regenerated data hash must match the stored one).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS simulations (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    label TEXT,
    scenario TEXT NOT NULL,
    seed INTEGER NOT NULL,
    config_json TEXT NOT NULL,
    rules_json TEXT,
    data_hash TEXT NOT NULL,
    summary_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS detections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    simulation_id TEXT NOT NULL REFERENCES simulations(id),
    created_at TEXT NOT NULL,
    step INTEGER NOT NULL,
    consumer_method TEXT NOT NULL,
    unit_method TEXT NOT NULL,
    n_alerts INTEGER NOT NULL,
    compute_ms REAL NOT NULL,
    result_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_detections_sim ON detections(simulation_id);
"""


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def save_simulation(self, sim_id: str, config: dict, rules: dict | None, data_hash: str, summary: dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO simulations VALUES (?,?,?,?,?,?,?,?,?)",
                (sim_id, datetime.now().isoformat(timespec="seconds"), config.get("label"), config["scenario"],
                 config["seed"], json.dumps(config), json.dumps(rules) if rules else None, data_hash,
                 json.dumps(summary, default=str)),
            )
            self._conn.commit()

    def get_simulation(self, sim_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM simulations WHERE id=?", (sim_id,)).fetchone()
        if row is None:
            return None
        return {"id": row["id"], "created_at": row["created_at"], "label": row["label"], "scenario": row["scenario"],
                "seed": row["seed"], "config": json.loads(row["config_json"]),
                "rules": json.loads(row["rules_json"]) if row["rules_json"] else None, "data_hash": row["data_hash"]}

    def list_simulations(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT s.id, s.created_at, s.label, s.scenario, s.seed, s.data_hash, "
                "(SELECT COUNT(*) FROM detections d WHERE d.simulation_id = s.id) AS n_detections "
                "FROM simulations s ORDER BY s.created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def save_detection(self, sim_id: str, step: int, consumer_method: str, unit_method: str, n_alerts: int,
                       compute_ms: float, result: dict) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO detections (simulation_id, created_at, step, consumer_method, unit_method, n_alerts, "
                "compute_ms, result_json) VALUES (?,?,?,?,?,?,?,?)",
                (sim_id, datetime.now().isoformat(timespec="seconds"), step, consumer_method, unit_method, n_alerts,
                 compute_ms, json.dumps(result, default=str)))
            self._conn.commit()
            return int(cur.lastrowid)

    def list_detections(self, sim_id: str | None = None, limit: int = 100) -> list[dict]:
        q = ("SELECT id, simulation_id, created_at, step, consumer_method, unit_method, n_alerts, compute_ms "
             "FROM detections")
        args: tuple = ()
        if sim_id:
            q += " WHERE simulation_id=?"
            args = (sim_id,)
        q += " ORDER BY id DESC LIMIT ?"
        with self._lock:
            rows = self._conn.execute(q, args + (limit,)).fetchall()
        return [dict(r) for r in rows]
