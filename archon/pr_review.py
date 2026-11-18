#!/usr/bin/env python3
"""ASDI PR reviewer: Pass 1 review pass (N-6).

Active path (owner override DD-48 of C-1/D-8; no API key in the repository):
  Claude, in the owner's Claude Code session, reviews each new PR head and runs
  ``verdict`` on its findings. ``verdict`` applies the same checks as any
  reviewer (schema 2, act needs evidence present in the diff, strike rules,
  fail closed) and renders one PR comment carrying
  ``<!-- asdi-review sha=<head> verdict=pass|fail|blocked -->``.
  ``.github/workflows/asdi-review.yml`` runs ``archon/gate_status.py`` with the
  built-in GITHUB_TOKEN to turn that comment into the ``asdi/review`` status.

Fallback (the REV K design): a local 60 s poller on the Studio with a local
model posts ``asdi/review`` itself (``run`` / ``poll`` / ``work``).

Commands:
  verdict    check session findings against a diff; write the verdict comment
  poll       one reconciliation pass over open PRs
  work       handle pending events until none is claimable
  run        poll + work every poller_interval_seconds (the service loop)
  health     report poller staleness; alert once when stale
  review     review one PR now (records and handles a single event)

The local commands post statuses only with --post; without it they are a dry
run that still stores and prints the result and the Review section.
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


def review_pull(
    config: ReviewerConfig,
    client: GitHubClient,
    model: ReviewModel | None,
    pull: dict[str, Any],
    number: int,
    sha: str,
) -> tuple[dict[str, Any], str, str]:
    """Run the review pass on one PR head; validate, store and render the result."""
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
    return result, section, store_result(config, result, section)


class SessionReviewer:
    """The reviewer is Claude in the owner's Claude Code session (DD-48).

    Its findings arrive as a JSON file; ``run_review`` applies exactly the same
    checks as for any other model: schema, evidence present in the diff for
    ``act``, strike rules, fail closed on unparseable output.
    """

    family = "anthropic"

    def __init__(self, reply: str, name: str = "claude-code-session") -> None:
        self.name, self._reply = name, reply

    def complete(self, system: str, user: str) -> str:
        return self._reply


def verdict_comment(result: dict[str, Any], section: str, sha: str) -> str:
    """The one PR comment the gate workflow reads (archon/gate_status.py)."""
    word = {"pass": "passed", "fail": "failed", "blocked": "blocked"}[result["status"]]
    return (
        f"<!-- asdi-review sha={sha} verdict={result['status']} -->\n"
        f"**ASDI review {word}** for `{sha[:12]}`.\n\n{section}\n"
        "A finding in Act must be fixed before merge. Each finding was checked against the diff; "
        "unsupported ones are demoted to Consider. A new commit resets `asdi/review` to pending until it is reviewed.\n\n"
        "---\n_Generated by [Claude Code](https://claude.ai/code)_\n"
    )


def verdict(
    config: ReviewerConfig,
    *,
    number: int,
    sha: str,
    diff: str,
    findings_json: str,
    title: str = "",
    body: str = "",
) -> tuple[dict[str, Any], str]:
    """Check a session review against the diff and render the verdict comment."""
    pr = PullRequestInput(repo=config.repo, number=number, head_sha=sha, title=title, body=body,
                          commit_messages=[], diff=diff)
    result = run_review(pr, SessionReviewer(findings_json), builder_families=config.builder_families,
                        max_diff_chars=config.max_diff_chars)
    _validate(result, SCHEMA, SCHEMA, "pass")
    section = render_review_section(result)
    store_result(config, result, section)
    return result, verdict_comment(result, section, sha)


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

    result, section, manifest = review_pull(config, client, model, pull, number, sha)
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
    parser.add_argument("command", choices=["verdict", "poll", "work", "run", "health", "review"])
    parser.add_argument("--config", default=None)
    parser.add_argument("--pr", type=int, help="PR number for the review and gate commands")
    parser.add_argument("--sha", help="verdict: the PR head commit that was reviewed")
    parser.add_argument("--diff-file", help="verdict: the reviewed diff")
    parser.add_argument("--findings-file", help='verdict: the session reviewer\'s {"findings": [...]} JSON')
    parser.add_argument("--out", help="verdict: write the comment body here")
    parser.add_argument("--post", action="store_true", help="post the asdi/review status (default: dry run)")
    parser.add_argument("--once", action="store_true", help="run: one cycle, then exit")
    args = parser.parse_args(argv)

    config = load_reviewer_config(args.config)
    client = GitHubClient(config.repo, token_env=config.token_env)
    out = print
    now = time.time

    if args.command == "verdict":
        if args.pr is None or not (args.sha and args.diff_file and args.findings_file and args.out):
            parser.error("verdict needs --pr, --sha, --diff-file, --findings-file and --out")
        result, body = verdict(config, number=args.pr, sha=args.sha,
                               diff=Path(args.diff_file).read_text(errors="replace"),
                               findings_json=Path(args.findings_file).read_text())
        Path(args.out).write_text(body)
        out(f"PR #{args.pr} @ {args.sha[:12]}: {result['status']}")
        return 0

    inbox = Inbox(config.inbox_path)
    model = build_model(config.model)

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
