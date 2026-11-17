# S-4 · GitHub identity, required statuses, and merge refusal

**Phase:** 0
**Question:** Can ASDI require `ci` and `asdi/policy` from a distinct identity while refusing agent and status identities on merge?
**Status:** local policy modeled; live GitHub ruleset probe pending.

## Local evidence

`merge/dry_run.py` models REV K §9.4 and §14.1:

```sh
python3 merge/dry_run.py --actor agents --status ci --status asdi/policy
python3 merge/dry_run.py --actor merge-bot --status ci --status asdi/policy
python3 merge/dry_run.py --actor merge-bot --status ci
```

Expected:

1. `agents` is refused.
2. `merge-bot` is `human_required` at T0, not autonomous.
3. Missing status is blocked.

## Still to verify

- Required status identity can be pinned by GitHub ruleset.
- Whether that identity must be a GitHub App.
- Agent token cannot satisfy merge authorization.
- 60-second poll rate fits the API budget.
