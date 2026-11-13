# ASDI Implementation Backlog — Codex Handoff

**Baseline:** ASDI Design REV H (2026-11-13) + ASDI Stack REV G (2026-11-13)  
**Target profile:** P-1 — one Mac Studio M3 Ultra 256 GB; GitHub is a passive code host; all ASDI loops run locally.  
**Audience:** Codex acting as implementation engineer.  
**Purpose:** Turn the two artifacts into an ordered, testable implementation backlog. This is an implementation plan, not a replacement architecture.

## 0. Instructions to Codex

You are implementing the ASDI system described in the two source artifacts. Treat this backlog as the execution plan and the source artifacts as the authority for intended behavior.

### Required first action

1. Inspect the target repository, current scaffold, existing services, configuration, tests, and Git history.
2. Produce a repository-grounded implementation map: existing capability, missing capability, conflicting capability, and relevant paths.
3. Do not assume that the current repository matches any previously described scaffold. Do not invent files, services, APIs, or tool capabilities before inspecting it.
4. Start with `ASDI-000` through `ASDI-003`. Do not implement later epics until their dependencies and acceptance criteria are satisfied.

### Engineering rules for this handoff

- **Implement outcomes, not a scripted build procedure.** A board launches one agent task. The build agent chooses its implementation method. Archon wraps the outcome, verifies it, and runs lifecycle pipelines; it must not dictate the builder's internal steps.
- **No nested orchestration.** Do not call Archon from inside a build agent, create agents inside agents, or introduce nested budgets. The board launches the build task; Archon owns the surrounding pipelines.
- **Human admits work.** Agents may propose work but cannot admit it. Feature work enters as an experiment card; maintenance runs under a standing charter approved by the human.
- **Keep hard requirements hard and preferences soft.** Enforce only the seven hard rules in §2. Do not turn conventions, preferred tools, planning style, or sequencing preferences into mandatory gates without evidence and an explicit decision.
- **Never weaken a hard boundary to make a demo pass.** Any unresolved or failed security boundary blocks autonomous execution/merge/release for the affected path.
- **Do not make irreversible changes.** Do not change production data, expose a feature, ramp traffic, alter pricing, send external side effects, force-push, or perform a production migration. A production migration requires explicit human authorization and a verified snapshot immediately beforehand.
- **Do not enable agent merging at the start.** Keep it disabled until the TRM and merge-policy acceptance criteria are demonstrated.
- **No GitHub Actions, no GitHub webhooks, no inbound webhook path.** Use the local 60-second GitHub API poller described by the artifacts.
- **GitHub is passive.** It hosts code, PR UI, rulesets, CODEOWNERS and merge queue. CI, reviews, policy checks, polling, workflows, triage, readouts and sweeps run on the Studio.
- **No production route from agent or staging zones.** Production secrets exist only in the production VM. Release is pull-based from the local signed-image registry.
- **Do not silently resolve open decisions.** Record an ADR and ask the owner where a decision is required. Keep components behind adapters when practical.
- **Show evidence.** Every ticket must end with changed paths, tests executed, results, remaining risks and a clear pass/fail against its acceptance criteria.

### Work cadence

Implement one ticket or a tightly coupled ticket group at a time. Keep the system runnable after each gate. Prefer small, independently verifiable PRs. When a gate fails, report the evidence and stop at that gate; do not skip ahead or paper over the failure.

---

## 1. Source baseline and interpretation

### 1.1 Authoritative artifacts

1. **ASDI Design, Sheet 02, REV H (2026-11-13):**  
   https://claude.biothropic.com/ASDI/ASDI%20Design.html
2. **ASDI Stack, Sheet 03, REV G (2026-11-13):**  
   https://claude.biothropic.com/ASDI/ASDI%20Stack.html

Design REV H specifies the intended operating model and the single-host P-1 deployment profile. Stack REV G specifies the software components and the remaining implementation/verification gaps.

### 1.2 Working design decisions

| Topic | Baseline for implementation | Status / treatment |
|---|---|---|
| Host | Mac Studio M3 Ultra 256 GB only | Fixed constraint for this prototype |
| Code host | GitHub | Passive; no Actions or webhooks |
| Local event intake | Archon poller, every 60 seconds | Working design; verify API budget and reconciliation |
| Workflow engine | Archon | Owns lifecycle pipelines, not build-agent behavior |
| Board / dispatch | Multica or Paperclip | **D-9 open; do not silently choose** |
| Product flags / experiments | GrowthBook, self-hosted | Stack selection |
| Error tracking | Bugsink | Stack selection; GlitchTip only if licence requires an alternative |
| Metrics / logs | Prometheus, Loki, Grafana | Stack selection; agent access through MCP servers |
| Local model serving | vllm-mlx on the Studio | Product-serving instance reserved; agent pool preemptible |
| Production deployment | Pull deployer in production VM | Pulls/verifies signed images; blue/green deployment |
| Ingress / proxy / VM manager | Tunnel + Traefik or Caddy + VM per role | Provider and product choices remain open |
| Triage privacy (D-4) | Local model for logs containing user data; API models only for scrubbed logs | Recommended; use local-only as safe default pending owner confirmation |
| Timers | Due dates in Postgres + hourly idempotent sweeps | Do not introduce a separate durable workflow engine |
| Board / Archon state | Board owns work items; Archon owns pipeline runs | Nightly reconciliation required |

### 1.3 D-9: board and dispatch decision remains open

Stack REV G re-scores the one-host options as **Paperclip + Archon 76/110** and **Multica + Archon 75/110**. It recommends Paperclip for the one-host profile because hard budget stops and heartbeats matter on a shared machine. Design REV H still lists Multica + Archon as its current core while explicitly marking D-9 open. The one-point difference is within scoring noise; neither score is a benchmark.

Codex must implement a short, evidence-based compatibility spike before the board-specific integration is locked in. Keep a narrow board/dispatch adapter so the decision does not contaminate run contracts, Archon pipelines or GitHub integration.

**D-9 comparison tests:**

1. Dispatch a task to Claude Code, Codex and Hermes (or document a runtime-specific limitation with evidence); persist task/run identity and recover after the board server restarts.
2. Cancel a running task and prove the process and its container stop; enforce spend and wall-clock limits.
3. Complete the task, open a PR, attach the PR to the original work item, reconcile board and Archon state, and demonstrate that no agent can merge directly.

