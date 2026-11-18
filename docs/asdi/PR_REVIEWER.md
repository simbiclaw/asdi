# ASDI PR reviewer and merge gate

**Status:** implemented and unit-tested. The gate turns on once the workflow is on `main` and `asdi/review` is a required check (see "Turning it on"). **Not a Phase 4 acceptance claim.**

## Design: Claude reviews, GitHub enforces, no stored secret (DD-48)

Owner direction, 2026-11-18:

- "i want you or github to run this review once a new pr lands (a merge gate)"
- "can YOU perform the task as i dont wanna leave a secret ANTHROPIC_API_KEY to within the repo"

| Part | Who | What it holds |
|---|---|---|
| Review | Claude, in the owner's Claude Code session, woken by an hourly scheduled task and by PR activity | The same review rules as every ASDI reviewer: contract, correctness and security; PR text as data; findings checked by `archon/pr_review.py verdict` (schema 2, `act` needs evidence present in the diff, strike only for correctness and security, fail closed) |
| Verdict | One PR comment, posted as `simbiclaw` through the session's GitHub connection | `<!-- asdi-review sha=<head> verdict=pass\|fail\|blocked -->` plus the Review section |
| Gate | `.github/workflows/asdi-review.yml` → `archon/gate_status.py` | Only the built-in, per-run `GITHUB_TOKEN`. **No stored secret, no model call** |

`gate_status.py` sets the commit status `asdi/review` on the PR's current head:

| Situation | `asdi/review` |
|---|---|
| New PR or new commit, not yet reviewed | **pending** (blocks merge) |
| Trusted verdict `pass` for this exact head | success |
| Trusted verdict `fail` or `blocked` for this head | **failure** |
| Verdict exists only for an older head | pending; a new head invalidates it (Guide §9.4) |
| Verdict comment written by anyone not in `trusted_reviewers` | ignored |
| Draft | pending until marked ready |
| PR #1, #2, or opened before 2026-11-18T08:38:16Z | success, not reviewed (owner direction) |

The workflow runs on `pull_request_target` (a new PR or commit resets the status to pending) and on `issue_comment` (a verdict sets it). Both run the workflow file and `gate_status.py` from the default branch. The PR head is never checked out or executed, so a PR cannot change how its own gate is decided. `.github/**`, `archon/**` and `config/review.json` are judgment-class paths.

### Trust boundary

- **Only `simbiclaw` counts.** `trusted_reviewers` in `config/review.json` is `["simbiclaw"]`. Claude's GitHub connection posts as `simbiclaw`, and agents use their own identity, which cannot author comments as `simbiclaw`.
- **The owner can also pass or fail a PR by hand**, by posting a marker comment. That is the owner's authority, not a bypass.
- **Same family.** The reviewer is Claude, the same family as Claude Code builds, so the result records `independent_family: false`. Guide §10.3 allows that in Pass 1, where the human merges everything.

### Latency

New PRs are picked up by the hourly scheduled task, so it takes up to about 60 minutes before `asdi/review` leaves pending. After the first review, the session subscribes to that PR's activity, so later commits wake it sooner.

## REV K standing

This overrides C-1 and D-8 (GitHub passive, local poller). It is recorded as DD-48 in `DECISIONS.md`, as a `SPEC_CONFLICT`, and the REV K documents are not edited. The local design is kept as the fallback: `python3 archon/pr_review.py run` (60 s poller with a local model, posting `asdi/review` itself). Reverting means deleting the workflow and the scheduled task.

## Turning it on

1. Merge this work into `main`. PR #2 (`revk/pass1`) goes first, because this branch is built on it. `pull_request_target` and `issue_comment` only run workflows that are on the default branch.
2. In the ruleset for `main`, require the status check **`asdi/review`**. ADR-0004 records that you had declined GitHub-native enforcement; a merge gate needs it.
3. Nothing else: no secret to add.

## Pipeline on each new PR head (DD-49: verify, then review)

```
new PR head ──► 1. VERIFY  skills/asdi-build-verify, `pr` profile
                  │ VERIFIED                         │ NOT VERIFIED / INCOMPLETE
                  ▼                                  ▼
               2. REVIEW  (contract, correctness,   3. FEEDBACK  no review;
                  security) → verdict comment          • issue "ASDI verify feedback: PR #n …"
                  pass / fail / blocked                  labels asdi-verify-feedback, codex,
                                                         machine-readable task for local Codex
                                                       • gate comment verdict=fail stage=verify
                  └───────────────┬─────────────────────┘
                                  ▼
               GitHub workflow sets the required `asdi/review` status from the latest trusted verdict
```

### 1. Verify

```bash
python3 skills/asdi-build-verify/scripts/pr_check.py --repo . --base <base sha> --head <head sha> --out <scratch>/pr-<n>-<sha12>
```

- **Which rows:** the `pr` profile has 18 rows at phase 1. Two are for PRs only: PR-TEST-1 (no test that passes at the base fails at the head) and PR-PROT-1 (protected paths). The other 16 are the standing rows that can be decided from the repo and git.
- **What fails a PR:** only a problem the PR introduces. Problems already on the base are listed as pre-existing.
- **How the builder's code runs:** in `git archive` scratch copies, with an empty environment and no network.
- **What it fills in:** every row it can decide, with evidence and controls. Each remaining row is marked `needs_confirmation` with its leads. The session opens those leads, settles each row with `confirm.py`, then runs `report.py`.
- **Speed:** about 20 seconds on this repo, mostly the two test runs.

### 2. Review (only after VERIFIED)

```bash
python3 archon/pr_review.py verdict --pr <n> --sha <head> --diff-file <diff> --findings-file <json> --verification-dir <record> --out <body.md>
```

`verdict` refuses to render a review unless the record is VERIFIED for this exact head. The comment states the verification result.

### 3. Feedback (verification not passed)

```bash
python3 skills/asdi-build-verify/scripts/feedback.py <record> --repo-slug simbiclaw/asdi --pr <n> --head-ref <branch> --kind title|issue
```

```bash
python3 skills/asdi-build-verify/scripts/feedback.py <record> --repo-slug simbiclaw/asdi --pr <n> --head-ref <branch> --kind comment --issue <m>
```

- **The issue:** one per PR. A later failing head updates the same issue. It carries a fenced `asdi-verify-feedback` JSON task. `AGENTS.md` tells Codex how to react, and that it must not edit specs, the skill or reports.
- **When the PR is fixed:** once a later head passes verification, the issue is closed with a comment naming the passing head.

## Evidence (2026-11-18)

- **Tests:** `tests/test_pr_reviewer.py` has 44 tests, all passing. They cover:
  - verdict rendering with the same evidence checks;
  - every gate state: pending, success, failure, old head, untrusted author, latest verdict wins, excluded, draft;
  - the workflow: no `${{ secrets.* }}`, default-branch checkout, no PR head reference, `statuses: write` only;
  - plus the inbox, poller and review-pass tests.
- **Full suite:** the same 3 failures and 8 errors as before. All are existing Docker and proxy tests that cannot run in this container.
- **Session wiring:** `git fetch origin pull/2/head` works from the session. The session's GitHub identity is `simbiclaw`.
