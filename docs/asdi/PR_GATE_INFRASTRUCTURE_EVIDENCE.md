# PR gate infrastructure evidence

**Date:** 2026-11-19  
**Result:** **Generic Phase 4 control-plane infrastructure implemented and builder-tested; Phase 4 exit not claimed**

## Implemented

### Durable local event transport

[`events/journal.py`](../../events/journal.py) provides:

- append-only fsynced JSONL events with monotonic IDs;
- durable poller cursor and health state;
- exact-once catch-up dispatch from the last successful cursor;
- failure preservation without advancing the cursor;
- stale/backlog alerts based on configured poller interval.

This models the passive-GitHub/local-poller boundary. It does not add webhooks, inbound GitHub-triggered execution, or cloud dependencies.

### Fail-closed classifier

[`events/classifier.py`](../../events/classifier.py) classifies changed paths from explicit configuration and a feature map. It detects protected verification paths, explicit judgment paths, uncovered product paths and verification/product mixes. A protected/product mix returns `split_required`; uncovered or judgment paths return `human_required`.

### PR gate and packet

[`events/pr_gate.py`](../../events/pr_gate.py) evaluates one immutable PR head and emits an `asdi.pr-packet/v1` payload. It requires:

- `ci` to pass;
- verifier result bound to the exact PR head;
- review result bound to the exact PR head;
- base branch to match;
- no protected/product path mix;
- no uncovered product path.

A judgment or uncovered path becomes `human_required`. A mix becomes `split_required`. Missing or failed checks become `blocked`. A new PR head invalidates prior review/verifier evidence.

`asdi/policy` is emitted by this evaluation as required by Build Guide V4 §10.1, rather than accepted as a circular gate input. The packet records the derived policy status: pass for eligible or human-required routing, fail for split-required or blocked.

### Post-merge and deployment eligibility

`post_merge_check` requires CI and verifier success bound to the exact `main` commit. Failure emits the required auto-revert branch and reason. Deployment is eligible only for an exact commit with a passing `main` result; stale results cannot authorize a new commit.

`deployment_decision` now validates the whole post-merge result contract: exact commit binding, `passed: true`, empty failures, `deployment_eligible: true`, and no required auto-revert. A forged or partial result with `passed: true` cannot authorize deployment or release readiness.

[`events/release_gate.py`](../../events/release_gate.py) adds a separate release-readiness boundary. `events.cli release-readiness` reads the exact commit's durable main state, requires a `sha256:` artifact binding, rejects stale or failed post-merge results, and records a `ready` or `blocked` request. Every result is `human_required` and `release_executed: false`; the command performs no build, registry push, deploy, exposure or authorization. This is governance infrastructure, not Phase 7 exit evidence.

### Merge dry-run boundary

[`events/merge_gate.py`](../../events/merge_gate.py) accepts only an eligible `asdi.pr-packet/v1` packet and feeds the Phase 0 fail-closed merge policy. It records whether the outcome is `eligible`, `human_required`, `blocked` or `refused`; `merge_executed` remains false in every case. T0 and judgment paths remain human-governed, while agent/status identities are refused.

### Independent review command boundary

[`events/review.py`](../../events/review.py) executes one explicit, absolute, shell-free reviewer command in fresh context with no inherited host environment. It provides the packet, changed diff and output path through placeholders; enforces a timeout; validates `asdi.review-result/v1`; requires `reviewed_commit` to match the PR head; and blocks on malformed output. `act` findings must include evidence. The normalized result records model, `independent_family`, status, findings and execution provenance.

### Untrusted-text boundary

[`events/comment_gate.py`](../../events/comment_gate.py) implements Pass 1's two required boundaries. Only allowlisted comment resumers may instruct ASDI or request `/asdi resume`; other comments remain external data and cannot trigger execution. Agent-authored claims are placed in a delimited block marked as data, length-capped, and any embedded end marker is escaped so the reviewer cannot break the untrusted-text boundary.

### Operational CLI

[`events/cli.py`](../../events/cli.py) exposes local, durable operations:

- `append-event`;
- `catch-up` with configured PR-gate dispatch;
- `health`;
- `gate`;
- `post-merge`;
- `deployment-decision`.
- `merge-dry-run`.
- `review`.
- `review-event`;
- `comment-gate`;
- `record-verification`;
- `record-main-verification`;
- `run-pr-gate`;
- `reconcile-github`;
- `agent-claims-block`;
- `review-input`.

Catch-up persists each eligible PR packet as `packets/pr-<number>-<head>.json`, updates `latest-policy.json`, records the poller cursor and health, and preserves all output on disk for later audit. `post-merge` and `deployment-decision` persist their exact evidence and decisions separately. The CLI uses no webhooks, no GitHub Actions and no inbound network listener.

