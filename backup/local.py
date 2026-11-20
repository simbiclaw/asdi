"""Local SQLite dump, restore and one-restore drill with integrity checks."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

from ci.approval import utc_now, write_json_atomic

RECORD_SCHEMA = "asdi.phase7-backup-record/v1"


class BackupError(RuntimeError):
    """Raised when a dump or restore fails its integrity check."""


def _sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _readonly_connection(path: str | Path) -> sqlite3.Connection:
    database = Path(path).resolve()
    if not database.is_file():
        raise BackupError(f"database is missing: {database}")
    return sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)


def integrity_check(path: str | Path) -> str:
    try:
        with _readonly_connection(path) as connection:
            result = connection.execute("PRAGMA integrity_check").fetchall()
    except sqlite3.DatabaseError as error:
        raise BackupError(f"integrity check failed for {path}: {error}") from error
    if len(result) != 1 or result[0][0] != "ok":
        raise BackupError(f"integrity check failed for {path}: {result}")
    return "ok"


def dump_database(
    database: str | Path,
    dump_path: str | Path,
    *,
    record_path: str | Path | None = None,
) -> dict[str, Any]:
    source_path = Path(database).resolve()
    target_path = Path(dump_path).resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with _readonly_connection(source_path) as source, sqlite3.connect(target_path) as target:
        source.backup(target)
    check = integrity_check(target_path)
    record = {
        "schema_version": RECORD_SCHEMA,
        "operation": "dump",
        "database": str(source_path),
        "dump_path": str(target_path),
        "dump_sha256": _sha256(target_path),
        "integrity_check": check,
        "recorded_at": utc_now(),
    }
    if record_path is not None:
        written = write_json_atomic(record_path, record)
        record["record_path"] = str(written)
        write_json_atomic(written, record)
    return record


def restore_database(
    dump_path: str | Path,
    target: str | Path,
    *,
    record_path: str | Path | None = None,
) -> dict[str, Any]:
    dump = Path(dump_path).resolve()
    target_path = Path(target).resolve()
    check = integrity_check(dump)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{target_path.name}.restore-", suffix=".sqlite3", dir=target_path.parent
    )
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        temporary.unlink()
        with _readonly_connection(dump) as source, sqlite3.connect(temporary) as restored:
            source.backup(restored)
        restored_check = integrity_check(temporary)
        os.replace(temporary, target_path)
    finally:
        if temporary.exists():
            temporary.unlink()
    record = {
        "schema_version": RECORD_SCHEMA,
        "operation": "restore",
        "dump_path": str(dump),
        "target": str(target_path),
        "dump_sha256": _sha256(dump),
        "restored_sha256": _sha256(target_path),
        "dump_integrity_check": check,
        "restored_integrity_check": restored_check,
        "recorded_at": utc_now(),
    }
    if record_path is not None:
        written = write_json_atomic(record_path, record)
        record["record_path"] = str(written)
        write_json_atomic(written, record)
    return record


def _user_tables(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [str(row[0]) for row in rows]


def _snapshot(path: str | Path) -> dict[str, list[str]]:
    with _readonly_connection(path) as connection:
        return {
            table: sorted(repr(row) for row in connection.execute(f'SELECT * FROM "{table}"'))
            for table in _user_tables(connection)
        }


def run_restore_drill(
    database: str | Path,
    record_path: str | Path,
    *,
    work_dir: str | Path | None = None,
) -> dict[str, Any]:
    source_path = Path(database).resolve()
    with tempfile.TemporaryDirectory(prefix="asdi-restore-drill-", dir=work_dir) as temporary:
        workspace = Path(temporary)
        dump_record = dump_database(source_path, workspace / "snapshot.sqlite3")
        restored_path = workspace / "restored.sqlite3"
        restore_record = restore_database(dump_record["dump_path"], restored_path)
        source_snapshot = _snapshot(source_path)
        restored_snapshot = _snapshot(restored_path)
        row_counts = {
            table: {"source": len(rows), "restored": len(restored_snapshot.get(table, []))}
            for table, rows in source_snapshot.items()
        }
        passed = (
            source_snapshot == restored_snapshot
            and dump_record["integrity_check"] == "ok"
            and restore_record["restored_integrity_check"] == "ok"
        )
        record = {
            "schema_version": RECORD_SCHEMA,
            "operation": "restore_drill",
            "database": str(source_path),
            "dump_sha256": dump_record["dump_sha256"],
            "restored_sha256": restore_record["restored_sha256"],
            "dump_integrity_check": dump_record["integrity_check"],
            "restored_integrity_check": restore_record["restored_integrity_check"],
            "table_row_counts": row_counts,
            "passed": passed,
            "recorded_at": utc_now(),
        }
    written = write_json_atomic(record_path, record)
    record["record_path"] = str(written)
    write_json_atomic(written, record)
    if not passed:
        raise BackupError("restore drill did not reproduce the source database")
    return record


def _print(value: dict[str, Any]) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="asdi-phase7-backup")
    commands = parser.add_subparsers(dest="command", required=True)

    dump = commands.add_parser("dump")
    dump.add_argument("--db", required=True)
    dump.add_argument("--dump", required=True)
    dump.add_argument("--record", default=None)

    restore = commands.add_parser("restore")
    restore.add_argument("--dump", required=True)
    restore.add_argument("--target", required=True)
    restore.add_argument("--record", default=None)

    drill = commands.add_parser("drill")
    drill.add_argument("--db", required=True)
    drill.add_argument("--record", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        if arguments.command == "dump":
            result = dump_database(arguments.db, arguments.dump, record_path=arguments.record)
        elif arguments.command == "restore":
            result = restore_database(arguments.dump, arguments.target, record_path=arguments.record)
        else:
            result = run_restore_drill(arguments.db, arguments.record)
    except (BackupError, OSError, sqlite3.Error, ValueError) as error:
        print(f"backup command failed: {error}", file=sys.stderr)
        return 2
    _print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