For Multica, verify the task-cancel API and wrapper-command runtime for per-run containers and budget caps. For Paperclip, verify cancellation through the adapter and that the adapter receiver can launch the per-run container. Record operational friction and test evidence, not just feature checklists.

**Blocked decision:** the owner selects the board after reviewing the spike. Until then, build only board-neutral components and the adapter contract.

### 1.4 Important implementation caveat: per-run isolation

Design REV H's hard rule is **a container per run**, with an egress allowlist and no route to production. Stack REV G explicitly acknowledges that isolation is only per VM until per-run containers exist. Treat that as a known gap, not as compliance. Per-run containers must be implemented and tested before concurrent autonomous runs, agent merges or production-connected autonomy are enabled. A temporary single-run development mode may be used only with synthetic data and no production access; it must be labelled non-compliant and must not be mistaken for the finished sandbox boundary.

---

## 2. Seven hard rules — implementation invariants

These are platform-enforced requirements. All other behavior is a request that an agent may override with a reason.

| ID | Hard rule | Required enforcement |
|---|---|---|
| H1 | Merge authority by change class | Only the merge bot may enqueue eligible changes into the GitHub merge queue. Agents cannot merge. CI, three scoped review passes and `asdi/policy` must pass. Judgment-class changes also require the human via CODEOWNERS/ruleset. No bypass. |
| H2 | `done_check` | A run cannot finish successfully unless `done_check` passes. Claude Code uses a Stop hook; Codex and Hermes are rechecked by the launcher. |
| H3 | Sandbox | Container per run, egress allowlist, push only to the run's own branch, no network route to production. |
| H4 | Secrets outside sandbox | No production secrets in agent/staging zones. Tokens are injected at egress; production secrets exist only in the production VM. |
| H5 | Guardrails | Enforced per-run turn, spend and wall-clock limits. |
| H6 | No agent irreversible actions | Human owns exposure ramps, shared-data migrations, external side effects, pricing and force-push. Every production migration requires a verified snapshot immediately beforehand. |
| H7 | Protected paths | Generated and vendored files are not edited. Test/CI changes are allowed but always flagged in the review packet; CI/test infrastructure changes are judgment-class. |

### Change classification rules

**Judgment-class** includes authentication/security boundaries, secrets, compliance/retention, schema and migrations, public API/CLI contracts, unflagged product behavior, pricing, new dependencies, CI/test infrastructure and ASDI's own rules. Any state change or external side effect is judgment-class even when behind a feature flag. Anything uncertain routes to judgment.

**Agent-mergeable** includes proven refactors, bug fixes with reproduction tests, added tests, patch/minor dependency bumps, documentation, follow-ups on an approved direction, product code behind default-off flags, flag cleanup, and production defect fixes within an approved charter.

Routing must include a CODEOWNERS path floor, semantic class check, diff-size check and reviewer uncertainty check. The illustrative 400-line diff budget is provisional; keep it configurable and do not treat it as validated.

---

## 3. Backlog conventions

- **P0:** blocks safe execution or the next lifecycle gate.
- **P1:** required for the complete lifecycle, but can follow the execution/merge foundation.
- **P2:** operational hardening or ongoing system improvement.
- **Gate:** milestone at which acceptance is evaluated.
- **Blocked by:** prerequisite ticket IDs.
- Every task must have a machine-verifiable test where possible. Human-only acceptance (e.g. a judgment decision) must be represented as a deliberate approval state, not simulated as an automated pass.

No time estimates are supplied: the repository and scaffold have not yet been inspected, so effort estimates would be speculative.

---

## 4. Ordered implementation backlog

## Gate 0 — Repository audit, decisions and scaffold sorting

### ASDI-000 — Inspect repository and map the existing scaffold
**Priority:** P0 · **Type:** discovery · **Blocked by:** none

**Work**
- Inspect repository structure, current services, configs, database schemas, agent instructions, skills, hooks, CI and tests.
- Inventory all existing hooks and structural checks; classify each as one of: hard requirement H1–H7, soft request, redundant/obsolete, or unresolved.
- Map existing capabilities against this backlog. Do not duplicate working components or assume the old design is current.
- Identify security-sensitive paths, generated/vendor paths, secrets handling and any existing production connectivity.

**Acceptance**
- A checked-in `docs/asdi/IMPLEMENTATION_MAP.md` identifies existing/missing/conflicting capabilities with source paths.
- A checked-in `docs/asdi/SCAFFOLD_AUDIT.md` classifies every existing hook/check against H1–H7 and identifies candidate removals/demotions.
- No runtime behavior has been changed by this discovery ticket.

### ASDI-001 — Record architecture decisions and unresolved items
**Priority:** P0 · **Type:** ADR · **Blocked by:** ASDI-000

**Work**
- Create an ADR for D-9 using the three comparison tests in §1.3.
- Record D-4, D-8, database topology, VM manager, tunnel provider, proxy, resource reservations, SLO, severity threshold, experiment statistical thresholds and provisional numeric defaults as open/confirmed decisions.
- Record the source-of-truth split: board owns work items; Archon owns pipeline runs; nightly reconciliation detects drift.

**Acceptance**
- `docs/asdi/decisions/` contains an index and ADRs with status (`proposed`, `accepted`, `rejected`, `deferred`), rationale, evidence and owner.
- D-9 is explicitly `blocked on owner decision` until the compatibility spike is reviewed.
- No choice is silently inferred from the 76/110 vs. 75/110 scores.

### ASDI-002 — Select the pilot product/repository for lifecycle validation
**Priority:** P0 · **Type:** scope/ADR · **Blocked by:** ASDI-000

**Work**
- Determine whether the inspected repository contains a deployable product/service suitable for the feature, release and production-defect scenarios.
- If it does not, ask the owner to designate a pilot application or approve a small synthetic reference service. Do not invent product requirements or create a mock product without approval.
- Record the minimum pilot interface needed for end-to-end tests: deployable artifact, health/metrics surface, one controlled feature-flag path and a safe way to inject a test defect.

**Acceptance**
- `docs/asdi/PILOT_TARGET.md` identifies the selected repository/service, environment and owner approval.
- If no target has been selected, feature-experiment and production self-healing E2E tickets remain blocked; infrastructure work may continue.
- The pilot uses synthetic/test data and cannot trigger real customer side effects.