The untrusted-text boundary is enforced in the event CLI: allowlisted owners can request resume, non-allowlisted comments remain inert data, and agent-authored claims are delimited, length-capped and end-marker-escaped before reviewer input.

The Pass 1 review boundary now accepts an explicitly configured reviewer command and normalizes its result into the PR-gate review contract. It validates head binding, output schema, finding buckets and `act`-finding evidence. A malformed or stale reviewer result becomes `blocked`, never pass.

`review-event` connects that review boundary to the durable workflow. It first persists the complete review execution result, including command provenance and captured output; it then appends only normalized, head-bound gate fields as `github.review_completed`. The event never carries reviewer execution logs or stdout, while the separately persisted review result preserves the full execution audit.

### Event-driven PR workflow

[`events/pr_workflow.py`](../../events/pr_workflow.py) persists workflow state across separately arriving events rather than treating one PR event as a complete gate input. A normalized `github.pull_request` event records PR number, exact 40-character head SHA, base branch and changed paths as `asdi.pr-state/v1`; verification and review may arrive separately. Review evidence embedded in the initial PR event is ignored.

`github.verification_completed` accepts only a head-bound verifier result and explicit CI status; it rejects `asdi/policy` as an input. [`events/verification.py`](../../events/verification.py) maps a valid evidence manifest to this event and requires source `pr-head`, exact subject/result commit, a non-empty feature list, every feature pass, and every negative control caught. A missed negative control becomes verifier `fail`, never pass. CLI `record-verification` separately persists the complete evidence record and appends only the normalized gate payload.

A later `github.review_completed` event must bind `reviewed_commit` to the current head, carry a boolean `passed` value that agrees with its `pass | fail | blocked` status, and reference the currently persisted PR state. Only then does the workflow invoke the existing fail-closed [`events/pr_gate.py`](../../events/pr_gate.py), persist the packet separately from state, and expose the policy decision. The CLI retains the short `packets/pr-<number>-<head>.json` filename in addition to durable `pr-workflow/pr-state/pr-<number>/<head>.json` and `pr-workflow/packets/pr-<number>/<head>.json` locations.

The state machine is fresh-head safe: a new PR head creates a new pending state and does not carry forward prior review or verifier evidence; historical per-head files remain available. A stale review is recorded as a rejection without mutating the current state. A review arriving before its PR is also rejected. Invalid or unsupported workflow events are written under `workflow-rejections/`, while successful dispatch results are written under `workflow-results/` and `latest-pr-workflow.json`.

### Event-driven post-merge workflow

[`events/main_workflow.py`](../../events/main_workflow.py) records only `main` pushes by exact 40-character commit, then accepts verification separately. A verification result must carry CI and a manifest-bound verifier for the same commit. The store invokes the existing post-merge check, persists its pass/fail result and auto-revert plan by exact commit, and computes deployment eligibility from only that exact matching result. A newer `main` commit cannot inherit an older result. The CLI catch-up dispatches these events and persists each under `main-workflow-results/`, with the latest decision in `latest-main-workflow.json`.

`record-main-verification` accepts only evidence whose manifest source is `main`, binds the manifest subject and result to the exact landed commit, checks every feature and negative control, and appends `github.main_verification_completed`. The complete evidence record remains external to the event payload.

`run-main-verification` now executes an explicit source-main verifier command and connects it to this post-merge workflow. The adapter enforces the same exact-commit evidence, runtime boundary and fail-closed status rules as the PR verifier command. The pipeline persists complete execution separately, appends normalized post-merge evidence, computes exact-commit deployment eligibility, records the auto-revert requirement on red, and never deploys or re-executes already-recorded verification.

### Integrated PR-gate pipeline

[`events/pipeline.py`](../../events/pipeline.py) connects the separate control-plane slices into one operational sequence. `run-pr-gate` consumes an already verified evidence manifest, maps it to the current durable PR head, executes the explicit fresh-context reviewer, persists the complete review result separately, appends only normalized review evidence, dispatches events through [`events/dispatcher.py`](../../events/dispatcher.py), assembles the packet, and invokes the existing merge dry-run.

The pipeline never merges, pushes, posts to GitHub, deploys, or executes an agent. It accepts only evidence already produced by the verifier boundary. With a passing manifest and caught negative control, a T0 pipeline reports the gate `eligible` and merge authority `human_required`; with a missed negative control, it reports `blocked` and refuses merge authorization. Reviewer execution provenance remains in the separate full review result, not in normalized workflow state.

