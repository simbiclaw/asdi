# ASDI Scaffold Audit

**Audit date:** 2026-11-13  
**Ticket:** ASDI-000  
**Scope:** Every hook and structural check present in the inspected working directory.

## Inspection method

- Listed all files, including hidden entries, in the working directory.
- Searched tracked candidate content for project files, service manifests, configuration, hooks, CI, tests, secrets, and references to ASDI or gates.
- Reviewed the only regular file, [`ASDI_Codex_Implementation_Backlog_REV_H_G.md`](../../ASDI_Codex_Implementation_Backlog_REV_H_G.md), for requirements and existing capability.
- Checked for `.git` and Git metadata before treating any artifact as checked in.

## Inventory

| Existing hook or structural check | Classification | Hard-rule coverage | Assessment and action |
|---|---|---|---|
| None found | Not applicable | None | There are no Git hooks, agent hooks, task hooks, CI checks, validators, policy scripts, CODEOWNERS, branch rules, lint/test entry points, or structural preflight checks in the repository. Nothing is redundant, obsolete, or candidate for removal. |

No existing check can be promoted as a hard-rule implementation. H1–H7 therefore remain unimplemented at this baseline.

## Hard-rule baseline

| Rule | Requirement | Existing enforcement | Required new capability |
|---|---|---|---|
| H1 | Merge authority by change class; agents cannot merge. | Missing | Remote repository rulesets, CODEOWNERS, scoped merge-bot identity, policy gate, merge-queue verification. |
| H2 | `done_check` must pass before successful completion. | Missing | Contract field, runtime adapter verification, Stop-hook/recheck paths, durable failure evidence. |
| H3 | Container per run, egress allowlist, own-branch push only, no production route. | Missing | Container lifecycle, workspace isolation, network policy, scoped egress tokens, isolation/network tests. |
| H4 | Secrets outside sandbox; production secrets only in production VM. | Missing | Secret inventory, credential roles, injection-at-egress boundary, sandbox secret denial tests. |
| H5 | Per-run turn, spend, and wall-clock guardrails. | Missing | Central configurable defaults, live counters, cancellation, durable guardrail failure states. |
| H6 | No agent irreversible actions or production migration without human authorization. | Missing | Action classifier, production egress denial, approval states, human gates, release/exposure controls. |
| H7 | Protected generated and vendored paths are not edited. | Missing | Explicit protected-path declaration, diff classifier, fail-closed status, review packet flag. |

## Security inventory

| Area | Result | Source of finding |
|---|---|---|
| Git and history | No Git repository or commit history existed. | Hidden-file inspection and `git status` failure. |
| Remote and permissions | No remote, branch protection, ruleset, identity, token role, or merge boundary. | Git remote inspection and filesystem inventory. |
| Secrets | No project secret or credential artifact was present. | Full non-Git file inventory. |
| Production access | No production route, API client, deployment target, inbound webhook, or outbound service configuration. | Full non-Git file inventory. |
| Agent execution | No launcher, adapter, sandbox, hook, or guardrail. | Full non-Git file inventory. |
| Product surface | No deployable application or service. | Full non-Git file inventory. |

## Generated and vendored paths

None existed. No protected path is inferred from absent content. Generated/vendor declarations should be introduced only when actual generated output or vendored dependencies exist, and must be enforced by ASDI-003/ASDI-033.

## Candidate removals or demotions

None. There is no existing hook or structural check to remove, demote, or replace. The backlog's seven hard rules are requirements to implement, not existing checks that can be modified.

## ASDI-000 result

**Pass:** every discovered hook/check is inventoried and classified; none implements H1–H7. No runtime behavior was changed. The absence of a Git baseline is recorded as an ASDI-003 blocker rather than treated as a completed protected repository.
