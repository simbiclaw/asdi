# TRM and Paired Metrics Evidence

**Date:** 2026-11-15  
**Result:** **Local prototype PASS**

## Task Readiness Maturity ledger

[`src/asdi/governance.py`](../src/asdi/governance.py) implements the source-defined task-type ledger:

* every new task type starts at T0;
* T0 → T1 after three first-pass approvals;
* T1 → T2 after five additional approvals and 30 stable days;
* any T1 revert demotes to T0;
* any T2 revert or escaped defect demotes to T0;
* two consecutive T2 resets demote to T1;
* model release demotes eligible task types to T1 until the evaluation set passes;
* judgment paths cap effective supervision at T1.

Every transition has old/new maturity, reason, evidence, mission/work context where applicable, UTC timestamp, and an append-only sequence. There is no manual or agent override that raises maturity without evidence.

## Paired metrics

The `governance` CLI command exposes the design’s speed metrics with mandatory countermeasures:

| Speed metric | Countermeasure |
|---|---|
| PR cycle time | revert rate |
| share of merges by bot | bot-merge revert rate + misroute sampling |
| deploys per day | rollback rate + post-deploy incidents |
| experiments decided per week | expired flags + total flags |
| detection → verified fix | reopen rate |
| first-pass approval rate | escaped defects + one-in-ten deep review |
| resets per run | brief-v2 success rate |
| rule count | recurrence of the same correction |

Every metric records its source. Missing PR and correction-ledger data are explicitly reported as unavailable rather than fabricated. AI code share, lines of code, and agent count are not used.

## Verification

```sh
PYTHONPATH=src python3 -m unittest tests.test_governance -v
PYTHONPATH=src:. python3 -m unittest tests.test_company_cli -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
git diff --check
```

TRM tests cover all promotion, demotion, boundary-date, model-release, judgment-cap, and reset cases. CLI integration proves mission outcomes produce a TRM ledger and all eight paired metrics with source and countermeasure fields.

Full suite: **60 tests, OK, 3 expected AF_UNIX skips.**
