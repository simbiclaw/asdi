# Live Qwen Local Agent Evidence

**Date:** 2026-11-16
**Owner-selected runtime:** LiteLLM model `qwen3.6-35b-dspark-local`
**Result:** **Governed local lifecycle PASS without exposure**

## Runtime path

The operations CLI `--live` mode invokes [`scripts/codex_lifecycle_adapter.py`](../scripts/codex_lifecycle_adapter.py). The adapter:

1. reads the local LiteLLM credential from the local gateway container without printing it;
2. creates an isolated provider-only `CODEX_HOME`;
3. starts a local role-compatibility proxy that converts Responses `developer` roles into user messages for the local Qwen template;
4. invokes Codex with model `qwen3.6-35b-dspark-local`, provider `litellm`, Responses transport, workspace-write, approvals disabled, and network access disabled for model shell commands;
5. validates the produced artifact behavior before returning success.

The parent assistant prompt and tools do not leak into the nested model request.

## Successful governed mission

**Mission:** `mission_aa327a3b-269d-457a-b962-d420b7a476e7`
**External reference:** `LIVE-QWEN-35B-DSPARK-5`
**Status:** `deployed`

Evidence:

| Stage | Result |
|---|---|
| Live implementation | Codex exit 0; model/provider fields recorded |
| Self-check | exit 0 |
| Correctness/security/acceptance reviews | all pass |
| Classification | `T0_human`; autonomous merge false; production access false |
| Governed local merge | commit `deee7cd06e1fb274b40696239599f5af17595da4`; remote merge false |
| Local deployment | release `..._034f71f6` |
| Default flag | feature ran with `variant=off`; exposure intentionally omitted |
| Guardrails | 5 turns, $0 reported, 23.11 seconds wall clock; limits 24/$2/600s |

## Failed attempts preserved

Earlier live attempts failed for:

1. LiteLLM chat-template rejection of Codex Responses developer roles;
2. adapter behavioral validation when the model used subcommands instead of required flags;
3. acceptance review requiring revision provenance.

These failures produced durable mission evidence and led to the adapter/reviewer fixes above. They were not silently retried as the same successful run.

## Boundary

This proves a live local model can complete the implementation portion of the governed local lifecycle. It does **not** prove strict container egress acceptance, remote merge authority, or production deployment. The successful run intentionally omitted exposure; the fixture-based complete exposure scenario remains separately verified.
