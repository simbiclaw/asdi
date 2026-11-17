# REV K Phase 0 evidence

**Date:** 2026-11-16
**Result:** **Phase 0 scaffold PASS**

## Commands

```sh
PYTHONPATH=.:src python3 tools/validate_examples.py
PYTHONPATH=src:. python3 -m unittest tests.test_phase0_scaffold -v
PYTHONPATH=.:src python3 -m unittest discover -s tests -v
git diff --check
./tests/zone_probe.sh
```

## Evidence

### Schemas

The minimal REV K validator validated all 11 canonical examples:

```text
validated 11 REV K examples
```

A mutated run contract missing `done_check` failed closed.

### Topology

`compose.yaml` defines `prod`, `agent`, `staging`, `ops`, and egress. The first four are internal; only egress has external reach. `agent-canary` joins only `asdi-agent`; `prod-canary` joins only `asdi-prod`; their network sets are disjoint.

The live Docker probe started both canaries and verified:

```text
zone isolation verified: agent cannot resolve or connect to prod
```

### Merge authority

`merge/dry_run.py` proves REV K §14.1 row 1:

* actor `agents` with both required statuses: refused;
* actor `merge-bot` at T0 with both statuses: human required;
* actor `merge-bot` at T1 with missing status/old branch: blocked.

## Phase 0 result

All Phase 0 deliverables are present and the three stated exit checks pass. The next phase is Phase 1: REV K launcher, verifier, guardrails, evidence store, and one working agent adapter.