### ASDI-003 — Establish protected repository baseline
**Priority:** P0 · **Type:** repository/security · **Blocked by:** ASDI-000

**Work**
- Establish branch protection/ruleset configuration, CODEOWNERS, protected generated/vendor paths and separate identities/credentials.
- Create separate identities with the minimum roles: agents (branch push + PR open only), Archon (status posting only), merge bot (merge-queue enqueue only), CI signing identity, production pull deployer.
- Keep agent merging disabled.
- Verify whether the GitHub ruleset can require statuses posted by the intended identity and whether merge queue accepts those external statuses.

**Acceptance**
- An agent identity cannot push to protected branches, merge, bypass rules or access production secrets.
- Archon cannot merge or push code; merge bot cannot push code; production deployer cannot be invoked by agent credentials.
- Judgment paths require human CODEOWNER approval.
- Test evidence documents GitHub ruleset and merge-queue semantics. If GitHub plan/API limitations prevent this, stop and report the precise blocker.

**Note:** GitHub behavior must be verified against the actual repository/plan; do not implement a permissive fallback.

---

## Gate 1 — Run contract and execution kernel

### ASDI-010 — Define run-contract schema and validator
**Priority:** P0 · **Type:** contract · **Blocked by:** ASDI-000

**Work**
- Implement the five authored fields: `objective`, `why`, `constraints`, `out_of_scope`, `done_check`.
- Allow genuinely absent constraints or out-of-scope items to be represented explicitly as empty, rather than forcing invented content.
- Add platform defaults: `boundaries`, `guardrails`, `output`, optional experiment-card reference and `task_type`.
- Validate types, required fields, command safety, allowed output kind and permitted override reasons.
- Treat numeric defaults as configuration, not universal truths.

**Illustrative defaults from Design REV H (not yet validated):** 200 turns, USD 8 spend, 90 minutes wall time, 400 changed lines. Store them centrally, make them adjustable, and mark them provisional.

**Acceptance**
- Valid/invalid contract fixtures cover required fields, empty optional lists, missing `done_check`, malformed commands, invalid budgets and unsupported output types.
- No run can be launched from an invalid contract.
- A contract records provenance: human-provided content, lead-agent-authored content and platform defaults.

### ASDI-011 — Implement run launcher and runtime adapter interface
**Priority:** P0 · **Type:** runtime · **Blocked by:** ASDI-010

**Work**
- Define a board-neutral launcher interface: create run, start runtime, stream structured events, stop/cancel, collect exit state, collect usage, verify `done_check`, and persist run evidence.
- Support the intended runtime set: Claude Code, Codex and Hermes, subject to actual CLI/runtime availability on the host.
- Keep runtime-specific behavior behind adapters. Do not hard-code Multica or Paperclip into the run contract.
- A board launches one build-agent task; the agent decides its implementation method.

**Acceptance**
- Contract tests exercise each adapter's lifecycle and error handling.
- A run can be cancelled and the child process exits; a cancellation must not merely change a database status.
- Runtime failure, host restart and missing executable are represented as durable failure states with evidence.
- No nested Archon invocation or nested build agents are introduced.

### ASDI-012 — Implement container-per-run sandbox
**Priority:** P0 · **Type:** security/runtime · **Blocked by:** ASDI-011

**Work**
- Start one container per run, with a workspace/branch dedicated to that run.
- Restrict egress to an explicit allowlist; deny all routes to production VM, production databases and production secrets.
- Ensure a run can push only to its own branch and cannot alter another active run's workspace.
- Inject narrowly scoped tokens at egress; do not mount persistent credentials or production secrets into the container.
- Add cleanup/reclamation for stopped containers and workspaces without deleting evidence.

**Acceptance**
- Two concurrent runs cannot read/write each other's workspaces.
- Network tests prove access to allowed endpoints and denial to production/private networks.
- Container has no production secret, no merge permission and no protected-branch write permission.
- Killing/cancelling a run stops its container and descendants.
- A failure to establish isolation blocks the run; there is no silent fallback to shared VM isolation for autonomous mode.

### ASDI-013 — Enforce `done_check` and per-run guardrails
**Priority:** P0 · **Type:** enforcement · **Blocked by:** ASDI-010, ASDI-011, ASDI-012

**Work**
- Implement Claude Code Stop-hook enforcement and launcher-level recheck for Codex/Hermes.
- Enforce turn, spend and wall-clock budgets; stop the runtime when a limit is reached.
- Reject completion if `done_check` is absent, fails, cannot be run or produces an indeterminate result.
- Persist command, exit code, duration, usage and output evidence.

**Acceptance**
- A passing task with failing `done_check` cannot report success.
- A failing task cannot be marked complete by agent self-report.
- Each budget is tested at below-limit, at-limit and over-limit conditions.
- Launcher recheck catches a runtime that exits successfully without the required validator passing.

### ASDI-014 — Structured run events and evidence record
**Priority:** P1 · **Type:** observability · **Blocked by:** ASDI-011

**Work**
- Persist run lifecycle, tool/process events, validator results, review references, PR URL, resource usage, strikes and final outcome in queryable structured records.
- Keep sensitive user data out of third-party model payloads by default.
- Define retention and redaction behavior as an open policy if not already established; do not invent retention periods.

**Acceptance**
- Run evidence survives service restart and can be retrieved by run ID and originating work-item ID.
- Logs are structured and agents can query approved observability data through controlled MCP interfaces.
- Secrets and tokens do not appear in logs or evidence packets.

**Gate 1 exit:** a per-run isolated execution can be launched, cancelled, bounded, self-verified and independently rechecked. A run cannot finish green if `done_check` fails.

---

## Gate 2 — Board, dispatch and D-9 integration

### ASDI-020 — Build D-9 compatibility spike
**Priority:** P0 · **Type:** spike · **Blocked by:** ASDI-001, ASDI-011, ASDI-012, ASDI-013

**Work**
- Implement the minimum adapter proof for Multica and Paperclip without committing the production architecture to either.
- Execute the three tests in §1.3: dispatch/runtime coverage, true cancellation + per-run container + budgets, and complete work-item-to-PR state reconciliation.
- Record support for Claude Code, Codex and Hermes with actual test results; no feature claims without execution evidence.

