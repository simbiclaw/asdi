# Reset and Work-Reference Evidence

**Date:** 2026-11-15  
**Result:** **Local prototype PASS**

## Capability

The integrated lifecycle now supports:

* durable `external_reference` on every mission;
* ordered retrieval of all missions for a work item;
* generation tracking (`reset_generation`);
* a fresh brief-v2 reset after two failed repair attempts;
* fail-closed reset rejection for active missions.

A reset creates a new mission with a fresh workspace, links it to the failed parent, preserves the work-item reference and guardrail policy, and clears repair attempts. It does not delete evidence from the failed mission.

## Verification

```sh
PYTHONPATH=src python3 -m unittest tests.test_lifecycle -v
PYTHONPATH=src:. python3 scripts/run_company_scenarios.py
git diff --check
```

Regression evidence:

| Test | Result |
|---|---|
| External reference is queryable across resets | Pass |
| Two failed repairs transition to `reset_required` | Pass |
| Reset creates generation 2 with fresh repair budget | Pass |
| Active missions cannot be reset | Pass |
| Full product/self-healing scenarios still pass | Pass |
| Ordered mission index is persisted by external reference | Pass |

Full suite: **46 tests, OK, 3 expected AF_UNIX skips.**

Latest integrated scenario evidence root:  
`/private/var/folders/yf/nn0v06c92fv8yc2z36cqqjw80000gn/T/asdi-company-20261115-073004-04bprp0y`
