# ASDI reference authority

**Owner direction:** The newest four REV K specifications are authoritative. The REV H/G backlog is archived and historical only. On 2026-11-18 the owner approved reconciliation of the stale Handbook metadata: the current authority is the four-document REV K set, while rev-2/frozen language is historical.

## Authoritative specification set

| Role | Path | SHA-256 |
|---|---|---|
| Product intent, hard rules, human authority, lifecycle and TRM | [`ASDI Design doc-REV K.html`](ASDI%20Design%20doc-REV%20K.html) | `5b7c65a64a15a8e1784260178669901d3a5797eefdbd3e40d6f746a24c3bbe1e` |
| Components, deployment roles and runtime topology | [`ASDI Stack doc.html`](ASDI%20Stack%20doc.html) | `0ad0db6308aab98de941c269dda5065b7158617fb65e4ca9b5d3c2fa1924bef7` |
| Normative implementation layout, schemas, interfaces, commands, phase order and exit tests | [`ASDI-BUILD-GUIDE.md`](ASDI-BUILD-GUIDE.md) | `c528326ee0a5cb6cb86f061abd747896117a308822b399d7bc471fab13057ee6` |
| Trust model, evidence validity and control rationale | [`ASDI-TRUST-HANDBOOK.html`](ASDI-TRUST-HANDBOOK.html) | `c368904d42b54cb4df4a3c0a3c2db7b2ee30a4fc774c06383f7d5d155f95b3cd` |

Implementation conflicts take the ownership rule from Build Guide V4 REV K. If ownership rules do not resolve a cross-document conflict, record `SPEC_CONFLICT`; do not silently reinterpret the documents.

**2026-11-18 metadata reconciliation:** the Design introduction names the Trust Handbook REV K. Its rev-2/frozen revision-log statement is explicitly historical. Handbook §13 records that Build Guide V4 has already been synchronized at REV K. The hashes above are the executable baseline for audits.

## Supplemental reference

[`ASDI-Product-Verification-Skill-Build-Guide-REV-K.md`](ASDI-Product-Verification-Skill-Build-Guide-REV-K.md) and its HTML rendering describe how to build a product-specific verification harness. They are **not** part of the four-document authority set and must not replace Build Guide V4 schemas, phase commands or exit tests. Markdown SHA-256: `6ca73d0758ad45d3194567b8b355431db81039301806c52c4d4c0338cef945ed`.

## Archived historical input

[`archive/ASDI_Codex_Implementation_Backlog_REV_H_G.md`](archive/ASDI_Codex_Implementation_Backlog_REV_H_G.md) records the earlier REV H/G implementation baseline. It is retained for provenance only and is superseded by the four REV K specifications above. SHA-256: `839c1e41077db7db2d59197b46edeae7d37058b7cd9c86cea72e8e5614043664`.
