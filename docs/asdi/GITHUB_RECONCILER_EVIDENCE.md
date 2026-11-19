# GitHub reconciler evidence

**Date:** 2026-11-19  
**Result:** **Read-only reconciler implemented and builder-tested; authenticated live reconciliation blocked by invalid host GitHub token**

## Implemented

[`events/github_reconciler.py`](../../events/github_reconciler.py) implements Build Guide V4's passive-GitHub / local-poller boundary:

- polls current state with an explicit absolute, shell-free `gh` command;
- bounds each command with a timeout and a minimal environment;
- does not inherit arbitrary host environment or credential variables;
- may use only the explicitly supplied local HTTP/HTTPS proxy;
- normalizes open PR number, exact 40-character head SHA, base branch and changed paths into `github.pull_request`;
- normalizes exact `main` commit into `github.push`;
- scans the durable journal before appending, so a crash between append and state refresh cannot create duplicate facts;
- rejects malformed PR payloads without appending them;
- persists reconciliation health and, on failure, command exit, timeout and stderr tails;
- does not post statuses, write repository data, accept webhooks, execute reviews or invoke agents.

The CLI command is:

```sh
PYTHONPATH=.:src python3 -m events.cli \
  --root <state-root> --base-ref main \
  reconcile-github \
  --repository simbiclaw/asdi \
  --gh /opt/homebrew/bin/gh \
  --proxy http://127.0.0.1:7890 \
  --timeout-seconds 30
```

## Builder-side execution

Focused tests used an explicit fake `gh` executable and proved:

- PR and `main` facts are normalized once;
- replay does not append duplicate events;
- malformed PR arrays are rejected while valid facts still reconcile;
- command failure records unhealthy state and appends nothing;
- the default environment excludes inherited credential variables;
- the CLI adapter emits two normalized discovery events and marks the result read-only.

```sh
PYTHONPATH=.:src python3 -m unittest tests.test_events_github_reconciler -v
PYTHONPATH=.:src python3 -m unittest tests.test_events_cli -v
PYTHONPATH=.:src python3 -m unittest discover -s tests
```

Observed full-suite result at this slice: **171 tests, OK, 4 expected socket/TCP skips**.

## Actual authenticated probe

Two read-only attempts used `simbiclaw/asdi`, `/opt/homebrew/bin/gh`, local proxy `http://127.0.0.1:7890`, and a 30-second timeout. Both reconciliations failed closed before any journal append.

The persisted health record contains:

- PR command exit code `1`;
- PR stderr: `HTTP 401: Requires authentication (https://api.github.com/graphql)`;
- main command exit code `1`;
- main result: GitHub HTTP 404, consistent with an unauthenticated request to a private repository;
- `healthy: false`;
- `alert: github_reconciliation_failed`;
- journal line count `0`.

A separate diagnostic command returned:

```text
github.com
  X Failed to log in to github.com account simbiclaw (default)
  - Active account: true
  - The token in default is invalid.
  - To re-authenticate, run: gh auth login -h github.com
```

ASDI did not re-authenticate, rotate credentials, change GitHub configuration, or inject a token. This is a supervisor/owner-side host credential action.

## Status boundary

| Claim | Status |
|---|---|
| Read-only reconciler and CLI | Implemented |
| Fake-runtime current-state reconciliation | Builder-tested |
| Deduplication and fail-closed behavior | Builder-tested |
| Real authenticated GitHub reconciliation | **Blocked: invalid host GitHub token** |
| End-to-end live PR workflow | Not demonstrated |
| Phase 4 exit | Not claimed |
