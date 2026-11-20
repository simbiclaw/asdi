# Autonomous Mission Runner Evidence

**Date:** 2026-11-15
**Result:** **Local prototype PASS**

## Capability

The durable operations CLI now has a `run` command. An admitted work order can be autonomously executed through the local lifecycle:

```text
decomposition → agent execution → self-verification
→ three scoped independent checks → classification
→ explicit T0-governed local merge → local deployment
→ default-off verification → controlled exposure
→ experiment verdict → durable task completion
```

The runner supports both the deterministic fixture adapter and the explicit shell-free live command adapter. It does not remotely merge, deploy to production, authorize irreversible actions, or expose production secrets.

## Governed operation

The command requires explicit T0 authorization:

```sh
--approver OWNER_NAME
--decision-reference OWNER_DECISION_REFERENCE
```

The resulting mission records:

* `authority=T0_human`;
* `autonomous_merge=false`;
* `remote_merge=false`;
* local commit ID;
* approver and decision reference.

Controlled exposure also records the same owner decision reference. The feature flag remains off until exposure is explicitly requested.
Deployment can also complete without exposure, leaving the experiment task open.

## Verification

```sh
PYTHONPATH=src:. python3 -m unittest tests.test_company_cli tests.test_lifecycle -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
git diff --check
```

The end-to-end CLI regressions prove:

* an admitted mission reaches `experiment_completed`;
* all six lifecycle tasks complete;
* implementation artifact passes self-check and three scoped checks;
* classification is `T0_human`;
* local merge is governed and non-remote;
* deployment exists;
* pre-exposure product traffic is `variant=off`;
* controlled exposure is enabled only with the decision reference;
* four traffic outcomes produce `keep_for_human_review`;
* mission budget records 5 turns.
* `--no-exposure` completes deployment while keeping the flag off and leaving the experiment task open.

Full suite: **50 tests, OK, 3 expected AF_UNIX skips.**
