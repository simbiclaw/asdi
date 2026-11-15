# Development Flow Evidence — Noncompliant Network Profile

**Date:** 2026-11-15  
**Decision:** [`ADR-0007`](decisions/ADR-0007-development-open-network-profile.md)  
**Result:** `development_flow_pass` — **not ASDI-012 acceptance**

## Command

```sh
PYTHONPATH=src:. python3 scripts/dev_e2e_flow.py --url https://example.com/
```

This used the explicit `development_open`, bridge-network profile. It requires `owner_approved`, `development_only`, and launcher `allow_noncompliant_test=true`.

## Flow result

Evidence root:  
`/private/var/folders/yf/nn0v06c92fv8yc2z36cqqjw80000gn/T/asdi-dev-flow-20261115-043127-fuqvh_ue`

| Stage | Run | Result |
|---|---|---|
| Contract admission | `asdi_run_62acedf2-03fb-43e4-ad02-c28f2f98e5f9` | `contract_validated`; owner override and development-only scope recorded |
| Runtime execution | same run | container `5db82f869d39...b25f00e`; bridge network; HTTP `https://example.com/` returned 200 |
| Structured output/usage | same run | runtime emitted `type=result`, usage `{usd_cost: 0.0, turns: 1}`; event sequences 1–11 were contiguous |
| Launcher done-check | same run | `/workspace/verify_flow.py` exited 0; final status `succeeded` |
| Cancellation | `asdi_run_f525cf9c-cd8b-414c-9e33-1989ed79ac21` | container existed before cancel; launcher ended `cancelled`; cleanup event persisted |
| Cleanup | cancellation run | Docker inspect found no container after cancel; leak check found no `asdi-*` containers |
| Review handoff | success run | `review-packet.json` marked `pending_human_review`, `T0_human`, `autonomous_merge_authorized=false` |

The success run's durable event sequence was:

```text
run_created
contract_validated
runtime_starting
runtime_started
usage_observed
runtime_output
process_exit
done_check_started
done_check_exit
run_succeeded
container_cleaned
```

## Tests

```sh
python3 -m compileall -q src tests scripts
PYTHONPATH=src python3 -m unittest discover -s tests -v
git diff --check
```

Result: **36 tests, OK, 3 expected AF_UNIX skips.**

## Boundary

This evidence proves development-flow integration only. It does **not** prove:

- container egress allowlist enforcement;
- private/production route denial;
- per-run spend, turn, or wall-clock enforcement;
- board integration;
- independent review;
- governed merge;
- deployment or production verification.

The run explicitly reported `isolation_compliant=false` and `network_profile=development_open_noncompliant`. ASDI-012 remains FAIL.
