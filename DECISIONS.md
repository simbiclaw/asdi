# ASDI decisions

| ID | Decision | Status | Provisional implementation | Consequence |
|---|---|---|---|---|
| REV-K | Use Build Guide v4 / REV K as the authority for topology, schemas, phase order, exit tests, and deferred decisions. | accepted | `reference/ASDI-BUILD-GUIDE.md`; new Pass 1 scaffold | Earlier prototype remains reference-only, not the Pass 1 implementation. |
| DD-1 | Docker socket access is proxied and allowlisted. | provisional default | Phase 1 socket-proxy seam; agent containers never mount Docker socket | Enforced before launcher Phase 1 exit. |
| DD-2 | Record installed macOS container runtime rather than choosing a new one. | provisional default | Docker Desktop / engine reported in runtime evidence | Do not introduce a VM. |
| D-9 | Board is Multica by default; Paperclip remains an alternative. | deferred | `board/` adapter stub in Phase 2 | No board code is baked into launcher or policies. |
| D-8 | GitHub events arrive through a local poller. | provisional default | `events/poller/` seam in Phase 4 | No Actions or webhooks. |
| DD-12 | Direct merge is the Pass 1 merge path. | provisional default | `merge/dry_run.py`; no merge queue | Human merges all work until agent merge is explicitly enabled after Pass 2. |
| DD-16 | Spend for local-model runs is measured in tokens and wall-clock. | provisional default | Guardrail schema allows null spend and records both counts | No invented monetary rate. |
| DD-17 | Exposure is gated by a human-run CLI. | accepted for Pass 1 | `exposure/` CLI in Phase 8 | Agents cannot ramp flags. |
| DD-27 | ASDI is implemented as separate Python processes. | provisional default | Future REV K modules under their own directories | Existing prototype remains outside REV K execution path. |
| DD-37 | Only allowlisted human logins may resume work by PR comment. | provisional default | `config/identities.yaml`; enforcement lands with Phase 4 | Other comments are data, never instructions. |
| DD-38 | Pass 1 uses an installed CLI through the launcher adapter. | provisional default | Codex adapter already smoke-tested locally; Claude adapter seam remains | No vendor coupling elsewhere. |
| DD-39 | Pass 1 event inbox and audit log are a SQLite file behind `events/inbox.py`. | provisional default | `Inbox` interface; Archon Postgres is the target (Guide §18) | Backend swap only; dedup, supersede, lease and append-only audit semantics are tested. |
| DD-6 | Pass 1 reviewer is a local OpenAI-compatible model (`qwen-local`, family `qwen`) via vllm-mlx. | provisional default | `config/review.json` `passes[].model`; `archon/models.py` | Different family from both builder CLIs, so `independent_family: true`; unavailable model blocks the pass. |
| DD-48 | **Owner override of C-1 and D-8 for the review trigger (2026-11-18).** GitHub Actions runs the review as a merge gate on every new PR head (`.github/workflows/asdi-review.yml`, job `asdi/review`), using Claude (`claude-opus-5-5`) via the Anthropic SDK. | accepted by owner direction; `SPEC_CONFLICT` with C-1/D-8 recorded, REV K documents unchanged | `archon/pr_review.py gate`; `config/review.json` `github_gate`; the local poller stays as the REV K fallback | GitHub is no longer passive for review. The reviewer is the same family as Claude Code builds (`independent_family: false`, allowed in Pass 1 by Guide §10.3). Reverting = delete the workflow and run `archon/pr_review.py run`. |
