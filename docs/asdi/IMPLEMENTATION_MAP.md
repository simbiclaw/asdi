# ASDI Implementation Map

**Audit date:** 2026-11-13  
**Audited path:** `/Users/russell/workspace/ASDI`  
**Ticket:** ASDI-000  
**Baseline document:** [`ASDI_Codex_Implementation_Backlog_REV_H_G.md`](../../ASDI_Codex_Implementation_Backlog_REV_H_G.md)

## Repository inventory

The inspected working directory contained exactly one regular file:

| Path | Existing capability | Evidence |
|---|---|---|
| [`ASDI_Codex_Implementation_Backlog_REV_H_G.md`](../../ASDI_Codex_Implementation_Backlog_REV_H_G.md) | Execution backlog for ASDI Design REV H and ASDI Stack REV G, including tickets, dependencies, seven hard rules, D-9 compatibility tests, and open decisions. | Full-file review; lines 1–900. |

There was no `.git` directory when the audit was performed. Consequently, there was no Git history, branch configuration, remote, checked-in state, or protected baseline.

## Existing services, configuration, and data

| Capability | Status | Repository evidence |
|---|---|---|
| Application service | Missing | No manifest, source tree, package manifest, Dockerfile, or process definition. |
| Database schema or migration | Missing | No schema, migration, ORM model, or database configuration. |
| Runtime configuration | Missing | No environment template, service configuration, or infrastructure configuration. |
| Agent instructions | Missing | No repository-level `AGENTS.md`, agent config, hooks, or runtime adapter. |
| Skills | Missing from the repository | The available-session skill catalog is outside this repository and is not project scaffold. |
| Hooks or structural checks | Missing | No Git hooks, task hooks, scripts, validators, policy checks, or preflight checks. |
| CI | Missing | No CI workflow, job definition, runner configuration, or test entry point. |
| Tests | Missing | No test files, fixtures, runners, or expected-results directory. |
| Documentation | Backlog only | The backlog is authoritative for execution order and acceptance criteria; no system documentation existed before this audit. |

## Security-sensitive surface

| Area | Finding | Consequence |
|---|---|---|
| Secrets | No checked-in secret, token, credential, environment value, keyfile, or secret manager configuration was found. | There is no production secret exposure in the inspected scaffold. |
| Production connectivity | No service, network route, deploy target, tunnel, proxy, webhook, CI integration, or external API client was found. | There is no production connectivity and no runtime side-effect path. |
| Generated or vendored paths | No generated, vendored, or third-party content was found. | No protected generated/vendor path can yet be declared from existing content. |
| Authentication and authorization | No identity, token boundary, role definition, GitHub ruleset, CODEOWNERS file, or merge-control mechanism was found. | H1 and H3–H7 are unimplemented; no autonomous execution or merge path may be enabled. |

## Mapping to the backlog

### Gate 0 — audit, decisions, scaffold

| Ticket | Dependency | Existing support | Missing or conflicting capability | Relevant path |
|---|---|---|---|---|
| ASDI-000 | None | Backlog provides acceptance criteria. | Repository map and hook audit did not exist before this document; no Git baseline existed. | `docs/asdi/IMPLEMENTATION_MAP.md`, `docs/asdi/SCAFFOLD_AUDIT.md` |
| ASDI-001 | ASDI-000 | Open decisions and candidate options are recorded in backlog §1.3 and §7. | No checked-in ADR index, D-9 test plan, decision record, owner, or evidence trail. | `docs/asdi/decisions/` |
| ASDI-002 | ASDI-000 | Backlog specifies what makes a suitable pilot. | Current repository has no deployable product or service; no pilot target or owner approval. | `docs/asdi/PILOT_TARGET.md` |
| ASDI-003 | ASDI-000 | Backlog defines required identities and fail-closed verification. | No Git repository, remote, branch protection, rulesets, CODEOWNERS, credential separation, or GitHub permission tests. | Git remote/repository settings and `CODEOWNERS` |

### Gate 1 — run contract and execution kernel

| Ticket | Dependency | Existing support | Missing or conflicting capability | Relevant path |
|---|---|---|---|---|
| ASDI-010 | ASDI-000 | Backlog defines authored fields, defaults, validation examples, and provenance. | Implemented and reverified through 2026-11-13: dependency-free schema builder, strict validator, provisional central defaults, provenance checks, fixtures, and tests. The ASDI-011 launcher revalidates before launch. | [`src/asdi/run_contract.py`](../../src/asdi/run_contract.py), [`fixtures/run_contracts/`](../../fixtures/run_contracts/), [`tests/test_run_contract.py`](../../tests/test_run_contract.py) |
| ASDI-011 | ASDI-010 | Backlog defines runtime lifecycle and adapter requirements for Claude Code, Codex, and Hermes. | Implemented through 2026-11-13: board-neutral durable run store, Claude/Codex/Hermes adapters, structured event collection, actual child-process cancellation, usage capture, launcher `done_check` recheck, missing/runtime/host-restart failures, and fail-closed refusal without ASDI-012 isolation. Vendor CLI invocation and guardrail consumption remain unimplemented/unverified. | [`src/asdi/runtime.py`](../../src/asdi/runtime.py), [`tests/test_run_launcher.py`](../../tests/test_run_launcher.py), [`tests/test_runtime_adapters.py`](../../tests/test_runtime_adapters.py), [`docs/asdi/GATE_011_EVIDENCE.md`](GATE_011_EVIDENCE.md) |
| ASDI-012 | ASDI-011 | Hard rule H3 requires container-per-run isolation and egress control. | In progress and **not accepted**: hardened no-network container launch/cancellation/workspace/environment/setup-failure evidence exists; host-side HTTP/SOCKS allowlist works, but Docker Desktop cannot mount its Unix socket into the container. An owner-approved `development_open` bridge profile permits noncompliant flow bring-up only. | [`src/asdi/sandbox.py`](../../src/asdi/sandbox.py), [`src/asdi/egress.py`](../../src/asdi/egress.py), [`tests/test_sandbox.py`](../../tests/test_sandbox.py), [`docs/asdi/GATE_012_EVIDENCE.md`](GATE_012_EVIDENCE.md), [`docs/asdi/DEV_FLOW_EVIDENCE.md`](DEV_FLOW_EVIDENCE.md) |
| ASDI-013 | ASDI-010, ASDI-011, ASDI-012 | H2 and H5 define `done_check`, turn, spend, and wall-clock requirements. | Local prototype guardrails and failure transitions are implemented and tested. Live runtime billing and production acceptance remain unfinished. | [`src/asdi/lifecycle.py`](../../src/asdi/lifecycle.py), [`tests/test_lifecycle.py`](../../tests/test_lifecycle.py), [`docs/asdi/ADAPTER_GUARDRAILS_EVIDENCE.md`](ADAPTER_GUARDRAILS_EVIDENCE.md) |
| ASDI-014 | ASDI-011 | Backlog defines structured events and evidence. | Durable missions/events, usage, external-reference indexing, and reset/closure records exist locally. Queryable API, retention/redaction policy, and production observability interface remain. | [`src/asdi/lifecycle.py`](../../src/asdi/lifecycle.py), [`tests/test_lifecycle.py`](../../tests/test_lifecycle.py) |

