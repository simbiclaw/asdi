# ASDI-003 Repository Baseline Evidence

**Date:** 2026-11-13  
**Repository:** [`https://github.com/simbiclaw/asdi`](https://github.com/simbiclaw/asdi)  
**Network path:** local HTTP proxy `127.0.0.1:7890`  
**Result:** **FAIL — externally blocked; no permissive fallback configured**

## Owner direction recorded on 2026-11-13

The owner directed ASDI to stop pursuing GitHub repository rulesets and legacy branch protection for this repository. That direction is recorded in [ADR-0004](decisions/ADR-0004-github-protection.md) as a decision to defer GitHub-native enforcement, not as a pass or a weakening of hard rule H1. Agent execution and agent merge remain disabled. CODEOWNERS is advisory until an equivalent fail-closed enforcement boundary is implemented and tested.

## Verified baseline

| Check | Evidence |
|---|---|
| Remote designation | `gh repo view simbiclaw/asdi` returned a private, empty repository with `main` as the default branch and viewer permission `ADMIN`. |
| Local baseline publication | Local root commit `f204409`, containing ASDI-000 through ASDI-002 discovery artifacts, was pushed to the empty `main` branch. The local branch tracks `origin/main`. |
| Repository owner identity | GitHub authenticated the active CLI identity as `simbiclaw`; the token has `repo` and `workflow` scopes. This is the human/owner administrative identity, not a scoped agent, Archon, merge-bot, CI-signing, or production-deployer identity. |
| Merge-method settings | API reported auto-merge disabled; merge commit, squash merge, and rebase merge enabled; branch deletion after merge disabled. Auto-merge was not enabled. |
| CODEOWNERS | [`/CODEOWNERS`](../../CODEOWNERS) was added. The root rule requires `@simbiclaw` for every path; explicit rules cover decisions and Gate 0 evidence plus future vendor, third-party, build, distribution, and generated paths. CODEOWNERS cannot enforce branch protection while branch protection is unavailable. |

## GitHub capability probes

All probes used `https://api.github.com` through proxy `127.0.0.1:7890`.

| Probe | Endpoint | Exact result |
|---|---|---|
| Repository rulesets | `GET /repos/simbiclaw/asdi/rulesets` | HTTP 403. Message: “Upgrade to GitHub Pro or make this repository public to enable this feature.” |
| Legacy branch protection | `GET /repos/simbiclaw/asdi/branches/main/protection` | HTTP 403 with the same GitHub Pro/public requirement. |
| Effective branch rules | `GET /repos/simbiclaw/asdi/rules/branches/main` | HTTP 403 with the same GitHub Pro/public requirement. |

Because creation would use the same paid capability, no branch-protection or ruleset write was attempted. Enabling branch protection or merge queue on this free private repository is not possible from the observed API behavior.

## Required separate identities and credentials

The five minimum identities remain unresolved. The existing `simbiclaw` owner token must not be reused for any agent or service role.

| Identity | Minimum capability | Current state |
|---|---|---|
| Build agent | Branch push and PR open only | Missing; owner token has broad `repo` and `workflow` access and must not be used. |
| Archon | Status posting only | Missing; owner token cannot be used. |
| Merge bot | Merge-queue enqueue only | Missing; owner token can merge directly and must not be used. |
| CI signing identity | Artifact signing/verification only | Missing. |
| Production pull deployer | Pull/verify release images only | Missing. |

Separate accounts or GitHub Apps, fine-grained credentials, and app installations were not created. This requires explicit owner authorization and must not be silently substituted with the existing owner token.

## Agent merge safety

Agent merge remains disabled by fail-closed absence:

- No agent credential exists.
- No merge-bot credential exists.
- No merge-queue rule can be enabled on the current free private repository.
- No agent merge feature is implemented or enabled.

This is **not** accepted as H1 enforcement. H1 is unverified and remains blocked.

## Acceptance result

| ASDI-003 criterion | Result | Reason |
|---|---|---|
| Protected branch/ruleset baseline | **Fail** | GitHub reports that branch protection and rulesets require GitHub Pro or a public repository. |
| Generated/vendor path protection | **Partial** | CODEOWNERS declares human ownership, but no enforceable branch rule can be created under the current plan. |
| Separate minimum identities | **Fail** | No scoped identity or credential has been created/installed; existing owner token is unsuitable. |
| Agent cannot push protected branches/merge | **Unverified** | There is no protected branch and no separate agent identity to test. |
| Archon status-only / merge-bot enqueue-only | **Unverified** | Identities and required merge-queue behavior cannot be established. |
| Judgment paths require human CODEOWNER approval | **Unverified as enforced** | CODEOWNERS exists, but branch protection is unavailable to make it mandatory. |
| Agent merge disabled | **Pass as disabled baseline** | No agent merge path exists or is enabled; this does not satisfy full H1 acceptance. |

## Owner decision required

ASDI-003 cannot proceed until the owner selects and authorizes one of these paths:

1. Upgrade the GitHub account/repository capability (for example, GitHub Pro) and retain `simbiclaw/asdi` as private.
2. Make the repository public after explicitly accepting the exposure implications.
3. Provide another existing repository/organization with verified paid capability and owner authorization to configure protection.

After that, explicitly authorize creation/installation of the five separate identities or apps and provide scope/permission approval. Do not reuse the owner token.

Until then, do not enable autonomous runs, agent merge, production connectivity, or external side effects.
