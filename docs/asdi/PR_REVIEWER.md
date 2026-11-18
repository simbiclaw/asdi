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

## Review procedure (what the session does on each wake)

1. List open PRs. Skip #1 and #2, PRs opened before the cutoff, and drafts.
2. For each remaining PR, read its comments. Skip it if a `simbiclaw` comment already carries the marker for the current head.
3. `git fetch origin pull/<n>/head`, then diff the merge base against the head.
4. Review the diff. Write `{"findings": [...]}`.
5. Run:

   ```bash
   python3 archon/pr_review.py verdict --pr <n> --sha <head> --diff-file <diff> --findings-file <json> --out <body.md>
   ```

6. Post `body.md` by updating the existing verdict comment, or adding one. Subscribe to the PR's activity.

## Evidence (2026-11-18)

- **Tests:** `tests/test_pr_reviewer.py` has 44 tests, all passing. They cover:
  - verdict rendering with the same evidence checks;
  - every gate state: pending, success, failure, old head, untrusted author, latest verdict wins, excluded, draft;
  - the workflow: no `${{ secrets.* }}`, default-branch checkout, no PR head reference, `statuses: write` only;
  - plus the inbox, poller and review-pass tests.
- **Full suite:** the same 3 failures and 8 errors as before. All are existing Docker and proxy tests that cannot run in this container.
- **Session wiring:** `git fetch origin pull/2/head` works from the session. The session's GitHub identity is `simbiclaw`.