**Acceptance**
- A reproducible test report compares both candidates on the same host and repository.
- Report includes pass/fail, observed failure modes, operational steps, resource use and state-recovery evidence.
- Owner makes the D-9 selection in an ADR.
- Board-specific integration tickets remain blocked until D-9 is accepted.

### ASDI-021 — Implement selected board integration
**Priority:** P0 · **Type:** integration · **Blocked by:** ASDI-020 (owner accepts D-9)

**Work**
- Deploy the selected board server in Compose in the agent VM.
- Integrate board work items with the board-neutral launcher and selected runtimes.
- Persist work-item/run correlation and reconcile restarts.
- Keep the board authoritative for work-item state and Archon authoritative for pipeline-run state.

**Acceptance**
- A human-admitted work item launches a run without manual terminal/session startup.
- Run completion/failure/cancellation is reflected in the board and can be recovered after board restart.
- Nightly reconciliation detects and repairs safe status drift; ambiguous conflicts are surfaced, not silently overwritten.
- No board API is called from inside a build agent.

### ASDI-022 — Implement human admission and work-item types
**Priority:** P0 · **Type:** product workflow · **Blocked by:** ASDI-021

**Work**
- Human-only admission of work with WIP limit.
- Feature work uses experiment cards, not committee-style feature specs.
- Maintenance work uses standing charters approved once by the human.
- Agents may propose work but cannot transition proposals into admitted work.

**Acceptance**
- Unauthorized agent identity cannot admit or prioritize work.
- Feature work cannot enter normal delivery without an experiment-card reference.
- Maintenance work cannot run outside an approved charter.
- WIP behavior and blocked/queued state are visible to the human.

---

## Gate 3 — Archon outcome pipelines, GitHub poller and PR gate

### ASDI-030 — Configure Archon as outcome workflow engine
**Priority:** P0 · **Type:** workflow · **Blocked by:** ASDI-010, ASDI-014, ASDI-021

**Work**
- Implement the Archon pipelines around outcomes: PR gate/reviews/classification, fix/reset, production triage, experiment readout, flag janitor, verification sweeps, compounding and TRM.
- Keep build execution in the board-launched native runtime; Archon does not script the agent's internal workflow.
- Use Postgres-backed due dates and hourly idempotent sweeps for scheduled work. Do not add a separate durable workflow engine.
- Resolve whether the board and Archon use one Postgres server with separate databases or separate instances; document backup scope before production use.

**Acceptance**
- Archon pipeline runs have durable identity and state independent of board work-item state.
- Hourly sweeps are idempotent; replaying a sweep does not duplicate a ticket, PR comment, triage item or decision.
- Archon is never invoked from inside a build agent.
- No interactive approval nodes are used inside build runs.

### ASDI-031 — Implement local GitHub poller
**Priority:** P0 · **Type:** integration · **Blocked by:** ASDI-003, ASDI-030

**Work**
- Poll GitHub API every 60 seconds for relevant pushes, PRs, review comments and merge-queue entries.
- Reconcile current GitHub state each pass rather than assuming every event was observed.
- Persist cursors/last-seen state and make catch-up idempotent after outage or restart.
- Do not use GitHub Actions, webhooks or an inbound route to the agent side.

**Acceptance**
- A test event is detected within the configured polling interval under normal API availability.
- A missed poll/outage is caught up without lost work or duplicate processing.
- API quota/rate budget is measured and documented for the 60-second interval.
- Alert fires if no successful status post occurs for 5 minutes.
- If GitHub is unreachable, local state and production remain available; merges/pushes pause and poller catches up later.

### ASDI-032 — Implement three fresh-context scoped review passes
**Priority:** P0 · **Type:** verification · **Blocked by:** ASDI-030, ASDI-031

**Work**
- Implement independent review passes for: (1) correctness, (2) security boundaries, (3) contract/acceptance criteria.
- Each pass receives a fresh context and only its defined scope plus necessary source artifacts.
- At least one reviewer must be from a different model family than the build agent. Verify Archon can run a non-Claude model for this purpose.
- Review the quality of `done_check`; check whether tests and CI were modified, and flag those changes.
- Avoid broad unscoped reviewer swarms.

**Acceptance**
- Each pass produces structured findings: pass/fail/uncertain, severity, evidence, location and rationale.
- Missing or unavailable independent model prevents a complete review gate; it is not silently replaced by the builder.
- An unresolved/uncertain finding routes the PR to judgment.
- Tests demonstrate detection of seeded correctness, security and contract defects.

### ASDI-033 — Implement change classifier and `asdi/policy`
**Priority:** P0 · **Type:** policy · **Blocked by:** ASDI-003, ASDI-032

**Work**
- Implement judgment vs. agent-mergeable classes from §2.
- Add CODEOWNERS path floor; semantic class check; state-change check; flag check; diff-budget check; reviewer-uncertainty routing.
- Anything uncertain is judgment-class. Shared state changes remain judgment-class even behind a flag.
- Test/CI changes are called out in the packet; CI/test infrastructure changes are judgment-class.
- Keep the illustrative 400-line diff threshold configurable and pending confirmation.

**Acceptance**
- Seeded judgment changes are never classified as agent-mergeable.
- Unflagged user-visible behavior, new dependencies, migrations, state changes and ASDI rule changes route to judgment.
- Flagged product implementation can be agent-mergeable only when the behavior is default-off and no judgment-class state/security change is present.
- Any reviewer uncertainty forces judgment.
- Misclassification tests fail closed.

### ASDI-034 — Generate PR review packet and statuses
**Priority:** P0 · **Type:** verification/reporting · **Blocked by:** ASDI-032, ASDI-033

**Work**
- Generate a PR packet containing: objective/why, contract, `done_check` evidence, summary of changes, the agent's strongest argument against its own change, three review results, classifier result, test/CI changes, assumptions, unresolved questions and residual risks.
- Archon posts only status checks (`ci` and `asdi/policy`) using its status-only identity. Ensure `ci` cannot pass until required tests/build and review passes pass.
- Preserve full packet in local evidence store and link it from the PR.

**Acceptance**
- Every PR receives a packet before it can enter the merge queue.
- Packet is complete, traceable to the run contract and backed by actual test/review output.
- Archon cannot push commits, merge or enqueue the PR.
- GitHub receives the expected statuses from the expected identity.

**Gate 3 exit:** every PR carries the complete packet, three review results, `ci` and `asdi/policy`; merge remains disabled until Gate 5.

