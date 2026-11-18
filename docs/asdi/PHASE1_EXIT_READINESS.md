# REV K Phase 1 exit readiness

**Candidate:** `90aa7c0`
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
| Verifier runs static gates then base-branch verify | static runner and `_verify_head` | live run; verifier-authority tests | Implemented / builder-tested |
| Red verifier overrides successful agent | launcher status logic | `test_successful_agent_cannot_overturn_red_verifier` | Negative control passes |
| Base-branch harness edits do not authorize green | `_fresh_export` plus result binding | `test_base_harness_snapshot_ignores_agent_weakening`; `test_green_verify_exit_requires_bound_caught_feature_result` | Negative control passes |
| No token/model key in run or verifier | explicit environment allowlist and command scan | `test_run_environment_has_no_model_key`; `test_verifier_command_has_no_model_credentials` | Negative control passes |
| Evidence survives teardown and hashes verify | [`launcher/evidence.py`](../../launcher/evidence.py) | evidence tests; post-teardown verification of manifests `m-c9c1d54e0ac4ee31ff13b5d5` and `m-6ab537ce486a96d903aa7039` | Implemented / builder-tested |

## Current full-suite evidence

```sh
PYTHONPATH=.:src python3 -m unittest discover -s tests -v
```

Latest observed result through the full suite at `f2942aa`: **106 tests, OK, no unexpected failures**. Documentation-only commits through `90aa7c0` do not alter that implementation evidence.

## Decision boundary

This document does **not** declare Phase 1 accepted. Independent conformance verification remains blocked by the verifier-authority escalation in [`VERIFIER_AUTHORITY_ESCALATION.md`](VERIFIER_AUTHORITY_ESCALATION.md). Human acceptance and merge remain required.
