#!/usr/bin/env python3
"""ASDI PR reviewer: local poller + Pass 1 review pass + ``asdi/review`` status.

Build Guide V4 REV K section 10.1 step 3 and Phase 4 ("poller behind
``events/``; on a new PR head: ... one review pass ...; poller health alert").
Runs on the Studio inside Archon's container (C-4). It replaces any hosted
reviewer: no GitHub Actions, no webhooks, no cloud runner (C-1, D-8).

Authority: Archon's identity may only post statuses. This module never merges,
pushes, edits a PR or comments. ``asdi/review`` is informational; the ruleset
requires ``ci`` and ``asdi/policy`` (section 9).

Commands:
  poll       one reconciliation pass over open PRs
  work       handle pending events until none is claimable
  run        poll + work every poller_interval_seconds (the service loop)
  health     report poller staleness; alert once when stale
  review     review one PR now (records and handles a single event)

Statuses are posted only with --post. Without it the run is a dry run: the
pass result and the Review section are still stored and printed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from archon.config import ReviewerConfig, load_reviewer_config  # noqa: E402
from archon.models import OpenAICompatibleModel, ReviewModel  # noqa: E402
from archon.passes.review import (  # noqa: E402
    PullRequestInput,
    blocked,
    independent_family,
    render_review_section,
    run_review,
)
from events.inbox import Event, Inbox  # noqa: E402
from events.poller.github import PR_HEAD, DiffUnavailable, GitHubClient, GitHubError, poll_once  # noqa: E402
from tools.validate_schema import ValidationError, _validate  # noqa: E402

STATE = {"pass": "success", "fail": "failure", "blocked": "error"}
SCHEMA = json.loads((ROOT / "schemas" / "pass.schema.json").read_text())


def build_model(spec: dict[str, Any] | None) -> ReviewModel | None:
    if not spec:
        return None
    if spec.get("kind") != "openai-compatible":
        raise ValueError(f"unsupported reviewer model kind: {spec.get('kind')!r}")
    return OpenAICompatibleModel(name=spec["name"], family=spec["family"], base_url=spec["base_url"])


def notify(config: ReviewerConfig, message: str, now: float) -> None:
    """DD-15 Pass 1 stand-in: notifications append to a log file."""
    config.notifications_log.parent.mkdir(parents=True, exist_ok=True)
    with config.notifications_log.open("a") as handle:
        handle.write(json.dumps({"at": now, "message": message}) + "\n")


def store_result(config: ReviewerConfig, result: dict[str, Any], section: str) -> str:
    """Content-addressed, write-once store for pass output (N-2 layout)."""
    body = json.dumps(result, sort_keys=True, indent=2).encode()
    digest = hashlib.sha256(body).hexdigest()
    directory = config.evidence_root / "reviews" / digest
    directory.mkdir(parents=True, exist_ok=True)
    for name, data in (("pass.json", body), ("review.md", section.encode())):
        target = directory / name
        if not target.exists():
            target.write_bytes(data)
    return f"rv-{digest[:24]}"


def describe(result: dict[str, Any]) -> str:
    counts = {b: sum(1 for f in result["findings"] if f["bucket"] == b) for b in ("act", "consider")}
    if result["status"] == "blocked":
        text = f"review blocked: {result.get('blocked_reason', 'unknown')}"
    else:
        text = f"review {result['status']}: {counts['act']} act, {counts['consider']} consider"
    return f"{text}; independent family {result['independent_family']}"[:140]


def handle(
    event: Event,
    *,
    config: ReviewerConfig,
    client: GitHubClient,
    inbox: Inbox,
    model: ReviewModel | None,
    post: bool,
    out: Callable[[str], None],
) -> str:
    """Review one PR head. Returns the outcome recorded on the event."""
    number, sha = event.payload["number"], event.payload["head_sha"]
    pull = client.pull(number)
    if pull.get("state") != "open":
        inbox.complete(event.id, "subject closed")
        return "subject closed"
    if pull["head"]["sha"] != sha:
        inbox.supersede(event.id, "head moved before review")
        return "superseded"

    pr = PullRequestInput(
        repo=config.repo,
        number=number,
        head_sha=sha,
        title=pull.get("title") or "",
        body=pull.get("body") or "",
        commit_messages=[c["commit"]["message"] for c in client.pull_commits(number)],
        diff="",
    )
    try:
        pr.diff = client.pull_diff(number)
        result = run_review(pr, model, builder_families=config.builder_families, max_diff_chars=config.max_diff_chars)
    except DiffUnavailable as error:
        # Fail closed: a diff nobody can read is blocked, never passed (Guide 9.5).
        family = independent_family(model.family if model else None, config.builder_families)
        result = blocked(pr, model.name if model else "none", family, str(error))
    _validate(result, SCHEMA, SCHEMA, "pass")
    section = render_review_section(result)
    manifest = store_result(config, result, section)
    out(f"PR #{number} @ {sha[:12]}: {result['status']} ({manifest})\n{section}")

    # A new head invalidates the verdict: re-check before posting (Guide 9.4, 10.2).
    if client.pull(number)["head"]["sha"] != sha:
        inbox.supersede(event.id, "head moved during review")
        return "superseded"
    if post:
        if not config.may_post_status:
            raise PermissionError(f"identity {config.status_identity!r} may not post statuses")
        target = f"{config.evidence_base_url.rstrip('/')}/reviews/{manifest}" if config.evidence_base_url else None
        client.post_status(sha, state=STATE[result["status"]], context=config.status_context,
                           description=describe(result), target_url=target)
    inbox.audit("review.completed", repo=config.repo, pr=number, sha=sha, status=result["status"],
                manifest=manifest, posted=post)
    outcome = f"{result['status']} {manifest}" + ("" if post else " (dry run)")
    inbox.complete(event.id, outcome)
    return outcome


def work(config: ReviewerConfig, client: GitHubClient, inbox: Inbox, model: ReviewModel | None,
         *, post: bool, out: Callable[[str], None], now: Callable[[], float]) -> int:
    handled = 0
    tried: set[int] = set()  # a failed event waits for the next cycle, never a tight retry loop
    while (event := inbox.claim(lease_seconds=config.lease_seconds, max_attempts=config.max_attempts,
                                exclude=tried)) is not None:
        tried.add(event.id)
        if event.kind != PR_HEAD:
            inbox.complete(event.id, "not handled by the reviewer")
            continue
        try:
            handle(event, config=config, client=client, inbox=inbox, model=model, post=post, out=out)
        except (GitHubError, ValidationError, PermissionError, OSError) as error:
            state = inbox.release(event.id, max_attempts=config.max_attempts, reason=str(error))
            out(f"event {event.id} attempt {event.attempts} failed: {error}")
            if state == "failed":
                notify(config, f"review of {event.subject} failed after {event.attempts} attempts: {error}", now())
        handled += 1
    return handled


def health(config: ReviewerConfig, inbox: Inbox, now: float, out: Callable[[str], None]) -> bool:
    """Guide 9.5: poller stalled -> no statuses, alert after poller_stale_after_seconds."""
    last = inbox.health("poller.last_success")
    stale = last is None or now - last > config.stale_after_seconds
    if stale and inbox.health("poller.stale_alerted") != last:
        notify(config, f"poller stale: last success {last}", now)
        inbox.set_health("poller.stale_alerted", last)
    if not stale:
        inbox.set_health("poller.stale_alerted", None)
    out(f"poller {'STALE' if stale else 'ok'}; last success {last}")
    return not stale


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["poll", "work", "run", "health", "review"])
    parser.add_argument("--config", default=None)
    parser.add_argument("--pr", type=int, help="PR number for the review command")
    parser.add_argument("--post", action="store_true", help="post the asdi/review status (default: dry run)")
    parser.add_argument("--once", action="store_true", help="run: one cycle, then exit")
    args = parser.parse_args(argv)

    config = load_reviewer_config(args.config)
    inbox = Inbox(config.inbox_path)
    client = GitHubClient(config.repo, token_env=config.token_env)
    model = build_model(config.model)
    out = print
    now = time.time

    if args.command == "health":
        return 0 if health(config, inbox, now(), out) else 1
    if args.command == "review":
        if args.pr is None:
            parser.error("review needs --pr")
        sha = client.pull(args.pr)["head"]["sha"]
        inbox.record(source="manual", source_id=f"{config.repo}#{args.pr}@{sha}@{now()}",
                     subject=f"{config.repo}#{args.pr}", kind=PR_HEAD,
                     payload={"repo": config.repo, "number": args.pr, "head_sha": sha})
        work(config, client, inbox, model, post=args.post, out=out, now=now)
        return 0
    if args.command == "poll":
        out(f"recorded {poll_once(client, inbox, ignore_prs=config.ignore_prs, ignore_created_before=config.ignore_created_before, now=now)} new event(s)")
        return 0
    if args.command == "work":
        work(config, client, inbox, model, post=args.post, out=out, now=now)
        return 0
    while True:  # run
        try:
            poll_once(client, inbox, ignore_prs=config.ignore_prs,
                      ignore_created_before=config.ignore_created_before, now=now)
        except GitHubError as error:
            out(f"poll failed: {error}")  # no state lost; the next pass reconciles
        work(config, client, inbox, model, post=args.post, out=out, now=now)
        health(config, inbox, now(), lambda _: None)
        if args.once:
            return 0
        time.sleep(config.poll_interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