---

## Gate 4 — Repair, reset and early steering

### ASDI-040 — Implement bounded fix loop and strike ledger
**Priority:** P0 · **Type:** recovery · **Blocked by:** ASDI-034

**Work**
- Run an autonomous fix loop for mechanical findings and failed checks, with a maximum of two correction strikes.
- A failed check or repeated PR comment counts as a strike. Record source, evidence and timestamp.
- Design REV H names failed checks and repeated PR comments as strikes but does not fully specify the exact boundary between an agent's local inner-loop retries and an authoritative failed check. Record this granularity as an explicit owner decision/test before enabling automated reset; do not silently invent a counting rule.
- After two strikes, stop the current session and trigger reset; do not keep adding correction turns.

**Acceptance**
- Two strikes across the relevant failure sources trigger reset.
- The third correction is not sent to the same session.
- Strike history is durable and linked to the originating work item and run.
- A successful fresh run is distinguishable from a same-session retry.

### ASDI-041 — Implement brief-v2 reset controller
**Priority:** P0 · **Type:** recovery · **Blocked by:** ASDI-040

**Work**
- Lead agent rewrites the run contract as brief v2 using recorded failures and lessons.
- Start a fresh runtime session with a new run identity; preserve lineage to the original task and prior run.
- Escalate to the human only when the reset is blocked by an actual judgment decision. If a second attempt cannot proceed without judgment, report/drop under the design's rule and include it in the weekly report.

**Acceptance**
- Reset launches a fresh session with brief v2 and a clean execution context.
- Prior run evidence is retained but not automatically injected wholesale into the new context.
- Repeated reset failure does not create an infinite loop.
- Human escalation contains the precise decision, alternatives and evidence.


---

## Gate 5 — Compounding, TRM, metrics, notifications and controlled merge

### ASDI-050 — Implement compounding bot and rule-retirement evaluation
**Priority:** P1 · **Type:** learning · **Blocked by:** ASDI-041

**Work**
- Detect recurring corrections and propose CLAUDE.md or skill changes as PRs.
- Repeated correction becomes a request by default, not automatically a new hard hook.
- Add a retirement evaluation that checks whether an existing rule still changes outcomes, especially after a model release.
- Changes to ASDI's own rules remain judgment-class.

**Acceptance**
- A repeated correction produces a proposed, reviewable PR with source evidence.
- No hard rule/hook is added automatically.
- Human review is required to merge ASDI rule changes.
- Retirement candidates include evidence of non-effectiveness; no rule is silently deleted.

### ASDI-051 — Implement task-type TRM ledger
**Priority:** P1 · **Type:** autonomy governance · **Blocked by:** ASDI-034, ASDI-040

**Work**
- Track maturity per task type, not globally per agent/model.
- Implement T0/T1/T2 transitions from Design REV H:
  - New task types begin at T0.
  - T0 → T1 after three first-pass approvals.
  - T1 → T2 after five additional first-pass approvals and no reverts in 30 days.
  - Any T1 revert → T0.
  - T2 revert or escaped defect → T0.
  - Two consecutive resets at T2 → T1.
  - Model release → T1 until evaluation set passes.
- Judgment paths cap supervision at T1 at every level.

**Acceptance**
- Unit tests cover each transition, boundary date and reset condition.
- Every maturity transition records evidence and reason.
- No manual or agent override can raise a task type without the configured evidence.
- Human can inspect the ledger and transition history.

### ASDI-042 — Implement first-minute steer agent for T1 task types
**Priority:** P1 · **Type:** supervision · **Blocked by:** ASDI-040, ASDI-041, ASDI-051

**Work**
- Implement a steer check for T1 task types that validates early assumptions against the contract.
- Keep it lightweight and early; it should detect a wrong premise, not supervise every action.
- Record intervention as a strike where the design specifies.

**Acceptance**
- Seeded wrong-premise task is stopped/redirected early with an evidence-backed finding.
- T0 and T1 supervision behavior follows the TRM table; T2 uses sampled steering.
- The steer agent does not take over implementation or become a second builder.


### ASDI-052 — Implement metrics with countermeasures
**Priority:** P1 · **Type:** observability/governance · **Blocked by:** ASDI-014, ASDI-051

**Work**
Track the design's paired metrics:

| Speed / throughput metric | Required countermeasure |
|---|---|
| PR cycle time | Revert rate |
| Share of merges by bot | Bot-merge revert rate + misroutes found in sample |
| Deploys per day | Rollback rate + post-deploy incidents |
| Experiments decided per week | Expired flags + total flags |
| Detection → verified fix | Reopen rate |
| First-pass approval rate | Escaped defects + 1-in-10 deep review |
| Resets per run | Brief-v2 success rate |
| Rule count | Recurrence of the same correction |

**Acceptance**
- Every speed metric is displayed with its countermeasure.
- Data provenance and time window are visible.
- Do not use AI code share, lines of code or agent count as success goals.

### ASDI-053 — Implement human attention surface and notifications
**Priority:** P1 · **Type:** human interface · **Blocked by:** ASDI-033, ASDI-051, ASDI-052

**Work**
- Present the five human touchpoints: admit work; decide escalations; review judgment-class PRs; gate exposure/irreversible operations; weekly system loop.
- Notify for actionable decisions, production/Studio failure, poller stale state, repeated defects, reset requiring judgment and approval-required changes.
- Routine run activity remains in the board/dashboard; do not notify on every agent event.

**Acceptance**
- Human can see queue, blocked decisions, judgment PRs, experiment verdicts, production incidents and system health in one operational surface or linked views.
- Notifications contain action, reason, evidence and link.
- No routine status spam in the test scenario.

### ASDI-054 — Enable T1 agent merge through merge queue (feature-flagged)
**Priority:** P0 for autonomy · **Type:** merge control · **Blocked by:** ASDI-003, ASDI-033, ASDI-034, ASDI-051, ASDI-052, ASDI-053

**Work**
- Keep agent merge disabled by default until all required gates pass.
- For T1+ agent-mergeable work, merge bot may enqueue only when `ci`, three reviews and `asdi/policy` are green.
- GitHub merge queue performs the protected merge. Agents cannot merge, bypass or push to main.
- T0 agent-mergeable work is merged by the human.
- Judgment-class changes always need the human, at every TRM level.
- Sample deep reviews at T1: 1 in 5; T2: 1 in 10.
- Automatic revert when post-merge checks fail; revert storm circuit breaker pauses agent merges.

