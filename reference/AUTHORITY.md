# ASDI reference authority

**Owner direction:** The newest four REV K specifications are authoritative. The REV H/G backlog is archived and historical only.

## Authoritative specification set

| Role | Path | SHA-256 |
|---|---|---|
| Product intent, hard rules, human authority, lifecycle and TRM | [`ASDI Design doc-REV K.html`](ASDI%20Design%20doc-REV%20K.html) | `f1a032fd7daaa527705ed3a8452a1f09908a85c4554f3deb39469a0c44eced23` |
| Components, deployment roles and runtime topology | [`ASDI Stack doc.html`](ASDI%20Stack%20doc.html) | `0ad0db6308aab98de941c269dda5065b7158617fb65e4ca9b5d3c2fa1924bef7` |
| Normative implementation layout, schemas, interfaces, commands, phase order and exit tests | [`ASDI-BUILD-GUIDE.md`](ASDI-BUILD-GUIDE.md) | `c528326ee0a5cb6cb86f061abd747896117a308822b399d7bc471fab13057ee6` |
| Trust model, evidence validity and control rationale | [`ASDI-TRUST-HANDBOOK.html`](ASDI-TRUST-HANDBOOK.html) | `30616c0268d812be0c06cbc4a5136aad169bdcb532dcaa7cb7987f211e54fe85` |

Implementation conflicts take the ownership rule from Build Guide V4 REV K. If ownership rules do not resolve a cross-document conflict, record `SPEC_CONFLICT`; do not silently reinterpret the documents.

## Supplemental reference

[`ASDI-Product-Verification-Skill-Build-Guide-REV-K.md`](ASDI-Product-Verification-Skill-Build-Guide-REV-K.md) and its HTML rendering describe how to build a product-specific verification harness. They are **not** part of the four-document authority set and must not replace Build Guide V4 schemas, phase commands or exit tests. Markdown SHA-256: `6ca73d0758ad45d3194567b8b355431db81039301806c52c4d4c0338cef945ed`.

## Archived historical input

[`archive/ASDI_Codex_Implementation_Backlog_REV_H_G.md`](archive/ASDI_Codex_Implementation_Backlog_REV_H_G.md) records the earlier REV H/G implementation baseline. It is retained for provenance only and is superseded by the four REV K specifications above. SHA-256: `839c1e41077db7db2d59197b46edeae7d37058b7cd9c86cea72e8e5614043664`.
