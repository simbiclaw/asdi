# ADR-0004: GitHub-Native Branch Enforcement

**Ticket:** ASDI-003
**Date:** 2026-11-13
**Owner:** Repository owner
**Status:** Deferred — owner declined current GitHub-native enforcement; fail-closed restrictions remain in force

## Context

The designated repository is private and its authenticated owner has admin permission. GitHub rejected reads of repository rulesets, legacy branch protection, and effective branch rules with HTTP 403, reporting that the capability requires GitHub Pro or a public repository. The owner subsequently directed ASDI to no longer pursue repository rulesets or legacy branch protection.

## Decision

Do not configure or retry GitHub repository rulesets or legacy branch protection for `simbiclaw/asdi` under the current account/repository configuration. Do not make the repository public and do not upgrade the account implicitly. Record CODEOWNERS as advisory only.

This does **not** declare ASDI-003 complete, does **not** satisfy hard rule H1, and does **not** authorize a permissive merge or execution fallback.

## Fail-closed consequences

- No build-agent credential may be issued.
- No autonomous run may be launched.
- No merge-bot identity or agent merge path may be enabled.
- No GitHub merge queue may be simulated.
- A future equivalent enforcement boundary must pass the original ASDI-003 identity and permission tests before H1 can be marked satisfied.

## Reopening criteria

This decision may be revisited only with an explicit owner action: upgrade the GitHub capability, change repository visibility deliberately, use a different repository/organization with verified capability, or implement and test an equivalent repository-side enforcement boundary that provides the same guarantees without bypass.