The pipeline can now execute an explicit verifier command itself through [`events/verifier_command.py`](../../events/verifier_command.py). This adapter is absolute, shell-free, timeout-bounded and environment-restricted. It validates exact-head evidence, EvidenceStore binding, negative controls and verifier-only runtime boundaries; missing, stale, failed or nonzero-exit results become a red verifier. The complete verification execution remains separate from normalized journal state.

The active `owner_invoked_audit` decision is now enforced by [`events/independent_audit.py`](../../events/independent_audit.py). When selected, a cloud Claude audit must be durably bound to the exact PR number/head and active owner decision before an otherwise green packet remains eligible. Missing, failed, stale or invalid audits downgrade the packet to blocked; the merge dry run remains non-executing and T0 remains human-governed. See [`INDEPENDENT_AUDIT_EVIDENCE.md`](INDEPENDENT_AUDIT_EVIDENCE.md).

## Builder-side execution

```sh
PYTHONPATH=.:src python3 -m unittest tests.test_events_pr_gate -v
PYTHONPATH=.:src python3 -m unittest discover -s tests -v
```

Observed latest full suite after derived-CI hardening, release-readiness, deployment-evidence validation, PR #2 review remediation, run-ID schema enforcement and owner-invoked audit enforcement: **217 tests, OK, 4 expected AF_UNIX/socket-binding skips**. Focused evidence covered pending verification/review states, stale and orphan rejection, malformed payloads, new-head invalidation, separate durable packets, evidence-derived PR-head verifier status, evidence-derived exact-main verifier status, missed negative controls, wrong-source rejection, explicit reviewer execution, explicit PR/main verifier-command execution, static-check-derived CI status, exact-main deployment eligibility, forged passed-result rejection, failed-main auto-revert planning, idempotent main verification replay, mixed-journal cursor preservation, stale-main rejection, artifact-bound release readiness, setup-failure cleanup, invalid run-ID rejection, cloud Claude audit binding/ingestion, and the integrated PR verifier → review → independent audit → policy → T0 merge-dry-run sequence.

## Limits

This is reusable control-plane infrastructure. It is not Phase 4 exit evidence, because Phase 3 remains blocked pending the owner's pilot decision and Phase 4 has not executed the complete real PR lifecycle. The workflow accepts normalized local events; a GitHub API reconciler and launcher invocation inside that reconciler remain subsequent integration slices. Auto-revert planning does not execute Git or deployment actions.

Explicit verifier commands and evidence-file ingestion now share one derived-CI rule. Static-gate output is bound into the evidence statement, so `record-verification` and `record-main-verification` reject a caller-declared CI status that disagrees with the named checks. The validator preserves real gate diagnostics and the non-static `verify:` check, while command/evidence comparison normalizes optional `blocking` fields. No live Docker or independent acceptance evidence was produced by this slice.

The first read-only GitHub reconciler slice is now implemented and builder-tested in [`events/github_reconciler.py`](../../events/github_reconciler.py). It normalizes exact PR heads and `main` commits into the existing journal, deduplicates current-state facts, uses a bounded shell-free `gh` command and minimal proxy environment, and fails closed without appends on command errors. The real authenticated probe remains blocked by an invalid host GitHub token; see [`GITHUB_RECONCILER_EVIDENCE.md`](GITHUB_RECONCILER_EVIDENCE.md).

## Live rehearsal on the current branch

A local rehearsal of `run-pr-gate` used the real PR-head evidence manifest
`m-1b048a893f174465d875ff3b` for head `80fa15b`, the actual
`main...80fa15b` diff, and a process-isolated fixture reviewer. It exposed
three real defects, now fixed:

1. `events.cli` defaulted `--feature-map` to `config/coverage.yaml`, which is
   a metrics configuration and cannot be parsed as a feature map. The new
   `config/features.yaml` maps the three toy-notes features to repository
   paths and is now the default.
2. `events.pipeline` and the independent-audit CLI commands passed a decision
   file path where `OwnerDecisionLog` expects a root directory, crashing when
   the ledger file already existed.
3. A test used the same incorrect constructor form and masked the defect.

After the fixes, the rehearsal completed with:

```text
head_sha: 80fa15b153d884788a71a9cfec84b6716e87b474
independent_audit_enforced: true
independent_audit.status: missing
independent_audit.failures: independent audit is pending
base_policy_decision: split_required
classification: split_required
packet_policy: blocked
merge_decision: blocked
merge_executed: false
```

The `split_required` result reflects the real broad PR mixing protected
configuration/verification paths with product paths. It is recorded honestly
and is not converted to a pass. The rehearsal proves that the gate now runs,
binds exact-head evidence, enforces the pending cloud Claude audit, and never
executes a merge.
