# REV K Phase 7 builder-side verification record

**Status:** builder-side only. These results verify the new local seams; they
are **not Phase 7 acceptance**. The Phase 7 exit test requires a merged change
serving in `prod`, an observed smoke-failure swap-back, rejection of an
unapproved commit, and a negative agent-to-`prod` path check in a real ASDI
run. None of those production acceptance conditions was executed here.

## Requested command

```sh
$ PYTHONPATH=.:src python3 -m unittest discover -s tests -v
Ran 270 tests in 27.288s
OK (skipped=1)
```

The single skip is the live-Docker test: `python:3.12-slim is not cached;
external pulls are not allowed`. The daemon is available, but a direct
`docker pull python:3.12-slim` timed out at the registry, so the test kept its
fail-safe skip instead of fetching an unverified image. It uses
`docker version` and `docker image inspect` before attempting a
`--network=none` build.

## Focused Phase 7 command

```sh
$ PYTHONPATH=.:src python3 -m unittest discover -s tests -p 'test_phase7_*.py' -v
Ran 30 tests in 0.129s
OK (skipped=1)
```

## Whitespace check

```sh
$ git add -N ci deploy backup exposure observe \
    pilots/toy_notes/Dockerfile pilots/toy_notes/.dockerignore \
    tests/test_phase7_*.py docs/asdi/PHASE7_*.md
$ git diff --check
(no output; exit 0)
```

The intent-to-add step is required because the Phase 7 files were previously
untracked; `git diff --check` alone would not inspect them.

## Additional integration checks

```sh
$ PYTHONPATH=.:src python3 tools/validate_examples.py
validated 12 REV K examples

$ PYTHONPATH=.:src python3 pilots/toy_notes/verify/self_test.py
self-test: pass; result validates; evidence preserved

$ python3 -m compileall -q ci deploy backup exposure observe \
    pilots/toy_notes/src pilots/toy_notes/verify
(no output; exit 0)
```

The full suite initially failed in the pre-existing
`test_socks5_proxy_reaches_an_allowlisted_global_endpoint`: the proxy reported
the relay decision only after both sockets closed, so an upstream keep-alive
could delay the callback past the test's deadline. The relay in
`src/asdi/egress.py` now closes both sockets when either endpoint closes,
which makes the decision prompt and preserves the existing egress decisions.
After that correction, the full suite passed as shown above.

## Real Docker verifier preflight

A live, verifier-only launcher run was executed against revision `facc481`
with the local cached `safeclaw:cc-2.1.283` image. Because `main` does not yet
contain the toy harness, `--base-branch revk/pass1` was used as a builder-side
preflight; this is **not** the authoritative PR-head gate.

The first two live attempts exposed two real defects that mocked tests had
hidden:

1. `_verify_head` wrote `static-gates.json` to the evidence root while the
   evidence store requires `.asdi-evidence/static-gates.json`.
2. It copied only top-level evidence files, so nested feature evidence paths
   such as `cli-notes/<run-id>/observed.json` were absent from the store.

Both were fixed at the producer in `launcher/runner.py`, with a regression test
in `tests/test_revk_runner.py`. The third live attempt succeeded:

```text
status: succeeded
run_id: r-v93e3eda136404a728a1bb16ba5baee62
manifest_id: m-172a45b1a023b72906e57a34
commit: facc4815d9573d4156a3a247ae6d606406b4593e
evidence.valid: true
checks: four static gates pass; verify:base-harness pass
features: cli-notes, http-notes, ui-note-list all pass
controls: cli-notes, http-notes, ui-note-list all caught
runtime: network none, no socket, no secret, no agent
```

This proves the verifier and evidence path work in a real container on this
Mac Studio. It does not prove Phase 7 acceptance or replace the owner merge,
post-merge check, production serving observation, or cloud audit.

## What the tests prove locally

- Stale, failed, and unapproved main decisions are refused by both build and deploy before Docker commands run.
- A successful fake build records commit, digest, artifact digest, and hashed approval evidence.
- A successful deploy swaps the pointer from blue to green; failed smoke leaves the previous digest active and records rollback.
- Run commands join `asdi-prod`, carry prod limits/OOM priority, and expose no socket, privileged mode, secret, agent, or staging path.
- Expired flags are killed and produce a judgment-class cleanup issue artifact with a path.
- SQLite dump/restore passes `PRAGMA integrity_check` and the one-restore drill reproduces row data.
- The error tracker appends local records and the Prometheus text endpoint serves request, latency, and process metrics.

These are builder-side negative and positive tests with fake Docker and local
files only. No real registry, external network, real users, secrets, or agent
path to production was exercised.