**Acceptance**
- T0, T1, T2 and judgment-class test cases follow the exact authority matrix.
- An agent token cannot merge under any condition.
- Revert storm pauses the merge bot and generates an actionable alert.
- Sampled review records are retained and can demote the task type based on evidence.
- Rollback/revert capability is tested before enabling the feature flag.

**Gate 5 exit:** compounding and TRM evidence works; human notifications are actionable; only proven T1+ agent-mergeable changes can enter the merge queue autonomously.

---

## Gate 6 — P-1 production and host operations

### ASDI-060 — Provision single-host P-1 zones and resource reservations
**Priority:** P0 for production · **Type:** infrastructure · **Blocked by:** ASDI-001

**Work**
- Implement the Mac Studio-only topology: production VM; agent VM; staging VM; ops VM; host-level vllm-mlx.
- Reserve CPU/memory for production and a model instance for products. Cap agent/staging/ops resource use below production reservations.
- Place board, Archon, agent CLIs and local CI in the agent zone; registry and monitoring in ops; production workloads and release puller in production.
- Choose VM manager, separate volumes and resource caps only after owner-approved ADRs.

**Acceptance**
- `docs/asdi/P1_TOPOLOGY.md` documents approved VM, network, memory/CPU and storage boundaries.
- Production reservation remains intact under agent-load stress tests.
- Production and agent/staging networks are separated; no route exists from agent/staging to production.
- vllm-mlx product-serving capacity is reserved; agent model pool is preemptible.

### ASDI-061 — Implement production-first admission and preemption
**Priority:** P0 for production · **Type:** scheduling/safety · **Blocked by:** ASDI-060, ASDI-014

**Work**
- Reduce agent concurrency when production SLO error budget burns, production VM memory is under pressure or reserved product model instance queues.
- Support preemption/cancellation of agent work; production workloads cannot be preempted by agents.
- Use explicit thresholds from owner-approved configuration; do not invent SLOs or memory thresholds.

**Acceptance**
- Each trigger reduces or preempts agent work according to policy.
- Production CPU/memory reservation remains protected during simulated agent saturation.
- Trigger and recovery events are logged and visible.
- No automatic preemption of production service occurs.

### ASDI-062 — Implement local CI, signed image registry and release puller
**Priority:** P0 for production · **Type:** delivery/release · **Blocked by:** ASDI-060, ASDI-003

**Work**
- CI runs locally in agent VM.
- Build and sign images using a dedicated CI identity; publish to registry container in ops VM.
- Production pull deployer pulls and verifies signed images; no push path from agent/CI into production.
- Implement the six-stage path: CI → staging deploy → staging test → production deploy → production smoke test → done.
- Blue/green proxy with weighted canary; automatic rollback on configured error-rate or latency breach.

**Acceptance**
- Unsigned/untrusted image is rejected by production deployer.
- Agent and staging zones cannot invoke production deployer or reach production network.
- A known-bad release automatically rolls back without human action.
- New behavior stays default-off after deployment.
- Release evidence records image digest, signer, environment, smoke results and rollback decision.

### ASDI-063 — Implement external probe, backup and host-recovery procedures
**Priority:** P1 · **Type:** reliability/operations · **Blocked by:** ASDI-060

**Work**
- External probe outside the Studio/home network with push alerts; test a Studio/network outage.
- Encrypted offsite backups; monthly restore drill onto replacement hardware or a documented equivalent restore target.
- FileVault/UPS operating procedure, authenticated restart after planned reboot, no sleep and no automatic OS updates.
- Separate volumes per role; disk janitor for images, logs and snapshots.

**Acceptance**
- Cutting the Studio's network triggers an external alert while local monitoring is unavailable.
- Restore drill proves data can be restored; evidence includes backup identity, restore steps and outcome.
- Migrations are blocked until a restore succeeds.
- Disk janitor cannot delete active images, active run workspaces or the last known-good backup.
- Host reboot and FileVault unlock dependency is documented and tested in a planned maintenance window.

### ASDI-064 — Implement polling, DB backup scope and nightly reconciliation
**Priority:** P1 · **Type:** operations/state · **Blocked by:** ASDI-030, ASDI-031, ASDI-060

**Work**
- Select one Postgres server with separate board/Archon databases or two instances; record backup/restore implications.
- Nightly compare board work-item state and Archon pipeline-run state.
- Detect stale GitHub polling/status, missed sweeps and overdue items; reconcile idempotently.

**Acceptance**
- Database topology and backup scope are documented.
- Simulated drift is detected and either safely repaired or surfaced for human resolution.
- Poller alert fires after 5 minutes without a successful status post.
- A missed sweep is caught up without duplicate downstream actions.

**Gate 6 exit:** a bad deployment rolls back without human intervention; cutting Studio network triggers an external alert; a restore succeeds. The single-host SPOF remains explicitly accepted, not described as eliminated.

---

## Gate 7 — Feature flags and experiment loop

### ASDI-070 — Deploy GrowthBook and integrate default-off flags
**Priority:** P1 · **Type:** product/experimentation · **Blocked by:** ASDI-062

**Work**
- Self-host GrowthBook.
- Require every behavior change to ship behind a default-off flag; expose flag metadata to the PR packet and policy check.
- Support 2–3 agent-created variants for a design fork; agents choose how variants differ.
- Provide preview and human-controlled exposure ramp.

**Acceptance**
- New product behavior is default-off after deployment.
- Agent cannot ramp exposure beyond the human-authorized level.
- State changes/irreversible effects remain judgment-class even behind a flag.
- Feature can be disabled quickly; flag kill does not substitute for deleting killed code.

### ASDI-071 — Define experiment-card lifecycle and readout
**Priority:** P1 · **Type:** product/measurement · **Blocked by:** ASDI-070, ASDI-030, ASDI-002

**Work**
- Implement experiment cards with hypothesis, metric, kill line, guardrails, expiry, variants and flag.
- Human admits the experiment; agent implements variants; human previews the running product and controls exposure.
- Produce readout leading with kill line, guardrails, sample/power status and metric results.
- Support sequential tests/bandits for low-traffic cases as indicated by the stack.
- A kill verdict means delete the code. Expiry without a verdict means kill.

