#!/usr/bin/env python3
"""Turn the reviewer's verdict comment into the required ``asdi/review`` status.

Runs inside the GitHub workflow with only the built-in, per-run GITHUB_TOKEN:
no stored secret and no model call. The review itself is done by Claude in the
owner's Claude Code session, which posts one verdict comment per PR carrying

    <!-- asdi-review sha=<head sha> verdict=pass|fail|blocked -->

Rules (fail closed):
- only comments authored by a login in ``trusted_reviewers`` count;
- only a verdict for the PR's *current* head counts (a new head invalidates it);
- no verdict yet -> ``pending``; ``fail`` or ``blocked`` -> ``failure``.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from archon.config import load_reviewer_config  # noqa: E402
from events.poller.github import GitHubClient  # noqa: E402

MARKER = re.compile(r"<!-- asdi-review sha=([0-9a-f]{7,40}) verdict=(pass|fail|blocked)(?: stage=[a-z]+)? -->")
CONTEXT = "asdi/review"


def decide(pull: dict[str, Any], comments: list[dict[str, Any]], *, trusted: list[str],
           ignore_prs: tuple[int, ...], ignore_created_before: str | None,
           include_prs: tuple[int, ...] = ()) -> tuple[str, str]:
    """Return (state, description) for the PR's current head."""
    number, head = int(pull["number"]), pull["head"]["sha"]
    excluded = number in ignore_prs or (ignore_created_before and pull["created_at"] <= ignore_created_before)
    if excluded and number not in include_prs:
        return "success", "Excluded from ASDI review by config/review.json"
    if pull.get("draft"):
        return "pending", "Draft: reviewed once marked ready"
    verdict = None
    for comment in comments:  # oldest first; the latest trusted verdict for this head wins
        if (comment.get("user") or {}).get("login") not in trusted:
            continue
        for sha, value in MARKER.findall(comment.get("body") or ""):
            if head.startswith(sha) or sha.startswith(head):
                verdict = value
    if verdict is None:
        return "pending", f"Awaiting ASDI review of {head[:12]}"
    if verdict == "pass":
        return "success", f"ASDI review passed for {head[:12]}"
    return "failure", f"ASDI review {verdict} for {head[:12]}; see the review comment"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--token-env", default="GITHUB_TOKEN")
    args = parser.parse_args(argv)
    config = load_reviewer_config()
    client = GitHubClient(config.repo, token_env=args.token_env)
    pull = client.pull(args.pr)
    if pull.get("state") != "open":
        print(f"PR #{args.pr} is not open; nothing to do")
        return 0
    comments = client._request("GET", f"/repos/{config.repo}/issues/{args.pr}/comments?per_page=100")
    state, description = decide(pull, comments, trusted=config.trusted_reviewers, ignore_prs=config.ignore_prs,
                                ignore_created_before=config.ignore_created_before, include_prs=config.include_prs)
    client.post_status(pull["head"]["sha"], state=state, context=CONTEXT, description=description, target_url=None)
    print(f"PR #{args.pr} @ {pull['head']['sha'][:12]}: {state} - {description}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
