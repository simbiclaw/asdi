# REV K Phase 1 exit readiness

**Candidate:** `20dd6f7`
**Status:** **Builder-tested / independently unverified / not accepted**

## Exit-criterion map

| Build Guide V4 Phase 1 criterion | Implementation evidence | Executed evidence | Status |
|---|---|---|---|
| Contract validation with fail-closed `done_check` | [`launcher/contract.py`](../../launcher/contract.py); [`schemas/run-contract.schema.json`](../../schemas/run-contract.schema.json) | `tests.test_revk_phase1` and full suite | Implemented / builder-tested |
| `launcher run`, `kill`, `status` | [`launcher/cli.py`](../../launcher/cli.py), [`launcher/state.py`](../../launcher/state.py) | `tests.test_launcher_cli` | Implemented / builder-tested |
| One container and internal network per run | [`launcher/runner.py`](../../launcher/runner.py) | `tests.test_revk_runner`; live Docker runs | Implemented / builder-tested |
| Guardrails enforced outside the run | structured stream monitor in [`launcher/runner.py`](../../launcher/runner.py) | turn/token/spend/wall-clock tests | Implemented / builder-tested |
| Egress proxy with allowlist and key injection | [`launcher/egress_proxy.py`](../../launcher/egress_proxy.py) | live Claude adapter run `r-5fc95790-5990-4b1b-bca2-842d6fe6e367` | Implemented / builder-tested live |
| Agent adapter with a working CLI and stop hook | [`launcher/agent_adapters.py`](../../launcher/agent_adapters.py), [`launcher/agents/claude_adapter.py`](../../launcher/agents/claude_adapter.py) | live run above; adapter tests | Implemented / builder-tested live |
| Verifier runs static gates then base-branch verify | static runner and `_verify_head`; verifier-only `verify_revision` | live run; verifier-authority tests; verifier-only tests | Implemented / builder-tested |
| Red verifier overrides successful agent | launcher status logic | `test_successful_agent_cannot_overturn_red_verifier` | Negative control passes |
| Base-branch harness edits do not authorize green | `_fresh_export` plus result binding | `test_base_harness_snapshot_ignores_agent_weakening`; `test_green_verify_exit_requires_bound_caught_feature_result` | Negative control passes |
| No token/model key in run or verifier | explicit environment allowlist and command scan | `test_run_environment_has_no_model_key`; `test_verifier_command_has_no_model_credentials` | Negative control passes |
| Evidence survives teardown and hashes verify | [`launcher/evidence.py`](../../launcher/evidence.py) | evidence tests; post-teardown verification of manifests `m-c9c1d54e0ac4ee31ff13b5d5` and `m-6ab537ce486a96d903aa7039` | Implemented / builder-tested |

## Current full-suite evidence

```sh
PYTHONPATH=.:src python3 -m unittest discover -s tests -v
```

Latest implementation-suite result at the verifier-only slice: **177 tests, OK, 4 expected AF_UNIX/socket-binding skips**. This adds builder-tested verifier-only orchestration; it does not change the candidate's independently unverified/accepted status.

## Pending owner decisions

The durable decision log at [`launcher/owner_decisions.py`](../../launcher/owner_decisions.py) can record the two choices required before the next lifecycle phase. It uses a hash-chained JSONL ledger, detects record mutation, rejects credential-like runtime commands and requires an explicit path when selecting an existing pilot.

```sh
PYTHONPATH=src:. python3 -m launcher.owner_decisions --root ./state decisions --help 2>/dev/null || true
```

## Decision boundary

This document does **not** declare Phase 1 accepted. Independent conformance verification remains blocked by the verifier-authority escalation in [`VERIFIER_AUTHORITY_ESCALATION.md`](VERIFIER_AUTHORITY_ESCALATION.md). Human acceptance and merge remain required.
