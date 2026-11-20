# PR #2 review response

**Source:** [PR #2 issue comment](https://github.com/simbiclaw/asdi/pull/2#issuecomment-6997732747), posted by `simbiclaw` on 2026-11-19T02:22:41Z for candidate `00f5f7e`.

## Act

**F-1 — partial setup leaked resources and left state running.** Fixed. Per-run exports, network, volumes, population and ownership now run inside the launcher's failure-handling boundary in `launcher/runner.py`. If setup fails, the launcher stops the proxy, tears down all named resources, records a terminal `failed` state, and re-raises. Regression evidence: `tests.test_revk_runner.REVKRunnerTests.test_setup_failure_cleans_resources_and_records_terminal_failure`.

## Consider

**F-2 — plain HTTP egress re-resolved the destination after authorization.** Fixed. `EgressHandler` now uses the addresses returned by `EgressAuthority.decide()` for direct HTTP connections, matching the CONNECT path, while retaining the original Host header. Unresolvable destinations are blocked before any second lookup.

**F-3 — Claude adapter forwarded credential-like environment names.** Fixed. The builder-owned adapter rejects any environment variable whose name contains `KEY`, `TOKEN`, `SECRET`, `PASSWORD` or `CREDENTIAL` before launching the CLI, without printing values. Regression evidence: `tests.test_agent_adapters.AgentAdapterTests.test_claude_adapter_refuses_credential_like_environment`.

## Noted

**F-4 — evidence store accepts `control: not_applicable`.** Not changed. The schema permits that control value for non-feature evidence records; the launcher still requires `control: caught` for every green feature, so the review's stated bypass does not exist. Tightening the global evidence enum would reject valid non-feature records without changing the actual gate.

## Verification

`PYTHONPATH=.:src python3 -m unittest discover -s tests -v`: **199 tests, OK, 4 expected sandbox skips**.

This is a builder-side response to a review of an older candidate. It does not accept a phase, re-run the independent auditor, post to GitHub, merge, deploy, or expose anything. A fresh review is required after the fixes are committed.

## Second review — `12eece8`

**Source:** [PR #2 review comment](https://github.com/simbiclaw/asdi/pull/2#issuecomment-7034234161) and [builder task](https://github.com/simbiclaw/asdi/issues/2#issuecomment-7034234162) for candidate `12eece804e83`.

**F-1 (Act, correctness):** `verify_revision` now performs exports, volume creation, population and chown inside the same failure boundary as `run()`. A setup failure tears down the verifier volumes and records a terminal failure instead of leaving `verifying` state behind. Regression: `tests.test_revk_runner.REVKRunnerTests.test_verifier_setup_failure_cleans_volumes_and_records_failure`.

**F-2 (Consider, correctness):** `run_review` now forces `blocked` when the reviewer times out or exits nonzero, even if it wrote a `pass` output file. Regression: `tests.test_events_review.ReviewCommandTests`.

**F-3 (Consider, contract):** `evaluate_merge_packet` derives `up_to_date` from packet freshness evidence and fires `R9-branch-not-up-to-date` when the evidence says the branch is stale. When no freshness evidence exists, the dry run records that freshness was not evaluated instead of asserting `up_to_date=True`. Regression: `tests.test_events_merge_gate.MergeGateTests`.

**F-4 (Consider, correctness):** `release_readiness` now blocks when `current_state` is missing, instead of skipping the exact-current-main check. Regression: `tests.test_events_release_gate.ReleaseReadinessTests.test_missing_current_main_state_is_blocked`.

**F-5 (Noted, correctness):** the dry run now receives only the names of statuses whose value is `pass`, not all status keys.

DD-10 was also tightened: `config/defaults.yaml` is the sole source for repair attempts, poller interval/stale windows, review/verifier/reconciler/remediation timeouts and guardrail default values. `events/config.py` validates the typed defaults; CLI, pipeline, remediation, verifier and reconciler callers consume them. The launcher accepts the specified `launcher run <contract.yaml>` form and YAML contracts.

Verification: `PYTHONPATH=.:src python3 -m unittest discover -s tests` — **211 tests OK**. `git diff --check` clean. This remains builder-side evidence; no phase acceptance, merge, deploy or exposure is claimed.
