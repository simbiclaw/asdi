# ASDI PR reviewer (REV K Phase 4 review slice)

**Status:** implemented and unit-tested. Ran live as a dry run against `simbiclaw/asdi`. It has not been run against a live reviewer model, and no status has been posted. **Not a Phase 4 acceptance claim.**
**Owner direction:** 2026-11-18, "create a new PR reviewer per the REV K to settle the hosted PR reviewer conflicts with REV K" (crosswalk X-6 in `specs/001-always-on-loops/crosswalk.md`).

## Why it exists

A hosted, hourly Claude scheduled task was set up on 2026-11-18 to review new PRs. It conflicted with C-1 and Build Guide §3.4, which exclude "cloud agent runners or hosted automation". It also never worked: its sessions had no repository access. This component replaces it with the reviewer REV K specifies:

| REV K requirement | Where it is met |
|---|---|
| C-1, D-8: loops run locally; GitHub is passive; no Actions or webhooks; 60 s poller | `events/poller/github.py` polls outward only; `archon/pr_review.py run` loops every `poller_interval_seconds` |
| Guide §4: event intake behind the `events/` seam | `events/inbox.py` (Inbox) + `events/poller/` |
| Guide §10.1 step 3: review in fresh context posts `asdi/review` | `archon/pr_review.py` `handle()`: one fresh model call per PR head; posts `asdi/review` only |
| Guide §10.2 (N-6): pass output schema; a verdict counts only for the head being judged; no evidence means no `act`; `strike` only for correctness and security | `schemas/pass.schema.json` (now schema 2, as in the Guide); `archon/passes/review.py` `_check()`; head re-checked before posting |
| Guide §10.3: Pass 1 runs one combined `review` pass on a different-family model, or records `independent_family: false` | `config/review.json` `passes[0]`, `builder_families`; `independent_family()` |
| Guide §10.4 (N-21): agent-authored text reaches the reviewer in a delimited block labelled as the implementer's claims; reviewers have no tools with side effects | `build_prompt()` uses nonce-delimited blocks; `archon/models.py` sends no tools |
| Guide §9.4: a new head invalidates earlier verdicts | Inbox supersedes older pending heads; the handler re-reads the head before posting |
| Guide §9.5: reviewer unavailable → blocked, never self-review; poller stalled → alert after 5 min | Every failure path ends `blocked` (state `error`); `health` alerts once after `poller_stale_after_seconds` |
| Design §08: Archon may only post statuses | Posting requires `identities.archon.may_post_status: true` and `may_merge: false`; nothing else is written to GitHub |
| Guide §18: audit events | `review.requested`, `review.completed` in an append-only table |
| DD-15 Pass 1 stand-in: notifications go to a log file | `.asdi-state/notifications.log` |

`asdi/review` is informational. The ruleset requires only `ci` and `asdi/policy` (Guide §9), so this reviewer cannot block or authorize a merge on its own.

## Running it

It runs on the Studio, inside Archon's container (C-4), on the `agent` and `ops` networks (DD-9). GitHub is reached through the egress proxy. The status token is read from the environment variable `ASDI_ARCHON_GITHUB_TOKEN` and is never stored in a file.

```bash
python3 archon/pr_review.py run              # service loop, dry run: stores results, posts nothing
```

```bash
python3 archon/pr_review.py run --post       # also posts asdi/review statuses
```

```bash
python3 archon/pr_review.py review --pr 3    # review one PR now (dry run)
```

```bash
python3 archon/pr_review.py health           # exit 1 and one alert when the poller is stale
```

Results are content-addressed under `.asdi-state/evidence/reviews/<sha256>/`, as `pass.json` (schema 2) and `review.md`. `review.md` is the packet's Review section (Guide §10.5).

## Configuration (`config/review.json`)

| Key | Value | Note |
|---|---|---|
| `passes[0].model` | `qwen-local`, family `qwen`, OpenAI-compatible at `http://host.docker.internal:8000/v1` | DD-6 provisional default: a local model via vllm-mlx |
| `builder_families` | `anthropic`, `openai` | DD-38: either agent CLI may build, so a reviewer from either family is not independent |
| `ignore_prs`, `ignore_prs_created_before` | `[1, 2]`, `2026-11-18T08:38:16Z` | Owner direction: existing PRs stay untouched |
| `max_diff_chars` | 200000 | A larger diff is `blocked`, never partly reviewed |
| `lease_seconds`, `max_attempts` | 900, 3 | Proposed DD-40 and DD-41 (spec 001) |

## Live dry-run evidence (2026-11-18)

Run from a cloud container with a scratch config. No reviewer model was reachable, and nothing was posted.

| Step | Result |
|---|---|
| `poll` | Listed open PRs on `simbiclaw/asdi`; recorded 0 events, because #1 and #2 are ignored |
| `health` | `poller ok` |
| `review --pr 2` | `blocked`: GitHub returns HTTP 406 for the diff (too large). The first run exposed two defects: a tight 3× retry, and 406 handled as a transient error. Both are fixed and covered by tests |
| `review --pr 1` | `blocked`: diff exceeds 200000 characters |

## Tests

`tests/test_pr_reviewer.py`: 34 tests. They use a fake GitHub client and a fake model, and cover:

- dedup and supersede;
- one handling per subject, and lease expiry leading to failed;
- evidence-checked `act` demotion and strike rules;
- fail-closed `blocked` paths: unavailable model, unparseable output, oversized or unrenderable diff, no model;
- a nonce-delimited block that implementer text cannot close;
- the head moving during a review, dry run and identity rights;
- a GitHub outage, poller staleness, and the model adapter's HTTP request shape.

Full suite: the same 3 failures, 8 errors and 2 skips as before this change. All of them are existing Docker and proxy tests that cannot run in the cloud container.

## Not done here (remaining Phase 4 work)

- `ci`, `asdi/verify`, the class check, `asdi/policy`, packet assembly, the merge-bot dry run and the post-merge check (Guide §13.3 Phase 4).
- An Archon container definition in `compose.yaml`, and egress-proxy routing for `api.github.com`.
- A live run against vllm-mlx on the Studio, and spike S-4 (status identity pinning, App vs token, 60 s rate budget).
- Phase order: AGENTS.md puts Phase 4 after Phases 1 and 3, which are on hold under `LOOP_A_ESCALATION.md`. This slice is independent of the launcher and touches none of the held work. It was built on explicit owner direction and is recorded as out-of-order in `STATUS.md`.
