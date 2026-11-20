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
