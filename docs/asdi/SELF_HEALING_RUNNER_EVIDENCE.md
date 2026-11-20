# Self-Healing Runner Evidence

**Date:** 2026-11-15
**Result:** **Local prototype PASS**

## Capability

The durable operations CLI now has a `monitor` command. It observes the current local release and, when a defect is detected, can autonomously create a repair mission and execute the bounded self-healing workflow:

```text
health probe → defect record → triage → repair implementation
→ self-check → three scoped checks → classification
→ T0-governed local merge → redeployment
→ production verification → closure/reopening
→ rollback if verification fails
```

The repair mission is linked to the defective parent, has its own external reference and guardrail budget, and preserves all failed-release evidence.

## CLI

Observation only:

```sh
PYTHONPATH=src:. python3 scripts/company_cli.py --root ROOT monitor \
  --parent-mission-id MISSION_ID --scenario load
```

Authorized autonomous repair:

```sh
PYTHONPATH=src:. python3 scripts/company_cli.py --root ROOT monitor \
  --parent-mission-id MISSION_ID --scenario load --auto-repair \
  --approver OWNER --decision-reference DECISION \
  --agent /path/to/fixture_agent.py --reviewer /path/to/fixture_reviewer.py
```

Auto-repair fails closed without an approver and decision reference. It remains local-only and cannot remotely merge or access production.

## Verification

```sh
PYTHONPATH=src:. python3 -m unittest tests.test_company_cli -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
git diff --check
```

The CLI integration test:

1. deploys a known-good baseline;
2. deploys a controlled defective variant;
3. monitors the load scenario;
4. creates a linked repair mission;
5. executes repair and independent checks;
6. performs T0-governed local merge and deployment;
7. verifies four post-repair requests;
8. closes the defect as `closed_verified`;
9. confirms a subsequent normal observation returns `action=none`.

Full suite: **51 tests, OK, 3 expected AF_UNIX skips.**

## Boundary

This is a local prototype self-healing loop. It does not represent accepted production autonomy, strict container isolation, remote merge authority, or production deployment.
