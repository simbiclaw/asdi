# Specification Feedback Report — Handbook synchronization metadata

**Date:** 2026-11-17

**Decision date:** 2026-11-18

**Status:** **Resolved by owner-approved specification reconciliation**

**Affected claim:** four-document REV K synchronization and full four-spec acceptance

## Requirement

Build Guide V4 REV K §1 states that the Design, Stack, Trust Handbook and Guide are synchronized at REV K. The conformance skill therefore requires a synchronized four-document source set before a full conformance pass.

## Original finding and pre-amendment evidence

The following line references describe the pre-amendment artifacts and are retained for provenance.

- `reference/ASDI-BUILD-GUIDE.md:7` says the revision set is synchronized at REV K.
- `reference/ASDI-BUILD-GUIDE.md:8` names “ASDI Trust Handbook — REV K”.
- `reference/ASDI-TRUST-HANDBOOK.html:7-8` labels itself REV K and says it is aligned to Design and Stack REV K.
- `reference/ASDI-TRUST-HANDBOOK.html:244` explicitly says the Build Guide’s “rev 2” / frozen references are stale and should be corrected.
- `reference/ASDI Design doc-REV K.html:67-69` says the trust handbook is `rev 2`.
- `reference/ASDI Design doc-REV K.html:679` says the Trust Handbook is frozen at rev 2 and describes a merge-queue tier.

## Suspected specification defect

The Design document contains stale REV K metadata that contradicts the authoritative Build Guide and the actual Handbook. This is a cross-document synchronization conflict, not an implementation defect. The verifier correctly reported `SPEC_SYNC_CONFLICT`.

## Owner decision

On 2026-11-18 the owner approved a metadata-only reconciliation with these directives:

1. Update the Design introduction to reference Trust Handbook REV K.
2. Clarify that the old rev-2/frozen statement describes an earlier state, not current authority.
3. Update Handbook §13 to reflect that Build Guide V4 has already been synchronized.
4. Reconcile status and this feedback report with the new authority decision.

## Resolution

- [`reference/ASDI Design doc-REV K.html`](../../reference/ASDI%20Design%20doc-REV%20K.html) now names **ASDI-TRUST-HANDBOOK.html, REV K** in its introduction.
- The Design revision-log entry that recorded rev 2/frozen now explicitly classifies that state as historical, not current authority, and points to the later synchronized Handbook.
- [`reference/ASDI-TRUST-HANDBOOK.html`](../../reference/ASDI-TRUST-HANDBOOK.html) §13 now states that Build Guide V4 is already synchronized with the Handbook at REV K and that §19.1 treats rev-2 differences as historical.
- Build Guide V4 already identified **ASDI Trust Handbook — REV K** and required no normative edit.
- `skills/asdi-build-conformance` no longer treats the metadata mismatch as an open defect; it now verifies execution sources against [`reference/AUTHORITY.md`](../../reference/AUTHORITY.md).
- The reconciled Design SHA-256 is `5b7c65a64a15a8e1784260178669901d3a5797eefdbd3e40d6f746a24c3bbe1e`; the reconciled Handbook SHA-256 is `c368904d42b54cb4df4a3c0a3c2db7b2ee30a4fc774c06383f7d5d155f95b3cd`.

The authoritative four-document set is synchronized at REV K for metadata and shared facts. Build Guide V4 remains the implementation authority.

## Scoped post-amendment verification

Builder-run check against the reconciled sources:

```text
result: pass
checked_sources: 4
design: 5b7c65a64a15a8e1784260178669901d3a5797eefdbd3e40d6f746a24c3bbe1e
stack: 0ad0db6308aab98de941c269dda5065b7158617fb65e4ca9b5d3c2fa1924bef7
build_guide: c528326ee0a5cb6cb86f061abd747896117a308822b399d7bc471fab13057ee6
trust_handbook: c368904d42b54cb4df4a3c0a3c2db7b2ee30a4fc774c06383f7d5d155f95b3cd
```

The check asserted the reconciled Design and Handbook statements and the synchronized Build Guide statement, then matched all four SHA-256 values to `reference/AUTHORITY.md`. This is scoped metadata verification, not independent implementation acceptance.

## Consequences after resolution

- The `SPEC_SYNC_CONFLICT` blocker is closed.
- Four-document metadata synchronization may be assessed against the hashes in [`reference/AUTHORITY.md`](../../reference/AUTHORITY.md).
- This decision does not accept implementation work, release the Loop A process hold, authorize merge or deployment, or change phase-exit criteria.
- Any future edit to an authoritative specification requires explicit owner direction and a fresh authority-hash baseline and conformance verification.

## Alternatives

1. **Confirm the four-document REV K set as authoritative and amend Design’s stale Handbook references.**
   - Advantage: matches the actual supplied Handbook and Build Guide.
   - Disadvantage: requires the owner-approved specification revision process.
   - Assessment: recommended if the supplied Handbook is intended to be current.
2. **Treat rev 2 as authoritative and reject/replace the REV K Handbook.**
   - Advantage: preserves the Design’s frozen-handbook language.
   - Disadvantage: contradicts Build Guide §1 and loses the Handbook’s documented REV K conflict resolutions.
3. **Defer synchronization and permit scoped audits against available sources.**
   - Advantage: unblocks implementation without an immediate revision.
   - Disadvantage: every result remains `BLOCKED`/`CONFORMS_WITH_GAPS`, never full four-spec acceptance.

## Decision required

**Decision recorded:** approve the specification reconciliation described above. The original alternatives remain below for audit provenance.
