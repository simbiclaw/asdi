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
