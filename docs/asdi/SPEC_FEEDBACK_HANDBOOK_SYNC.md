# Specification Feedback Report — Handbook synchronization metadata

**Date:** 2026-11-17  
**Status:** **Awaiting explicit owner direction**  
**Affected claim:** four-document REV K synchronization and full four-spec acceptance

## Requirement

Build Guide V4 REV K §1 states that the Design, Stack, Trust Handbook and Guide are synchronized at REV K. The conformance skill therefore requires a synchronized four-document source set before a full conformance pass.

## Actual evidence

- `reference/ASDI-BUILD-GUIDE.md:7` says the revision set is synchronized at REV K.
- `reference/ASDI-BUILD-GUIDE.md:8` names “ASDI Trust Handbook — REV K”.
- `reference/ASDI-TRUST-HANDBOOK.html:7-8` labels itself REV K and says it is aligned to Design and Stack REV K.
- `reference/ASDI-TRUST-HANDBOOK.html:244` explicitly says the Build Guide’s “rev 2” / frozen references are stale and should be corrected.
- `reference/ASDI Design doc-REV K.html:67-69` says the trust handbook is `rev 2`.
- `reference/ASDI Design doc-REV K.html:679` says the Trust Handbook is frozen at rev 2 and describes a merge-queue tier.

## Suspected specification defect

The Design document contains stale REV K metadata that contradicts the authoritative Build Guide and the actual Handbook. This is a cross-document synchronization conflict, not an implementation defect. The verifier correctly reported `SPEC_SYNC_CONFLICT`.

## Consequences

- A full four-spec `PASS` cannot be claimed.
- Affected dependent work: acceptance of the current implementation slice and any conformance claim requiring synchronized four-document sources.
- Unrelated implementation repair and phase execution may continue, provided they do not claim four-document synchronization or modify any specification.

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

Choose one disposition: confirm the original requirement, clarify the intended interpretation, approve a specification amendment, select an alternative approach, or defer/abandon the affected synchronization requirement. Do not permit specification edits or a synchronized acceptance claim until explicit direction is recorded.
