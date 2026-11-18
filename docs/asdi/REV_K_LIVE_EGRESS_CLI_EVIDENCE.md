# REV K live coding-CLI egress evidence

**Date:** 2026-11-17
**Result:** **PASS for Phase 1 live egress transport probe; independent conformance audit still required**

## Run identity

- Launcher run: `r-b73ef259-c3e7-44ff-9d5f-1aa8d9dd77cb`
- Evidence manifest: `m-14f6e99b3711391703429abc`
- Fixture commit: `d89ff8a1f2ac528ea3acb45aa15dc646143af5f9`
- Agent image: `safeclaw:cc-2.1.283`
- Coding CLI: Claude Code `2.1.283`
- Model: `qwen3.6-35b-dspark-local` through the local LiteLLM endpoint
- Final launcher status: `succeeded`
- Final checks: `static:probe-compile pass`, `verify:base-harness pass`

The content-addressed evidence statement was verified after container, network and volume teardown:

```json
{"files": 2, "manifest_id": "m-14f6e99b3711391703429abc", "run_id": "r-b73ef259-c3e7-44ff-9d5f-1aa8d9dd77cb", "valid": true}
```

## What Claude executed

The adapter at [`launcher/agents/claude_proxy_agent.py`](../../launcher/agents/claude_proxy_agent.py) invoked Claude Code noninteractively with its configured Stop hook. The live CLI:

1. used Git over the proxy to shallow-clone `https://github.com/octocat/Hello-World`;
2. used npm over the proxy to install and inspect pinned package `is-odd@3.0.1`;
3. generated and ran `proxy_probe.py`;
4. completed its Stop hook.

The Stop-hook record has every check true and `failures: []`. It records environment names only, not values. The observed forbidden-credential-like name list is empty. The launcher runtime evidence separately records:

```text
socket_mounted=false
secrets_mounted=false
```

## ASDI-run proxy observations

Durable `egress-proxy.log` records these authorized destinations:

```text
CONNECT github.com:443 authorized reason=allowlisted_connect
CONNECT registry.npmjs.org:443 authorized reason=allowlisted_connect
```

The npm registry connection appears four times. Twelve successful `POST` requests to `host.docker.internal:4000/v1/messages` also traversed the proxy. The proxy, not the agent, held `LITELLM_MASTER_KEY`; no key or token was present in the agent environment.

Reported model usage was 13,552 tokens and USD 0.075024. The launcher observed two structured turns and enforced the run guardrails from outside the container.

## Independent verification and control

The base-branch verifier, not Claude, decided the result. It re-ran the generated probe in a fresh verifier container and confirmed the exact semantic result:

```json
{"git_clone":"pass","npm_package":"pass","model_endpoint":"configured"}
```

It then copied the probe, mutated `git_clone` from `pass`, and observed that the control output no longer matched. It recorded feature `live-egress-cli` with `status=pass` and `control=caught`.

Earlier red runs in the same sequence proved fail-closed behavior for the absolute-form proxy URI defect and a malformed negative-control fixture. Their red evidence manifests remained valid; no agent exit or model claim overturned them.

## Limits

This proves the Phase 1 live coding-CLI transport through the per-run HTTP/CONNECT allowlist proxy, key injection at the proxy, Git/package traffic, model traffic, no-credential agent environment, and Claude Stop-hook evidence.

It does **not** accept Phase 1 as a whole, the four-document specification sync, production egress, production credentials, remote merge, or deployment. The fresh independent conformance audit remains required before acceptance.
