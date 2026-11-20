# Toy Notes Product Verification

## 1. Surface

`toy-notes` is one Python process with a stdlib HTTP server, a SQLite file, a CLI and a server-rendered UI page. The trusted feature map is `verify/features/`; each feature declares its source paths, drive command, literal proof, negative control and limits. Select features from changed product paths, never from an agent claim. Product source lives under `src/toy_notes/`.

## 2. Launch

`verify launch` starts the candidate product from `ASDI_HEAD` (or the current product root) on a run-owned loopback port and stores its pid, port and database path under `$ASDI_EVIDENCE_DIR/run/launch.json`. The harness enables `NOTES_UI_ENABLED` for its own launch so the UI proof can run; the product default remains off. Running `verify` with no subcommand performs the full sequence for the changed features, or all features when no source diff is available.

## 3. Doctor

`verify doctor` is read-only. It checks that the launched process is alive, that `/healthz` and `/readyz` answer as expected, that the SQLite file exists, and that every product source path is owned by at least one feature glob. It returns 2 when any check is blocked.

## 4. Drive

`verify drive <id>...` drives each selected feature through its real public interface. `verify drive --changed <base>..<head>` derives features by comparing filesystem trees and fails closed if any changed source path has no feature. Drive returns 0 only when every proof is `pass` and every control is `caught`; 1 means fail or missed, 2 means blocked or error.

## 5. Observe

Observe side effects, not only action success: read the SQLite row, export file, follow-up API response or rendered HTML. Do not accept a green exit code without the expected stored or returned value. Capture stdout, stderr and observed state as evidence files.

## 6. Isolate

Each feature uses its own run-owned database and port. UI proofs start separate flagged and unflagged processes; controls use a separate process with `TOY_NOTES_INJECT_DEFECT=create`. Stop only processes this harness started. A `blocked` or `error` status is never retried into a pass by changing the expected value.

## 7. Evidence

All files go under `$ASDI_EVIDENCE_DIR`, including `result.json` on every drive. `result.json` has schema 2, a `r-...` run id, the commit, and one entry per feature with status, control, relative evidence paths and non-empty limits. Cleanup never deletes evidence.

## 8. Cleanup

`verify cleanup` terminates only the pid recorded by `verify launch` and leaves the evidence directory intact. It is safe to call more than once.

## 9. Limits

The harness proves local CLI, JSON HTTP and server-rendered UI behaviour against synthetic data. It does not exercise browsers, authentication, TLS, concurrency, external services or production data. A passing proof covers only its declared feature and limits; only an ASDI-run verification with caught controls counts as phase acceptance.