### Integrated company lifecycle

| Capability | Dependency | Current support | Remaining boundary | Relevant path |
|---|---|---|---|---|
| Integrated lifecycle | ASDI-010/011 and ADR-0008 | **Local prototype verified; production autonomy not accepted.** Admission, brief, decomposition, fixture execution, scoped checks, bounded repair, work-reference indexing, brief-v2 reset, classification, T0-governed local merge, autonomous mission runner, monitored self-healing repair, local deployment/rollback, default-off flag, controlled exposure, monitoring, triage, verification, closure, and learning run as one vertical slice. Explicit shell-free command adapter, local turn/spend/wall-clock guardrails, and durable JSON operations CLI are verified. | Live model agents, remote merge, production deployment, strict egress acceptance, and production-grade guardrails remain unfinished. | [`src/asdi/lifecycle.py`](../../src/asdi/lifecycle.py), [`scripts/company_cli.py`](../../scripts/company_cli.py), [`scripts/run_company_scenarios.py`](../../scripts/run_company_scenarios.py), [`docs/asdi/COMPANY_LIFECYCLE_EVIDENCE.md`](COMPANY_LIFECYCLE_EVIDENCE.md), [`docs/asdi/AUTONOMOUS_RUNNER_EVIDENCE.md`](AUTONOMOUS_RUNNER_EVIDENCE.md), [`docs/asdi/SELF_HEALING_RUNNER_EVIDENCE.md`](SELF_HEALING_RUNNER_EVIDENCE.md), [`docs/asdi/ADAPTER_GUARDRAILS_EVIDENCE.md`](ADAPTER_GUARDRAILS_EVIDENCE.md), [`docs/asdi/RESET_RECOVERY_EVIDENCE.md`](RESET_RECOVERY_EVIDENCE.md) |

### Gates 2–6

Board, remote merge, production admission, deployment, and enterprise observability still depend on Gate 0 owner decisions and production hardening. The integrated local prototype now contains a policy classifier, recovery/repair loop, learning ledger, local experiment system, local deployment/rollback, defect pipeline, and local monitoring surface, but these are explicitly prototype controls rather than accepted production autonomy.

There is no conflicting implementation to preserve. The primary conflict is against intent, not existing code: the backlog describes a runnable, locally governed system while the inspected repository contains only the plan.

## Safe execution order from this baseline

1. Preserve the Gate 0 discovery artifacts in a local Git baseline without introducing runtime behavior.
2. Complete ASDI-001 ADRs and the D-9 evidence/test plan.
3. Complete ASDI-002 pilot-service selection: designate a pilot repository/service or approve a synthetic reference service; `simbiclaw/asdi` is the ASDI control repository, not yet the pilot product.
4. ASDI-003 remains incomplete by owner decision: GitHub-native branch enforcement is deferred, no scoped identities exist, and all execution/merge paths stay disabled.
5. ASDI-010 provides the launch preflight. ASDI-011 passed at process-kernel level. ASDI-012 remains failed until container-side egress is proven; the local lifecycle may run with fixture agents and T0-governed local merge only. Vendor production runtimes and autonomous remote merge/deployment remain disabled.

## ASDI-000 result

**Pass with boundary noted:** the repository audit and scaffold classification are checked into the local baseline, and no application/runtime behavior was changed. The protected GitHub repository baseline required by ASDI-003 remains externally blocked until an actual repository, plan capabilities, identities, and owner authorization are supplied.

## Baseline update after initial audit

After the initial audit, the owner designated the private repository [`https://github.com/simbiclaw/asdi`](https://github.com/simbiclaw/asdi), and local commit `f204409` was published to its empty `main` branch through local proxy port 7890. The authenticated repository owner is `simbiclaw` with admin permission.

The remote designation does not satisfy ASDI-003. GitHub rejected repository-ruleset, legacy branch-protection, and branch-rules reads for this private repository with HTTP 403, saying the feature requires GitHub Pro or a public repository. Separate identity provisioning remains unauthorized. See [`GATE_003_EVIDENCE.md`](GATE_003_EVIDENCE.md).

The owner subsequently deferred GitHub-native branch enforcement in ADR-0004. ASDI-003 remains fail-closed and incomplete; runtime execution and merge remain disabled.
