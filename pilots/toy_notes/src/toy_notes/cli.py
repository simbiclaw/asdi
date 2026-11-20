from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

from .store import NoteCreationError, NoteStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="toy-notes", description="Synthetic local notes CLI")
    parser.add_argument(
        "--db",
        default=os.environ.get("TOY_NOTES_DB", "toy-notes.sqlite3"),
        help="SQLite file used by this invocation",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create", help="Create a note")
    create.add_argument("--title", required=True)
    create.add_argument("--body", default="")

    commands.add_parser("list", help="List notes as JSON")

    read = commands.add_parser("read", help="Read one note as JSON")
    read.add_argument("--id", type=int, required=True)

    export = commands.add_parser("export", help="Export notes as a JSON file")
    export.add_argument("--out", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    store = NoteStore(arguments.db)
    try:
        store.initialize()
        if arguments.command == "create":
            note = store.create(arguments.title, arguments.body)
            print(json.dumps(note, sort_keys=True))
        elif arguments.command == "list":
            print(json.dumps(store.list(), indent=2, sort_keys=True))
        elif arguments.command == "read":
            note = store.get(arguments.id)
            if note is None:
                print(f"error: note {arguments.id} not found", file=sys.stderr)
                return 2
            print(json.dumps(note, sort_keys=True))
        elif arguments.command == "export":
            output = Path(arguments.out)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(store.export_json(), encoding="utf-8")
            print(json.dumps({"exported": str(output), "count": store.count()}, sort_keys=True))
        else:
            raise AssertionError(f"unhandled command: {arguments.command}")
    except NoteCreationError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except (ValueError, sqlite3.Error, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
