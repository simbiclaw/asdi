# Builder-owned Claude adapter recovery evidence

**Date:** 2026-11-18
**Result:** **Live local-model adapter transport PASS; independent conformance audit and phase acceptance pending**

## Implementation

- Explicit adapter registry: `fixture` and `claude`; board dispatch remains outside the launcher.
- Dedicated [`launcher/agents/claude_adapter.py`](../../launcher/agents/claude_adapter.py) launches Claude Code 2.1.283 headlessly with stream-JSON events.
- Contract objective, why, constraints, out-of-scope items and done-check command are passed as environment data.
- Claude Stop hook records its observation to the evidence volume, but the launcher verifier remains authoritative.
- Runner forwards normalized turns, tokens and cost from the stream and enforces guardrails externally.
- The per-run proxy strips credential headers, injects the LiteLLM key outside the sandbox, routes the local model by proxy-origin path, and keeps Git/package CONNECT destinations allowlisted.
- No Docker socket, model key or token-like environment name enters the agent container.

## Live execution

Local isolated run `r-5fc95790-5990-4b1b-bca2-842d6fe6e367`:

```text
status=succeeded
agent_exit_code=0
static:compile=pass blocking=true
verify:base-harness=pass
turns=5
tokens=6303
spend_usd=0.027948
socket_mounted=false
secrets_mounted=false
evidence=m-6ab537ce486a96d903aa7039 valid=true
```

Stored evidence included Claude stdout/stderr/result, Stop-hook output and static-gate results. The base verifier—not the agent—produced the authoritative result and feature verdict.

## Limits

This proves the fresh builder-owned live coding-CLI transport and guardrail collection. It does not constitute independent conformance verification, Phase 1 acceptance, production deployment, remote merge or controlled exposure.
