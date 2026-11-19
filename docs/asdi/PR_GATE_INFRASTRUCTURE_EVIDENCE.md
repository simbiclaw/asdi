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

- `ci` and `asdi/policy` to pass;
- verifier result bound to the exact PR head;
- review result bound to the exact PR head;
- base branch to match;
- no protected/product path mix;
- no uncovered product path.

A judgment or uncovered path becomes `human_required`. A mix becomes `split_required`. Missing or failed checks become `blocked`. A new PR head invalidates prior review/verifier evidence.

### Post-merge and deployment eligibility

`post_merge_check` requires CI and verifier success bound to the exact `main` commit. Failure emits the required auto-revert branch and reason. Deployment is eligible only for an exact commit with a passing `main` result; stale results cannot authorize a new commit.

### Merge dry-run boundary

[`events/merge_gate.py`](../../events/merge_gate.py) accepts only an eligible `asdi.pr-packet/v1` packet and feeds the Phase 0 fail-closed merge policy. It records whether the outcome is `eligible`, `human_required`, `blocked` or `refused`; `merge_executed` remains false in every case. T0 and judgment paths remain human-governed, while agent/status identities are refused.

### Operational CLI

[`events/cli.py`](../../events/cli.py) exposes local, durable operations:

- `append-event`;
- `catch-up` with configured PR-gate dispatch;
- `health`;
- `gate`;
- `post-merge`;
- `deployment-decision`.
- `merge-dry-run`.

Catch-up persists each eligible PR packet as `packets/pr-<number>-<head>.json`, updates `latest-policy.json`, records the poller cursor and health, and preserves all output on disk for later audit. `post-merge` and `deployment-decision` persist their exact evidence and decisions separately. The CLI uses no webhooks, no GitHub Actions and no inbound network listener.

## Builder-side execution

```sh
PYTHONPATH=.:src python3 -m unittest tests.test_events_pr_gate -v
PYTHONPATH=.:src python3 -m unittest discover -s tests -v
```

Observed latest focused merge-boundary suite: **4 tests, OK**.

## Limits

This is reusable control-plane infrastructure. It is not Phase 4 exit evidence, because Phase 3 remains blocked pending the owner's pilot decision and Phase 4 has not executed the complete real PR lifecycle.
