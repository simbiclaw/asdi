# Company Operations CLI Evidence

**Date:** 2026-11-15  
**Result:** **Local prototype PASS**

## Operational surface

[`scripts/company_cli.py`](../scripts/company_cli.py) now provides durable company operations:

* `admit` — create a mission, compile its brief, apply guardrails, and optionally decompose it;
* `missions` — list/filter by status, mission kind, and external work-item reference;
* `show` — retrieve a mission snapshot by ID or external reference;
* `events` — read the append-only lifecycle event log;
* `product` — read release/flag/traffic/monitoring/learning evidence;
* `check` — validate durable roots.
* `run` — autonomously execute an admitted local feature through governed local merge, deployment, optional exposure, and experiment verdict.

Mission snapshots expose current status, guardrails, remaining turn/spend/wall-clock budget, tasks, artifacts, classification, merge authorization, reset generation, and parent linkage.

Output is JSON. Values whose keys suggest API keys, tokens, passwords, secrets, or authorization are recursively redacted; values beginning with `bearer ` or `sk-` are also redacted.

## Verification

```sh
PYTHONPATH=src:. python3 -m unittest tests.test_company_cli -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
git diff --check
```

Result: **48 tests, OK, 3 expected AF_UNIX skips.**

Coverage proves:

* admission and brief compilation;
* restart-safe durable state;
* work-reference lookup;
* mission/event retrieval;
* guardrail/budget visibility;
* product/learning evidence retrieval;
* sensitive-value redaction;
* missing-mission fail-closed behavior.
