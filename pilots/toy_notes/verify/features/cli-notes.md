---
{
  "id": "cli-notes",
  "title": "Create, list, read and export notes with the CLI",
  "paths": ["src/toy_notes/cli.py", "src/toy_notes/store.py"],
  "class_floor": "agent-mergeable",
  "drive": {
    "kind": "cli",
    "command": "python3 -m toy_notes.cli --db $DB create --title cli-proof --body synthetic && list && read --id 1 && export --out $OUT"
  },
  "proof": {
    "contains": "\"title\": \"cli-proof\""
  },
  "negative_control": {
    "mutate": "env TOY_NOTES_INJECT_DEFECT=create python3 -m toy_notes.cli --db $DB create --title control",
    "expect": "fail"
  },
  "limits": [
    "Only a local SQLite file and JSON output are covered.",
    "No concurrent CLI writers or large export files are exercised.",
    "The negative control uses the product's test-only injection switch, not a persistence fault."
  ]
}
---
## User-visible behaviour

An operator creates a note, lists notes, reads one note and exports all notes as JSON with a local command.

## Reach

`python3 -m toy_notes.cli` with a run-owned `--db` path. The process imports only the product source from the candidate head.

## Drive

Create `cli-proof`, list notes, read note 1 and export to a run-owned JSON file. Capture stdout, the export file and the SQLite row.

## Proof

The create, list, read and export outputs are valid JSON, the export title is `cli-proof`, and the SQLite row count increases by exactly one.

## Gotchas

The database path must be run-owned. The injection flag must be absent for the positive proof and present only for the negative control.
