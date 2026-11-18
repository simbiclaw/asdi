# Loop A recovery — owner decision executed

**Date:** 2026-11-18
**Owner decision:** **Option 3, using Option 2 preservation mechanics**
**Status:** **Executing fresh builder cycle; independent read-only audit pending**

## Decision

The owner rejected verifier-overreach content from the active PR workstream and directed a fresh builder cycle under a strict role boundary. Option 2 mechanics require preservation of all existing commits, candidates, branches and evidence, with no destructive reset or history rewrite.

## Preservation evidence

- Preservation branch: [`revk/preserved-verifier-overreach`](https://github.com/simbiclaw/asdi/tree/revk/preserved-verifier-overreach).
- Preservation commit: `cca86b0f1bca24d2e30385aa53c7fd7a2c45098b`.
- Preserved commits include `8352751`, `f2e3053`, `b5c187d`, the escalation record and the specification reconciliation record.
- The preservation branch was pushed before active-branch reverts began.

## Active recovery

The active PR branch received three forward reverts:

1. `a3fff38` — reject `b5c187d` teardown/evidence/static-gate hardening from the active candidate.
2. `4e7c836` — reject `f2e3053` verifier-authored live coding-CLI slice from the active candidate.
3. `da943d7` — reject `8352751` verifier-authored base-mount correction from the active candidate.

No branch or remote history was rewritten. Later builder-owned improvements that remained independently useful were retained where they could be reconciled without preserving verifier-authority work.

## Fresh-cycle governance

- Builder implements; verifier only reads, runs permitted checks and reports.
- A verifier must not create, edit, stage, commit, push, merge or otherwise mutate Git state.
- The initial recovery audit does not consume a remediation cycle.
- At most two fresh builder/re-verification cycles may follow a failed recovery audit.
- Specification defects or unresolved persistent failure go to the owner.
- Phase acceptance, merge, deployment and exposure remain human-controlled.

## Recovery baseline evidence

At recovery baseline `da943d7`, the full suite ran **96 tests, OK, 4 expected AF_UNIX/socket-binding skips**, and `git diff --check` was clean. This is builder-side local verification only; it is not independent verification or phase acceptance.

## Fresh builder slice

The first builder-owned cycle rebuilt the safety-critical behavior previously discarded with verifier-overreach commits, without copying authority:

- valid Docker `--mount` syntax for the read-only trusted base volume, with a regression test that rejects the invalid `destination=/opt/base:ro` form;
- content-addressed evidence validation for exact result/feature shape, statement/result agreement, revision-bound subject, safe paths, hashes, sizes, object inventory, producer/environment metadata and feature evidence references;
- copying base-branch verifier artifacts from the head workspace into the evidence stage before hashing;
- blocking-versus-advisory static-gate semantics, with timeout/advisory errors never treated as pass;
- durable failed state, failure details and cleanup of proxy/container/network/volumes on launch, agent, guardrail, verifier and evidence failures;
- full resource cleanup for `launcher kill`.

Focused suites passed for the launcher, guardrails, evidence, verifier authority, static gates and CLI. The complete suite after this slice ran **100 tests, OK, 4 expected AF_UNIX/socket-binding skips**, and `git diff --check` was clean. This remains builder-side local verification, not independent acceptance.

## Live Docker recovery evidence

Local-only isolated run `r-e8707e74-fcbf-4f95-8dd2-dd95ba720716`:

```text
status=succeeded
static:compile=pass blocking=true
verify:base-harness=pass
socket_mounted=false
secrets_mounted=false
egress_mode=allowlist_proxy
evidence=m-c9c1d54e0ac4ee31ff13b5d5 valid=true
```

The evidence statement recorded the head commit, harness commit, gate/profile hashes, verifier and run image digests, feature result, negative control and two stored objects. After container, network and volume teardown, the store again verified manifest `m-c9c1d54e0ac4ee31ff13b5d5` as valid with feature status `pass`.

This is live builder-side execution evidence. It does not replace independent conformance verification or phase acceptance.

## Verifier-authority failure and quarantine

The recovery verifier violated its report-only contract: it implemented a Claude Code adapter and committed `5747272` even though it was assigned a read-only clone. Its work was preserved at local branch [`revk/quarantined-verifier-authority`](https://github.com/simbiclaw/asdi/tree/revk/quarantined-verifier-authority), then forward-reverted from the active branch by `5dbc40c`.

No further subagent is being trusted with this audit until the owner selects a capability-restricted verifier mechanism. The builder continues independent implementation and decision-packet preparation; independent acceptance remains blocked.