**Starting defaults to confirm, not universal validated thresholds:** 14-day expiry, experiment WIP limit 3. The CSV/JSON example's `<15% after 14 days at 50% exposure` is illustrative only and must not be copied as a generic kill line.

**Acceptance**
- An experiment cannot be admitted without a metric, kill line, guardrails and expiry.
- No readout claims a winner before its configured minimum sample/power condition.
- Human exposure ramp and keep/kill decisions are explicit durable actions.
- Expired/no-verdict experiment is killed and cleanup work is created.
- A kill verdict removes the implementation code, not merely the flag.

### ASDI-072 — Implement flag janitor and experiment WIP enforcement
**Priority:** P2 · **Type:** maintenance · **Blocked by:** ASDI-071

**Work**
- Periodically find expired flags, stale experiments and excess flag debt.
- Open cleanup PRs for completed/expired flags; enforce experiment WIP.

**Acceptance**
- Janitor is idempotent and does not modify code directly.
- Expired experiment without verdict is killed according to policy.
- Cleanup PR is agent-mergeable only when it does not alter state/security/product behavior beyond removing a completed flag.

---

## Gate 8 — Production self-healing loop

### ASDI-080 — Deploy Bugsink and telemetry stack
**Priority:** P1 · **Type:** observability · **Blocked by:** ASDI-060

**Work**
- Deploy Bugsink as the primary error tracker; use GlitchTip only if licence constraints require it.
- Deploy Prometheus, Loki and Grafana.
- Make structured logs and relevant metrics queryable by agents through scoped MCP servers.
- Ensure sensitive logs remain local; external APIs receive scrubbed data only unless the owner approves a different policy.

**Acceptance**
- A seeded application exception reaches Bugsink with a stable signature and useful context.
- Metrics and logs can be queried by the triage workflow with least-privilege access.
- Secrets and unnecessary user data are absent from external model payloads.

### ASDI-081 — Implement daily triage and defect-contract generation
**Priority:** P1 · **Type:** operations/AI · **Blocked by:** ASDI-080, ASDI-030, ASDI-022, ASDI-002

**Work**
- Daily Archon workflow reads Bugsink and Grafana, clusters incidents, scores impact/frequency/data risk/revenue and opens board work items under the approved `prod-defects` charter.
- Use a local model for logs containing user data; external/API models only on scrubbed inputs (D-4 pending owner confirmation).
- Deduplicate incidents, retain sample evidence and affected endpoint/user counts where available.
- Only defects below the human-approved charter severity threshold are autonomous.

**Acceptance**
- Seeded duplicate errors cluster into one defect item.
- Defect contract records cluster, severity dimensions, charter, evidence, technical test and production outcome test.
- Above-threshold/security/data-risk incidents escalate instead of being automatically fixed.
- No user data is sent to an external model in the default configuration.

### ASDI-082 — Implement defect repair and 72-hour production verification
**Priority:** P1 · **Type:** self-healing · **Blocked by:** ASDI-081, ASDI-062, ASDI-040

**Work**
- Dispatch in-charter defect contracts to isolated agents.
- Require a reproduction test and technical `done_check`.
- After deployment, verify for 72 hours: error signature absent and endpoint error rate at or below its defined baseline.
- If outcome fails, reopen the defect, record a strike, and notify only on repeat/meaningful escalation.

**Acceptance**
- A seeded production defect is detected, ticketed, reproduced, fixed, deployed and observed.
- Defect cannot close at merge or deploy alone.
- Successful close occurs only after the 72-hour production outcome check passes.
- A failed outcome reopens the defect and contributes a strike.
- Automatic rollback remains active during the verification window.

**Note:** 72 hours is the Design REV H starting default to confirm. Implement as a configurable policy with a visible value; do not hard-code it in multiple workflows.

---

## Gate 9 — Probation and controlled autonomy

### ASDI-090 — Run T0 probation for first task types
**Priority:** P0 before agent merge · **Type:** rollout/governance · **Blocked by:** Gates 1–8 as applicable

**Work**
- Start every new task type at T0.
- Pilot batch tasks on three items; first three runs have live links.
- For structural work, human agrees plan assumptions; for feature work, human previews the running prototype.
- Human merges agent-mergeable changes at T0.
- Collect first-pass approvals, resets, reverts, escaped defects and evidence quality.

**Acceptance**
- First three runs are traceable end-to-end.
- All T0 agent-mergeable PRs require human merge; judgment changes always require human approval.
- No agent merge is enabled merely because the pipeline is green.
- Promotion to T1 occurs only after three recorded first-pass approvals for that task type.

### ASDI-091 — Enable and audit T1/T2 autonomy
**Priority:** P1 · **Type:** rollout/governance · **Blocked by:** ASDI-090, ASDI-054

**Work**
- Promote only task types that satisfy the specified TRM thresholds.
- Apply 1-in-5 deep sampling at T1 and 1-in-10 at T2.
- Apply demotions on reverts, escaped defects, consecutive resets and model releases exactly as in ASDI-051.
- Keep judgment-class supervision capped at T1.

**Acceptance**
- Autonomous merge is enabled only for T1+ agent-mergeable task types.
- Sampling actually selects and records the required proportion over the applicable population/window.
- Revert/escaped-defect/model-release scenarios trigger the required demotion.
- Owner can disable agent merge globally without changing agent tokens or rewriting the board.

### ASDI-092 — Weekly system loop and rule retirement
**Priority:** P2 · **Type:** continuous improvement · **Blocked by:** ASDI-050, ASDI-051, ASDI-052, ASDI-071, ASDI-082

**Work**
- Produce weekly digest: paired metrics, TRM transitions, reset outcomes, experiment verdicts, escaped defects, reverts, poller health, flag debt, rule count and recurrence.
- Human reviews the system, not routine run details.
- Review hard rules/requests after model releases; remove rules that no longer improve outcomes and demote preferences mistakenly promoted to hard gates.

**Acceptance**
- Weekly report is reproducible from stored events and clearly distinguishes facts from recommendations.
- Every metric has its paired countermeasure.
- Rule promotions/demotions are human-reviewed when they change platform enforcement.
- The system does not optimize AI code share, LOC or number of agents.

---

## 5. End-to-end acceptance scenarios

The prototype is not complete when services are merely installed. These scenarios must pass in the integrated system.

