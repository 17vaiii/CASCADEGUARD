"""Durable local audit trail for advisory recommendations and verification."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_DB = Path(os.getenv("CASCADEGUARD_AUDIT_DB", "data/audit/recommendations.sqlite3"))


def _connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path or DEFAULT_DB)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS recommendation_audit (
        audit_id TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        recommendation_json TEXT NOT NULL,
        verification_json TEXT,
        data_refs_json TEXT NOT NULL,
        data_fingerprint TEXT
    )""")
    conn.commit()
    return conn


@contextmanager
def _connection(db_path: str | Path | None = None):
    conn = _connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def create_recommendation(
    recommendation: dict[str, Any] | list[Any] | str,
    data_refs: list[str] | None = None,
    data_fingerprint: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Record advice and provenance without storing raw consumer/grid inputs."""
    refs = data_refs or []
    if data_fingerprint is None:
        canonical = json.dumps({"recommendation": recommendation, "data_refs": refs},
                               sort_keys=True, separators=(",", ":"), default=str)
        data_fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
    audit_id = uuid.uuid4().hex
    created_at = datetime.now(timezone.utc).isoformat()
    with _connection(db_path) as conn:
        conn.execute(
            "INSERT INTO recommendation_audit VALUES (?, ?, ?, NULL, ?, ?)",
            (audit_id, created_at, json.dumps(recommendation, default=str),
             json.dumps(refs), data_fingerprint),
        )
    return {"audit_id": audit_id, "created_at": created_at,
            "verification": None, "data_fingerprint": data_fingerprint}


def record_verification(audit_id: str, verification: dict[str, Any],
                        db_path: str | Path | None = None) -> dict[str, Any] | None:
    verified_at = datetime.now(timezone.utc).isoformat()
    value = {**verification, "verified_at": verified_at}
    with _connection(db_path) as conn:
        cursor = conn.execute(
            "UPDATE recommendation_audit SET verification_json=? WHERE audit_id=?",
            (json.dumps(value, default=str), audit_id),
        )
        if cursor.rowcount == 0:
            return None
    return {"audit_id": audit_id, "verification": value}


def get_audit(audit_id: str, db_path: str | Path | None = None) -> dict[str, Any] | None:
    with _connection(db_path) as conn:
        row = conn.execute("SELECT * FROM recommendation_audit WHERE audit_id=?", (audit_id,)).fetchone()
    if row is None:
        return None
    return {"audit_id": row["audit_id"], "created_at": row["created_at"],
            "recommendation": json.loads(row["recommendation_json"]),
            "verification": json.loads(row["verification_json"]) if row["verification_json"] else None,
            "data_refs": json.loads(row["data_refs_json"]),
            "data_fingerprint": row["data_fingerprint"]}
