# ASDI PR reviewer and merge gate

**Status:** implemented and unit-tested; the gate's wiring was checked live against `simbiclaw/asdi`. No review has yet been run with a live model. The gate activates only once the workflow is on the default branch (see "Turning it on"). **Not a Phase 4 acceptance claim.**

## Owner override (DD-48)

On 2026-11-18 the owner directed: "i want you or github to run this review once a new pr lands (a merge gate), rather than review locally".

REV K says otherwise. C-1 keeps GitHub passive ("No Actions, no webhooks"), and D-8 has events arrive through a local 60-second poller. The override is recorded as DD-48 in `DECISIONS.md`, as a `SPEC_CONFLICT` with C-1 and D-8. The four REV K documents are **not** edited.

What changes and what stays:

| | REV K design | Now (DD-48) |
|---|---|---|
| Trigger | Local poller every 60 s | GitHub Actions on `pull_request_target`: opened, synchronize, reopened, ready_for_review |
| Where it runs | Archon container on the Studio | GitHub-hosted runner |
| Reviewer model | Local `qwen-local` via vllm-mlx (different family) | `claude-opus-5-5` via the Anthropic SDK (same family as Claude Code builds: `independent_family: false`, allowed in Pass 1 by Guide §10.3) |
| Result | `asdi/review` commit status (informational) | Job `asdi/review` passes or fails; make it a **required check**. Plus one sticky PR comment with the findings, and the same text in the job summary |
| Review logic | Unchanged: N-6 schema 2, nonce-delimited untrusted text, `act` needs evidence present in the diff, strike only for correctness and security, fail closed | Same code (`archon/passes/review.py`) |

The local poller path (`archon/pr_review.py run`) is kept as the REV K fallback. Reverting the override means deleting the workflow and running the poller.

## How the gate decides

| Outcome | Job | Comment |
|---|---|---|
| No `act` findings | pass | "ASDI review passed" plus any `consider` or `noted` findings |
| Any `act` finding with evidence verified in the diff | **fail** | "ASDI review failed" plus the findings |
| Reviewer unavailable, refusal (after the server-side fallback), truncated or unparseable output, diff over 200,000 characters, or a diff GitHub won't render | **fail** (blocked) | "ASDI review blocked" plus the reason |
| A newer commit landed while this run was queued | fail; the newer run decides | none |
| PR #1 or #2, or opened before 2026-11-18T08:38:16Z | pass, not reviewed | none (owner direction: existing PRs stay untouched) |
| Draft PR | job skipped | none; it runs on `ready_for_review` |

A new push cancels the run in progress for that PR (`concurrency`), because a new head invalidates the old verdict (Guide §9.4).

## Safety of running on GitHub

- **The PR cannot weaken its own gate.** `pull_request_target` runs the workflow file from the default branch, and the job checks out the PR's **base** commit, so the reviewer code also comes from the base. This is the same rule as Guide §9.3, where `verify/` is read from the base branch. `.github/**`, `archon/**` and `config/review.json` are now judgment-class paths in `config/classes.yaml`.
- **PR code never runs.** The PR head is never checked out. The diff, title, body and commit messages are read through the API and reach the model as nonce-delimited data. The model gets no tools.
- **Least privilege.** `contents: read`, and `pull-requests: write` for the one comment. The checkout keeps no credentials. `ANTHROPIC_API_KEY` is a repository secret, visible only to this step.
- **Fork PRs** are reviewed the same way. Their code is never executed, so exposing the secret to the job does not expose it to the PR.

## Turning it on

1. Add the repository secret `ANTHROPIC_API_KEY` (Settings → Secrets and variables → Actions).
2. Merge `.github/workflows/asdi-review.yml`, together with `archon/`, `events/`, `config/review.json` and `schemas/pass.schema.json`, into the default branch (`main`). `pull_request_target` only runs workflows that are on the default branch, and the job runs the reviewer code from the PR's base.
3. In the ruleset for `main`, require the status check **`asdi/review`**. ADR-0004 records that you had declined GitHub-native enforcement; a merge gate needs it.
4. Open a test PR. Expect one run, a job summary, and one comment that is updated on each push.

## Running it locally (REV K fallback)

```bash
python3 archon/pr_review.py run              # 60 s poller, dry run
```

```bash
python3 archon/pr_review.py run --post       # posts asdi/review commit statuses
```

```bash
python3 archon/pr_review.py gate --pr 3 --sha <head-sha>   # what the workflow runs
```

## Evidence (2026-11-18)

- **Tests:** `tests/test_pr_reviewer.py` has 43 tests. 40 run without the SDK; the 3 Anthropic-adapter tests also pass under `anthropic==2.10.0`. They cover:
  - gate pass, fail and blocked, the single sticky comment, a stale head, and excluded PRs;
  - workflow safety properties: base checkout, `pull_request_target`, no write to contents, cancel-in-progress;
  - the adapter: structured output, `fallbacks: "default"`, no tools, refusal leads to blocked, truncation leads to blocked;
  - plus all of the earlier poller, inbox and review-pass tests.
- **Full suite:** the same 3 failures and 8 errors as before. All are existing Docker and proxy tests that cannot run in this container.
- **Live wiring:**
  - `gate --pr 2` exits 0 as excluded.
  - `gate --pr 1` (exclusion lifted in a scratch config) exits 1, blocked: its diff exceeds 200,000 characters, so no model call was made.
  - No model call has been made yet. One needs the secret.

## Not done here

- The rest of Phase 4: `ci`, `asdi/verify`, the class check, `asdi/policy`, packet assembly and the post-merge check.
- An end-to-end run with a real key on a real PR.
- Phase order: Phases 1 and 3 remain on hold under `LOOP_A_ESCALATION.md`. This work is independent of them.
