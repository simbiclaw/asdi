# Owner-invoked cloud Claude audit evidence

**Date:** 2026-11-20  
**Result:** **Ingestion and PR-gate enforcement implemented and builder-tested; no real cloud Claude report has been accepted yet**

## Implemented

[`events/independent_audit.py`](../../events/independent_audit.py) makes the durable owner decision enforceable. When the active independent-verifier decision is `owner_invoked_audit`, `events.cli run-pr-gate` requires an owner-provided cloud Claude audit for the exact PR number and 40-character head before the packet may remain eligible.

`record-independent-audit --report <file>` validates and stores the report at:

```text
state/independent-audits/pr-<number>/<head-sha>.json
```

`show-independent-audit --pr-number <n> --head-sha <sha>` reads it back. The audit schema is `asdi.independent-pr-audit/v1`. Validation requires:

- source `cloud_claude`;
- exact PR number and lowercase 40-character head SHA;
- binding to the active `owner_invoked_audit` decision ID and owner identity;
- pass/fail/blocked verifier and review verdicts;
- non-empty verifier evidence;
- an independent review context;
- schema-valid findings, with evidence for every `act` finding;
- a `gate_status` consistent with the verifier, review and `act` findings.

The normative JSON Schema is [`schemas/independent-audit.schema.json`](../../schemas/independent-audit.schema.json); its valid example is included in the Phase 0 schema suite. To avoid hand-editing structure, the CLI can generate a prefilled template bound to the active decision:

```sh
PYTHONPATH=.:src python3 -m events.cli \
  --root state \
  audit-template \
  --pr-number 2 \
  --head-sha <candidate-sha> \
  --output state/cloud-claude-audit-template.json
```

The template deliberately starts `blocked`. The owner replaces the blocked verdicts with actual cloud Claude results, adds evidence, records any findings, and then submits the completed JSON through `record-independent-audit`.

The PR pipeline preserves the underlying local gate result in `base_policy_decision`, then adds `independent_audit`. A missing, invalid, failed or blocked audit sets `policy_decision: blocked` and `asdi/policy: fail`. Only a valid green audit restores the original eligible/human-required policy. The merge dry run still executes nothing; T0 remains human-required.

## Builder-side execution

Focused tests cover valid durable ingestion, exact-head and decision-binding rejection, missing/failed audit downgrade, green-audit preservation, and the end-to-end PR pipeline transition from independent-audit pending to allowed.

```sh
PYTHONPATH=.:src python3 -m unittest tests.test_events_independent_audit -v
PYTHONPATH=.:src python3 -m unittest tests.test_events_cli.EventsCliTests.test_owner_invoked_audit_blocks_then_allows_pr_gate -v
PYTHONPATH=.:src python3 -m unittest discover -s tests
```

Observed full suite after formal schema and template support: **220 tests, OK, 4 expected AF_UNIX/socket-binding skips**.

## Status boundary

| Claim | Status |
|---|---|
| Decision-aware ingestion and schema validation | Implemented / builder-tested |
| Formal audit schema and operator template | Implemented / builder-tested |
| Exact-head and owner-decision binding | Implemented / builder-tested |
| PR packet enforcement and downgrade | Implemented / builder-tested |
| Real cloud Claude report ingested | **Not yet** |
| Independent PR verification accepted | **Not claimed** |
| Phase 1 acceptance / Phase 4 exit | **Not claimed** |
