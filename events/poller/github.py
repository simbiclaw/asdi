"""Outbound-only GitHub API client and the 60 s PR poller (D-8, Stack doc section 02).

GitHub is passive (C-1): ASDI calls out, nothing calls in. The poller reconciles
against current state on every pass, so missed passes and GitHub outages lose
nothing: the next successful pass records whatever changed.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Callable

from events.inbox import Inbox

API = "https://api.github.com"
PR_HEAD = "pr.head"


class GitHubError(RuntimeError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class DiffUnavailable(GitHubError):
    """GitHub refuses to render the diff (HTTP 406: too many lines or files)."""


class GitHubClient:
    """Minimal REST client. The token comes from the environment, never a file."""

    def __init__(
        self,
        repo: str,
        *,
        token_env: str = "ASDI_ARCHON_GITHUB_TOKEN",
        api: str = API,
        opener: Callable[[urllib.request.Request], Any] | None = None,
    ) -> None:
        owner, _, name = repo.partition("/")
        if not owner or not name:
            raise ValueError(f"repo must be owner/name, got {repo!r}")
        self.repo = repo
        self._api = api.rstrip("/")
        self._token = os.environ.get(token_env, "")
        self._open = opener or (lambda request: urllib.request.urlopen(request, timeout=30))

    def _request(self, method: str, path: str, *, body: Any = None, accept: str = "application/vnd.github+json") -> Any:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(f"{self._api}{path}", data=data, method=method)
        request.add_header("Accept", accept)
        request.add_header("X-GitHub-Api-Version", "2022-11-28")
        request.add_header("User-Agent", "asdi-archon")
        if self._token:
            request.add_header("Authorization", f"Bearer {self._token}")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with self._open(request) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            raise GitHubError(f"{method} {path}: HTTP {error.code}", error.code) from error
        except (urllib.error.URLError, OSError) as error:
            raise GitHubError(f"{method} {path}: {error}") from error
        if accept.endswith("diff"):
            return raw.decode("utf-8", errors="replace")
        return json.loads(raw) if raw else None

    def open_pulls(self) -> list[dict[str, Any]]:
        pulls: list[dict[str, Any]] = []
        page = 1
        while True:
            batch = self._request("GET", f"/repos/{self.repo}/pulls?state=open&per_page=100&page={page}")
            pulls.extend(batch)
            if len(batch) < 100:
                return pulls
            page += 1

    def pull(self, number: int) -> dict[str, Any]:
        return self._request("GET", f"/repos/{self.repo}/pulls/{number}")

    def pull_diff(self, number: int) -> str:
        try:
            return self._request("GET", f"/repos/{self.repo}/pulls/{number}", accept="application/vnd.github.diff")
        except GitHubError as error:
            if error.status == 406:
                raise DiffUnavailable(f"GitHub will not render the diff of PR #{number} (too large)", 406) from error
            raise

    def pull_commits(self, number: int) -> list[dict[str, Any]]:
        return self._request("GET", f"/repos/{self.repo}/pulls/{number}/commits?per_page=100")

    def post_status(self, sha: str, *, state: str, context: str, description: str, target_url: str | None) -> None:
        body: dict[str, Any] = {"state": state, "context": context, "description": description[:140]}
        if target_url:
            body["target_url"] = target_url
        self._request("POST", f"/repos/{self.repo}/statuses/{sha}", body=body)


def _created_before(pull: dict[str, Any], cutoff: str | None) -> bool:
    if not cutoff:
        return False
    created = datetime.fromisoformat(pull["created_at"].replace("Z", "+00:00"))
    return created <= datetime.fromisoformat(cutoff.replace("Z", "+00:00"))


def poll_once(
    client: GitHubClient,
    inbox: Inbox,
    *,
    ignore_prs: tuple[int, ...] = (),
    ignore_created_before: str | None = None,
    now: Callable[[], float],
) -> int:
    """One reconciliation pass. Returns the number of new events recorded."""
    try:
        pulls = client.open_pulls()
    except GitHubError as error:
        inbox.set_health("poller.last_error", {"at": now(), "error": str(error)})
        raise
    recorded = 0
    for pull in pulls:
        number = int(pull["number"])
        if pull.get("draft") or number in ignore_prs or _created_before(pull, ignore_created_before):
            continue
        sha = pull["head"]["sha"]
        if inbox.record(
            source="github",
            source_id=f"{client.repo}#{number}@{sha}",
            subject=f"{client.repo}#{number}",
            kind=PR_HEAD,
            payload={"repo": client.repo, "number": number, "head_sha": sha},
        ):
            recorded += 1
            inbox.audit("review.requested", repo=client.repo, pr=number, sha=sha)
    inbox.set_health("poller.last_success", now())
    return recorded
