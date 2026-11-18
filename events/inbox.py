"""Durable event inbox and append-only audit log (REV K Pass 1 stand-in).

Build Guide V4 REV K section 18 puts the audit table in Archon's database and
section 4 puts event intake behind the ``events/`` seam (D-8). Pass 1 uses a
SQLite file behind this interface; moving to Archon's Postgres is a backend
swap, not a behaviour change.

Guarantees:
- an event is recorded at most once per (source, source_id);
- at most one handling per subject is in progress at a time;
- a newer event for a subject supersedes older pending ones (a new PR head
  invalidates earlier verdicts, Guide section 9.4);
- a claim whose lease lapses returns to pending; after ``max_attempts`` the
  event is marked failed and never retried automatically.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PENDING = "pending"
IN_PROGRESS = "in_progress"
DONE = "done"
FAILED = "failed"
SUPERSEDED = "superseded"


@dataclass(frozen=True)
class Event:
    id: int
    source: str
    source_id: str
    subject: str
    kind: str
    payload: dict[str, Any]
    status: str
    attempts: int


_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    subject     TEXT NOT NULL,
    kind        TEXT NOT NULL,
    payload     TEXT NOT NULL,
    status      TEXT NOT NULL,
    attempts    INTEGER NOT NULL DEFAULT 0,
    lease_until REAL,
    recorded_at REAL NOT NULL,
    updated_at  REAL NOT NULL,
    outcome     TEXT,
    UNIQUE (source, source_id)
);
CREATE INDEX IF NOT EXISTS events_subject ON events (subject, status);
CREATE TABLE IF NOT EXISTS audit (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    at    REAL NOT NULL,
    name  TEXT NOT NULL,
    data  TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;
CREATE TABLE IF NOT EXISTS health (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Inbox:
    def __init__(self, path: str | Path, *, clock: Any = time.time) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._db = sqlite3.connect(str(self.path), isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        self._db.close()

    # -- transactions -----------------------------------------------------
    def _tx(self) -> "_Tx":
        return _Tx(self._db)

    # -- audit ------------------------------------------------------------
    def audit(self, name: str, **data: Any) -> None:
        self._db.execute(
            "INSERT INTO audit (at, name, data) VALUES (?, ?, ?)",
            (self._clock(), name, json.dumps(data, sort_keys=True)),
        )

    def audit_rows(self) -> list[tuple[str, dict[str, Any]]]:
        return [
            (row["name"], json.loads(row["data"]))
            for row in self._db.execute("SELECT name, data FROM audit ORDER BY id")
        ]

    # -- health -----------------------------------------------------------
    def set_health(self, key: str, value: Any) -> None:
        self._db.execute(
            "INSERT INTO health (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )

    def health(self, key: str) -> Any:
        row = self._db.execute("SELECT value FROM health WHERE key = ?", (key,)).fetchone()
        return None if row is None else json.loads(row["value"])

    # -- events -----------------------------------------------------------
    def record(
        self,
        *,
        source: str,
        source_id: str,
        subject: str,
        kind: str,
        payload: dict[str, Any],
    ) -> bool:
        """Record an event. Returns False when it was already recorded."""
        now = self._clock()
        with self._tx():
            cursor = self._db.execute(
                "INSERT OR IGNORE INTO events "
                "(source, source_id, subject, kind, payload, status, recorded_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (source, source_id, subject, kind, json.dumps(payload, sort_keys=True), PENDING, now, now),
            )
            if cursor.rowcount == 0:
                return False
            new_id = cursor.lastrowid
            self._db.execute(
                "UPDATE events SET status = ?, outcome = ?, updated_at = ? "
                "WHERE subject = ? AND kind = ? AND status = ? AND id != ?",
                (SUPERSEDED, "superseded by a newer event", now, subject, kind, PENDING, new_id),
            )
        return True

    def supersede(self, event_id: int, reason: str) -> None:
        self._finish(event_id, SUPERSEDED, reason)

    def claim(self, *, lease_seconds: float, max_attempts: int, exclude: set[int] = frozenset()) -> Event | None:
        """Claim the oldest pending event whose subject has no active handling."""
        now = self._clock()
        with self._tx():
            # Expired leases return to pending, or fail when attempts are spent.
            for row in self._db.execute(
                "SELECT id, attempts FROM events WHERE status = ? AND lease_until < ?",
                (IN_PROGRESS, now),
            ).fetchall():
                if row["attempts"] >= max_attempts:
                    self._db.execute(
                        "UPDATE events SET status = ?, outcome = ?, lease_until = NULL, updated_at = ? WHERE id = ?",
                        (FAILED, "lease expired; attempts exhausted", now, row["id"]),
                    )
                else:
                    self._db.execute(
                        "UPDATE events SET status = ?, lease_until = NULL, updated_at = ? WHERE id = ?",
                        (PENDING, now, row["id"]),
                    )
            skip = ",".join(str(int(i)) for i in exclude) or "-1"
            row = self._db.execute(
                "SELECT * FROM events e WHERE e.status = ? AND e.id NOT IN (" + skip + ") AND NOT EXISTS ("
                "  SELECT 1 FROM events a WHERE a.subject = e.subject AND a.status = ?"
                ") ORDER BY e.id LIMIT 1",
                (PENDING, IN_PROGRESS),
            ).fetchone()
            if row is None:
                return None
            self._db.execute(
                "UPDATE events SET status = ?, attempts = attempts + 1, lease_until = ?, updated_at = ? WHERE id = ?",
                (IN_PROGRESS, now + lease_seconds, now, row["id"]),
            )
            return _event(self._db.execute("SELECT * FROM events WHERE id = ?", (row["id"],)).fetchone())

    def complete(self, event_id: int, outcome: str) -> None:
        self._finish(event_id, DONE, outcome)

    def release(self, event_id: int, *, max_attempts: int, reason: str) -> str:
        """Return a failed attempt to pending, or mark the event failed."""
        row = self._db.execute("SELECT attempts FROM events WHERE id = ?", (event_id,)).fetchone()
        if row is not None and row["attempts"] >= max_attempts:
            self._finish(event_id, FAILED, reason)
            return FAILED
        self._db.execute(
            "UPDATE events SET status = ?, lease_until = NULL, outcome = ?, updated_at = ? WHERE id = ?",
            (PENDING, reason, self._clock(), event_id),
        )
        return PENDING

    def _finish(self, event_id: int, status: str, outcome: str) -> None:
        self._db.execute(
            "UPDATE events SET status = ?, outcome = ?, lease_until = NULL, updated_at = ? WHERE id = ?",
            (status, outcome, self._clock(), event_id),
        )

    def events(self, status: str | None = None) -> list[Event]:
        if status is None:
            rows = self._db.execute("SELECT * FROM events ORDER BY id").fetchall()
        else:
            rows = self._db.execute("SELECT * FROM events WHERE status = ? ORDER BY id", (status,)).fetchall()
        return [_event(row) for row in rows]


class _Tx:
    def __init__(self, db: sqlite3.Connection) -> None:
        self._db = db

    def __enter__(self) -> None:
        self._db.execute("BEGIN IMMEDIATE")

    def __exit__(self, exc_type: Any, *_: Any) -> None:
        self._db.execute("ROLLBACK" if exc_type else "COMMIT")


def _event(row: sqlite3.Row) -> Event:
    return Event(
        id=row["id"],
        source=row["source"],
        source_id=row["source_id"],
        subject=row["subject"],
        kind=row["kind"],
        payload=json.loads(row["payload"]),
        status=row["status"],
        attempts=row["attempts"],
    )
