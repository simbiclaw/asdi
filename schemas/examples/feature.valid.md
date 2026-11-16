---
id: export-csv
title: Export notes as CSV
paths: ["src/export/**", "cli/export.py"]
class_floor: agent-mergeable
drive:
  kind: cli
  command: "notes export --format csv --out $OUT"
proof:
  compare: { file: "$OUT", equals: "fixtures/export/expected.csv" }
negative_control:
  mutate: "fixtures/export/broken-input.json"
  expect: fail
limits: ["Spreadsheet import not tested"]
---
## User-visible behaviour
Export saved notes.

## Reach
Run the notes CLI.

## Drive
Execute the drive command.

## Proof
Compare the output byte-for-byte.

## Gotchas
Line endings are normalized.
