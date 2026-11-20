---
{
  "id": "ui-note-list",
  "title": "Flagged UI note list and create form",
  "paths": ["src/toy_notes/server.py"],
  "class_floor": "agent-mergeable",
  "drive": {
    "kind": "ui",
    "url": "/notes/ui",
    "command": "GET /notes/ui with notes_ui_enabled off then on; POST form /notes title=ui-proof; GET /notes/ui"
  },
  "proof": {
    "http_status": 200,
    "contains": "<form"
  },
  "negative_control": {
    "mutate": "env TOY_NOTES_INJECT_DEFECT=create NOTES_UI_ENABLED=1 POST /notes form title=control; expect failure and no UI row",
    "expect": "fail"
  },
  "limits": [
    "The UI is server-rendered HTML checked through a real HTTP boundary; no browser engine or JavaScript is used.",
    "Accessibility and visual layout are not evaluated.",
    "The proof checks that other routes are unchanged by the flag, not every possible route combination."
  ]
}
---
## User-visible behaviour

With `notes_ui_enabled` off, the UI route is unavailable. With the flag on, the same process serves an HTML note list and create form; other routes do not change.

## Reach

`GET /notes/ui` and the form POST to `/notes` on the run-owned loopback server.

## Drive

Start an unflagged server and confirm `/notes/ui` returns 404. Use the flagged server, confirm the HTML form and seeded row, submit `ui-proof` as form data, then confirm the new title appears in the HTML and SQLite.

## Proof

The default-off route is 404 JSON, the enabled route is 200 HTML containing `<form` and the seeded title, and the submitted title appears in the list with one new row. Non-UI responses are byte-identical across the flag states after normalising dynamic timestamps.

## Gotchas

The harness enables the flag only when it launches the product. The negative control uses a separate injected process with a seeded database so a failed create cannot be mistaken for an empty list.
