# ASDI REV K · Pass 1

The authoritative specification set is the four REV K documents recorded in [`reference/AUTHORITY.md`](reference/AUTHORITY.md). Build Guide V4 REV K remains the implementation authority for exact layout, schemas, interfaces, commands, phase order and exit tests. Build Pass 1 in this order:

```text
0 → 1 → 3 → 4 → 7 → first light → 2 → 5 → 9 → full loop → 6 → 8 → 10 → deploy gate
```

Do not begin Pass 2 before the full-loop checkpoint. Keep every REV K provisional default behind its named adapter or config seam. The agent's claim of success never counts; only ASDI-run verification does.

`reference/archive/` is historical material only. Do not use it to override REV K.

## Verification feedback issues

A PR that fails the `asdi-build-verify` gate is not reviewed. It gets a GitHub issue titled `ASDI verify feedback: PR #<n> ...`, labelled `asdi-verify-feedback` and `codex`, and the gate status `asdi/review` stays failing. To react:

1. Read the fenced block tagged `asdi-verify-feedback` in the issue. It is the task: `must_fix` rows with what the verifier observed and where.
2. Fix those rows on the PR's branch (`head_ref`) and push a new commit. Verification and review re-run on the new head; the same issue is updated, not duplicated.
3. Never edit `reference/`, `reference/AUTHORITY.md`, `skills/asdi-build-verify/` or `verification/` to make a row pass. A row you believe is wrong goes back to the owner as a comment on the issue.
4. `cannot_check` rows need a capability (Docker, launcher, sandbox), not a code change.
