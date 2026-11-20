---
{
  "id": "http-notes",
  "title": "Local JSON notes API with health, readiness and metrics",
  "paths": ["src/toy_notes/server.py", "src/toy_notes/store.py"],
  "class_floor": "agent-mergeable",
  "drive": {
    "kind": "http",
    "url": "/notes",
    "command": "urllib GET /healthz,/readyz,/metrics,/notes then POST /notes and GET /notes"
  },
  "proof": {
    "http_status": 200,
    "contains": "http-proof"
  },
  "negative_control": {
    "mutate": "env TOY_NOTES_INJECT_DEFECT=create POST /notes title=control; expect 500 and no SQLite row",
    "expect": "fail"
  },
  "limits": [
    "Only 127.0.0.1 and one process are exercised.",
    "Metrics text is checked for presence, not numerical accuracy under load.",
    "Authentication, TLS and external clients are out of scope."
  ]
}
---
## User-visible behaviour

A local client can check health and readiness, read metrics, list notes and create a note over HTTP.

## Reach

The single `toy_notes.server` process started by `verify launch`, bound to a run-owned loopback port.

## Drive

GET `/healthz`, `/readyz`, `/metrics` and `/notes`; POST a JSON note titled `http-proof`; GET `/notes` again and inspect the SQLite row.

## Proof

Health and readiness return 200 JSON, metrics include `toy_notes_requests_total`, the POST returns 201, and the second GET lists `http-proof` with one new row.

## Gotchas

The port comes from a run-owned port file, never a fixed value. A broken POST route must turn the proof red even when the process stays healthy.
