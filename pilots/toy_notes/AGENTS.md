# toy-notes product requests

The four REV K documents in `reference/AUTHORITY.md` are authoritative. Build Guide V4 §6 and §13.3 govern this product and its harness.

- Prove behaviour on the real CLI, HTTP server, SQLite file and rendered UI; compilation is not proof.
- Reproduce a defect before changing code, and fix the root cause.
- Keep changes to one feature at a time, with a proof that verifies on its own.
- Drive public interfaces as a user would and compare against literal expected values.
- Name the limits of every measured result in the feature file.
- Do not wait on a human for a reversible local change; record it in `DECISIONS.tsv` for long runs.
- After a repeated correction, add a check instead of more prose.
- Write the failing proof first when a cheap local path exists.

Product source is limited to `src/toy_notes/`. Every file there must be owned by at least one feature path glob. The feature map and static-gate manifest are read from the trusted base branch, never from the candidate head. Evidence lives only under `ASDI_EVIDENCE_DIR` (or a run-owned temp path) and cleanup never deletes it.

Local controls: `NOTES_UI_ENABLED` turns on the UI route only and defaults off. `TOY_NOTES_INJECT_DEFECT=create` is a reversible test-only switch that makes note creation fail. Both are process-local; no secrets, external services, customer data or production endpoints are used.