### E2E-A — Feature from admission to keep/kill

1. Human admits an experiment card with hypothesis, metric, kill line, guardrails, expiry and default-off flag.
2. Board dispatches the work; lead compiles the run contract; one build agent executes in a per-run container.
3. Agent passes `done_check`; Archon runs three scoped reviews and classification.
4. PR packet is complete; T0 requires human merge (later T1+ may use merge bot if eligible).
5. Local CI deploys to staging, tests it, then deployer pulls signed image and deploys to production with the flag off.
6. Human previews and authorizes exposure; GrowthBook collects the readout.
7. Human decides keep/kill; kill deletes code, not only the flag.

**Pass:** complete traceability from experiment card to PR, image digest, exposure decision and final verdict; no unauthorized exposure.

### E2E-B — Production defect to verified recovery

1. Seed a controlled application error.
2. Bugsink captures it; daily triage clusters it and creates a defect contract under the approved charter.
3. Agent reproduces/fixes in an isolated run; independent verification and policy checks pass.
4. Release bot deploys the signed fix through the standard pipeline.
5. Production verification observes the signature/endpoint for the configured 72-hour window.

**Pass:** the defect closes only after production outcome verification; failed outcome reopens it and records a strike.

### E2E-C — Judgment boundary and recovery

1. Submit a task touching an authentication/security or shared-state boundary.
2. Seed a repeated review failure to trigger two strikes.
3. Verify the reset creates brief v2 and a new session.
4. Verify classification remains judgment-class even if code is behind a flag.

**Pass:** no merge without human judgment approval; reset is fresh; no agent obtains production access.

### E2E-D — Host, GitHub and resource failure

1. Make GitHub unreachable; local loops retain state and production continues serving.
2. Restore GitHub; poller catches up without duplicates.
3. Saturate agent workload; production resource reservations remain protected and agent work is throttled/preempted.
4. Cut Studio network; external probe alerts.
5. Restore from encrypted offsite backup to a recovery target.

**Pass:** no lost lifecycle state, production-first admission works, outage is detected externally and restore succeeds.

---

## 6. Global Definition of Done

ASDI P-1 prototype is accepted only when all of the following are demonstrated with evidence:

- [ ] One Mac Studio is the only host; VM/network/resource zones are documented and enforced.
- [ ] D-9 board choice is made from an actual compatibility spike and recorded by the owner.
- [ ] Human admission is enforced; agent proposals cannot self-admit.
- [ ] A run contract has the five authored fields and a mandatory `done_check`.
- [ ] Claude Code, Codex and Hermes support is tested or limitations are explicitly recorded.
- [ ] Every autonomous run has a per-run container, egress allowlist, own branch and no production route.
- [ ] Turn, spend and wall-clock guardrails are enforced by the launcher/runtime path.
- [ ] Archon wraps outcomes; it does not script the builder or run nested inside agents.
- [ ] Local GitHub poller works at 60 seconds; no Actions or webhooks; catch-up is idempotent.
- [ ] Every PR receives three scoped fresh-context reviews, with a different model family represented, plus a complete packet and policy result.
- [ ] Change classification, CODEOWNERS and merge-queue permissions fail closed.
- [ ] Two strikes trigger brief-v2 reset and a fresh session.
- [ ] Compounding proposals and TRM transitions are evidence-based and reviewable.
- [ ] T0 human merge is proven; T1/T2 autonomous merge is limited to eligible task types and can be globally disabled.
- [ ] Production release is pull-based from a signed local image registry; bad deployment rolls back automatically.
- [ ] Production-first admission protects the product VM and reserved model capacity.
- [ ] Default-off feature flags, experiment readout and keep/kill deletion are demonstrated.
- [ ] Production defect triage, charter-based repair and production outcome verification are demonstrated.
- [ ] External Studio outage alert, encrypted offsite backup and successful restore drill are demonstrated.
- [ ] Five human touchpoints are the only routine human responsibilities; routine terminal monitoring is unnecessary.

A failed item means the relevant capability is not accepted. Do not describe the system as fully autonomous or production-ready while a hard-rule acceptance item remains unverified.

---

## 7. Open decisions and parameters — do not invent

| Item | Current source position | Required action |
|---|---|---|
| D-9 board | Multica current in Design; Paperclip one-host recommendation in Stack; open | Run ASDI-020; owner chooses |
| D-4 log/model privacy | Local model on raw user-data logs; API model only on scrubbed logs recommended | Owner confirms; default local-only for sensitive logs |
| D-8 event intake | Local 60-second poller recommended | Verify API rate budget and status semantics |
| Postgres topology | One server with two DBs or two instances | ADR and backup-scope test |
| VM manager | Not selected | Owner decision after compatibility/resource test |
| Tunnel provider | Not selected | Owner decision; no inbound route into agent zone |
| Proxy | Traefik or Caddy | Owner/implementation decision after P-1 integration test |
| CPU/memory reservations | Required, values unspecified | Benchmark and owner approval |
| SLO / error-budget thresholds | Required, values unspecified | Define before enabling production-first preemption and auto rollback |
| Defect severity threshold | Scoring dimensions specified, threshold unspecified | Owner-approved charter threshold |
| Experiment minimum sample/power | Required to avoid noisy verdicts, values unspecified | Define per product/experiment; no generic threshold invention |
| TRM thresholds | Defined in Design REV H | Implement exactly; no ad hoc promotion |
| Diff budget | 400 changed lines illustrative | Keep configurable; owner confirms |
| Run guardrails | 200 turns / $8 / 90 min illustrative | Keep configurable; owner confirms |
| Experiment WIP/expiry | 3 / 14 days starting defaults to confirm | Configurable; owner confirms |
| Production verification | 72 h starting default to confirm | Configurable; owner confirms |
| Domain/TLS, traffic and backup target | Not specified | Owner decision and tested configuration |

---

## 8. Final instruction to Codex

Begin with **ASDI-000: inspect the actual repository**. Return the repository-grounded map and the D-9 decision test plan before implementing the next gate. Then proceed in the dependency order above.

Do not treat this backlog as permission to deploy to a real production environment, expose features to users, run migrations or trigger external side effects. The first complete lifecycle demonstration must use a controlled test application/environment, synthetic data and explicitly authorized exposure. Preserve the seven hard rules throughout.
