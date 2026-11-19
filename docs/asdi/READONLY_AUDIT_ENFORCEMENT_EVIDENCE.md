# Read-only audit enforcement evidence

**Date:** 2026-11-18  
**Result:** **Enforcement wrapper implemented; Docker probe passed; owner must select auditor command**

## Wrapper boundary

[`tools/readonly_audit.py`](../../tools/readonly_audit.py) executes the auditor in Docker with:

- `--network none`;
- all Linux capabilities dropped;
- no-new-privileges;
- read-only container root;
- non-root user `1001:1001`;
- candidate, specifications and skill mounted read-only;
- only the report directory writable;
- no inherited host environment or Git credential helper;
- no Docker socket mount;
- a fail-closed default timeout.

The wrapper rejects auditor commands containing `docker`, the Docker socket path or token assignments. On timeout it writes an execution record with `timed_out=true` and exits `3`; it never reports a pass.

The wrapper now also rejects an auditor exit zero unless the auditor writes a machine-readable report. Required fields follow the `asdi-build-conformance` report structure; the wrapper validates:

- exact report schema version;
- base and candidate commit bindings;
- build phase and scope;
- source completeness and specification set;
- allowed overall result;
- conformance matrix, findings, tests and adversarial checks;
- explicit `independent: true`.

A non-independent PASS is rejected with wrapper exit `3`, `accepted=false`, and failure `independent must be true`. This prevents an auditor process from crossing the C-5 boundary merely by exiting zero.

## Docker enforcement probe

A temporary candidate and probe script were mounted through the wrapper on the local Docker image `safeclaw-us-egress:cc-2.1.283`. The probe attempted all three prohibited actions and observed:

```json
{
  "candidate_writable": false,
  "docker_socket": false,
  "external_network": false,
  "write_error": "OSError",
  "docker_socket_error": "FileNotFoundError",
  "network_error": "OSError"
}
```

The candidate retained only its original files; no `.forbidden` file was created.

## Exact-commit binding

Unit tests prove that `export_commit` exports only the requested Git tree, rejects unsafe archive paths, does not export `.git`, and returns the full commit SHA. The CLI exact-commit mode records the exported SHA, candidate path and Docker invocation before execution. A timeout still exits `3` with `timed_out=true`; a successful invocation exits `0` with `timed_out=false`.

## Scope

This proves the capability boundary of the wrapper. It does not select an auditor model, produce a conformance verdict, or accept Phase 1.
