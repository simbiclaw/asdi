# REV K Phase 1 Launcher Evidence

**Date:** 2026-11-16  
**Result:** **Core Phase 1 runtime PASS; phase still in progress**

## Positive Docker evidence

Commands used a temporary local toy product, the locally available `safeclaw:cc-2.1.283` image, and the fixture agent at [`launcher/agents/fixture_agent.py`](../../launcher/agents/fixture_agent.py).

Observed:

```text
status=succeeded
agent_exit_code=0
static:compile status=pass exit_code=0
evidence valid=true
socket_mounted=false
secrets_mounted=false
```

The run used:

* one internal network: `asdi-run-*`;
* one evidence volume: `asdi-evidence-*`;
* one workspace volume: `asdi-workspace-*`;
* no Docker socket;
* no model keys;
* capabilities dropped except CHOWN in short-lived volume setup helpers;
* non-root user `1001:1001` in the agent container;
* read-only root filesystem with bounded `/tmp`.

The content-addressed evidence statement survived container teardown and passed hash verification.

## Negative guardrail evidence

`tests/test_revk_guardrails.py` starts a hanging agent with one turn. The launcher kills it and raises:

```text
turn guardrail exceeded
```

The test also asserts:

* a dedicated internal run network is used;
* no Docker socket appears in agent mounts;
* the volume setup helper did not become the run path.

## Verifier authority and clean-environment evidence

Additional regressions prove:

1. An agent exits 0, but a red verifier forces `status=failed`.
2. `_fresh_export` re-exports base-branch verification; an agent edit changing `verify/bin/verify` from `exit 0` to `exit 101` is ignored.
3. The runtime environment contains no key or token names.

## Full suite

```sh
PYTHONPATH=.:src python3 -m unittest discover -s tests -v
git diff --check
```

Result: **73 tests, OK, 3 expected AF_UNIX skips.**

## Current Phase 1 gap

The verifier now mounts the run-head and base-branch volumes. Next checks must prove:

1. a red verifier cannot be reported green;
2. an agent edit to existing base harness files is ignored;
3. spend and turn limits each independently kill;
4. no model or provider key appears in the run or verifier environment.
