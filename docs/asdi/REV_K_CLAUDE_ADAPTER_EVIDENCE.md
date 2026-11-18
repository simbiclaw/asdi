# REV K Phase 1 Claude adapter evidence

**Date:** 2026-11-18  
**Status:** Builder-side implementation and execution evidence; independent conformance verification is still required.

## Implementation

- Added an ASDI-owned adapter seam in [`launcher/agent_adapters.py`](../../launcher/agent_adapters.py), with separate fixture and Claude entries.
- Added the Claude-specific entrypoint in [`launcher/agents/claude_adapter.py`](../../launcher/agents/claude_adapter.py) for pinned image `safeclaw:cc-2.1.283`.
  - Uses headless `--print --output-format stream-json --verbose`.
  - Denies permission prompts and disables session persistence.
  - Mounts `AGENTS.md`, `CLAUDE.md`, the validated run contract and the adapter itself read-only.
  - Installs a Stop-hook done check from the contract. This remains a convenience; the launcher's clean verifier remains authoritative.
  - Emits stream events from which launcher-owned guardrails count turns, tokens and spend.
- The proxy now strips inbound `x-api-key`, `authorization` and proxy credential headers before injecting the model credential.
- A recognized Claude wire-model alias is the only model name visible to the agent; the egress proxy rewrites it to the configured local model after the sandbox boundary and corrects content length.
- The proxy converts an absolute HTTP-proxy request URI to an origin path before forwarding.
- The Claude wrapper preserves only the safe `HTTP_PROXY`, `HTTPS_PROXY` and `NO_PROXY` routing variables supplied by the launcher; it does not copy credentials or arbitrary environment.

## Local adversarial tests

```sh
PYTHONPATH=.:src python3 -m pytest -q tests/test_agent_adapters.py tests/test_revk_verifier_authority.py tests/test_revk_runner.py tests/test_revk_guardrails.py tests/test_revk_egress.py tests/test_launcher_cli.py
PYTHONPATH=.:src python3 -m unittest discover -s tests
git diff --check
```

Observed: **110 tests, OK, 4 expected skips**; `git diff --check` clean.

Coverage includes:

- a successful agent cannot overturn a forced-red verifier;
- agent weakening of existing harness content is ignored by the base export;
- runtime environment has no model-key or token names;
- the Claude launch has no Docker socket or secret bind;
- the proxy strips agent credential headers;
- the proxy rewrites the wire alias only outside the sandbox;
- each stop-hook done-check success/failure path returns the expected hook status;
- turn, token, spend and wall-clock guardrails terminate runs from outside.

## Live isolated run

Command shape:

```sh
LITELLM_MASTER_KEY="${LITELLM_MASTER_KEY:?}" \
PYTHONPATH=.:src python3 -m launcher.cli \
  --root /private/tmp/asdi-claude-live \
  --product-root /private/tmp/asdi-claude-fixture \
  --base-branch main \
  --agent-adapter claude \
  --model qwen3.6-35b-dspark-local \
  --model-alias claude-3-7-sonnet-latest \
  run --contract /private/tmp/asdi-claude-fixture/contract.json
```

Run ID: `r-26fac407-98a1-41bc-ad5b-e61913487347`

```text
status=succeeded
agent_exit_code=0
static:compile=pass
verify:base-harness=pass
turns=3
tokens=4335
spend_usd=0.014145
socket_mounted=false
secrets_mounted=false
egress_mode=allowlist_proxy
evidence=m-a9ad5f546c34b29f80a16f8d
```

After teardown, `EvidenceStore.verify("m-a9ad5f546c34b29f80a16f8d")` returned valid with feature status `pass`. The durable `launcher status` command also returned the same checks and evidence.

This proves the builder-owned adapter path in one isolated fixture. It does not prove Phase 1 acceptance or replace independent read-only conformance verification.
