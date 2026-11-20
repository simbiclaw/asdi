from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFECT_ENV = "TOY_NOTES_INJECT_DEFECT"
DEFECT_CREATE = "create"


class NoteCreationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Note:
    id: int
    title: str
    body: str
    created_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "body": self.body,
            "created_at": self.created_at,
        }


class NoteStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS notes ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "title TEXT NOT NULL, "
                    "body TEXT NOT NULL, "
                    "created_at TEXT NOT NULL)"
                )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path), timeout=5.0)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def defect_active() -> bool:
        return os.environ.get(DEFECT_ENV) == DEFECT_CREATE

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _note(row: sqlite3.Row) -> Note:
        return Note(
            id=int(row["id"]),
            title=str(row["title"]),
            body=str(row["body"]),
            created_at=str(row["created_at"]),
        )

    def create(self, title: str, body: str = "") -> dict[str, Any]:
        if self.defect_active():
            raise NoteCreationError("defect injection: note creation disabled")
        cleaned_title = title.strip()
        if not cleaned_title:
            raise ValueError("title must not be empty")
        with closing(self._connect()) as connection:
            with connection:
                cursor = connection.execute(
                    "INSERT INTO notes (title, body, created_at) VALUES (?, ?, ?)",
                    (cleaned_title, body, self._now()),
                )
                note_id = int(cursor.lastrowid)
                row = connection.execute(
                    "SELECT id, title, body, created_at FROM notes WHERE id = ?",
                    (note_id,),
                ).fetchone()
        if row is None:
            raise RuntimeError("inserted note disappeared")
        return self._note(row).as_dict()

    def list(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT id, title, body, created_at FROM notes ORDER BY id"
            ).fetchall()
        return [self._note(row).as_dict() for row in rows]

    def get(self, note_id: int) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT id, title, body, created_at FROM notes WHERE id = ?",
                (note_id,),
            ).fetchone()
        return None if row is None else self._note(row).as_dict()

    def export_json(self) -> str:
        return json.dumps(self.list(), indent=2, sort_keys=True) + "\n"

    def count(self) -> int:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT COUNT(*) AS total FROM notes").fetchone()
        return int(row["total"])
