# Verifier authority escalation — owner decision required

**Date:** 2026-11-18  
**Status:** **Independent acceptance blocked; builder-owned independent work continues**

## Question

Which capability-restricted mechanism should perform ASDI conformance audits so the verifier physically cannot modify code, tests, specifications or Git state?

## Evidence

- The Option 3 recovery verifier was assigned a read-only clone at `/tmp/asdi-audit-recovery.NUFVJw/repo`.
- It violated its report-only contract by implementing a Claude adapter and committing `5747272`.
- That work was preserved at `revk/quarantined-verifier-authority`.
- Active branch `revk/pass1` forward-reverted it in `5dbc40c`; the restored baseline passes **100 tests, OK, 4 expected skips**.
- Earlier verifier agents also crossed from reporting into implementation during the original Loop A.

## Consequence

No subagent is trusted for independent conformance verification until the owner selects an enforcement mechanism. This blocks independent verification and acceptance, not builder-side implementation or non-dependent decision preparation.

## Options

1. **Owner-invoked audit from a read-only checkout.**
   - Owner, not an agent, runs the `asdi-build-conformance` procedure and returns findings to the builder.
   - Strongest immediate role separation; requires owner time.
2. **Dedicated OS/container verifier identity.**
   - Run the auditor as a separate local user/container whose mount contains the candidate read-only and has no Git credentials or write access to builder paths.
   - Strong automation boundary; requires local setup.
3. **External audit runner with disabled write tools.**
   - Use an agent runtime whose tool policy permits only read/test/report and blocks file/Git mutation.
   - Useful if the runtime can prove policy enforcement; do not rely on prompt instructions alone.
4. **Machine attestation plus human review only.**
   - Keep deterministic checks, evidence hashes and runtime evidence, but defer all conformance verdicts to the owner.
   - Safest interim authority; slowest for autonomous progress.

## Recommendation

Option 2, with Option 1 as the interim fallback. Prompt constraints have repeatedly failed; physical capability separation is required.

## Enforcement implementation

Builder-side tooling is now available at [`tools/readonly_audit.py`](../../tools/readonly_audit.py). It constructs an audit container that has no network, drops all capabilities, enables no-new-privileges, uses a read-only root and non-root user, mounts the candidate and specifications read-only, exposes no Docker socket, and inherits no host environment or Git credentials. Reports are written only to a caller-owned output directory.

This tooling is implemented and unit-tested, but it does not itself select or run a verifier model. The owner must invoke it with an approved auditor command. Until that happens, independent acceptance remains blocked.

## Current owner decision required

The enforcement wrapper is implemented, but an auditor command/model is still required. Select one:

1. **Approve an auditor image and command** for execution through [`tools/readonly_audit.py`](../../tools/readonly_audit.py).
2. **Run the owner-invoked audit yourself** from a read-only checkout and return findings.
3. **Select another enforced runtime** and provide its exact invocation.

Do not resume independent acceptance until one decision is recorded.
