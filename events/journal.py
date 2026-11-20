#!/usr/bin/env python3
"""Durable local event journal and recoverable poller state.

GitHub remains passive in REV K.  This module models the local poller's
catch-up cursor and event input; it never opens an inbound webhook route.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class EventJournal:
    """Append-only local event input with stable numeric sequence IDs."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "events.jsonl"

    def append(
        self,
        *,
        event_type: str,
        payload: dict[str, Any],
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        event_id = self.next_event_id()
        event = {
            "event_id": event_id,
            "occurred_at": occurred_at or utc_now(),
            "event_type": event_type,
            "payload": payload,
        }
        with self.path.open("a") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return event

    def load(self, after_event_id: int = 0) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        events = []
        for line in self.path.read_text().splitlines():
            if not line:
                continue
            event = json.loads(line)
            if event["event_id"] > after_event_id:
                events.append(event)
        return events

    def next_event_id(self) -> int:
        last = 0
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                if line:
                    last = max(last, int(json.loads(line)["event_id"]))
        return last + 1


class PollerState:
    """Durable cursor and health, so no event is lost while offline."""

    def __init__(self, root: str | Path) -> None:
        self.path = Path(root).resolve() / "poller-state.json"

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "cursor": 0,
                "processed_at": None,
                "healthy": True,
                "alert": None,
                "error": None,
            }
        return json.loads(self.path.read_text())

    def save(self, state: dict[str, Any]) -> None:
        state["updated_at"] = utc_now()
        atomic_json(self.path, state)


class LocalPoller:
    """Process durable events exactly once and record catch-up health."""

    def __init__(
        self,
        *,
        journal: EventJournal,
        state: PollerState,
        stale_after_seconds: int,
    ) -> None:
        self.journal = journal
        self.state_store = state
        self.stale_after_seconds = stale_after_seconds

    def catch_up(self, *, handler: Callable[[dict[str, Any]], None], now: float | None = None) -> dict[str, Any]:
        state = self.state_store.load()
        events = self.journal.load(state.get("cursor", 0))
        processed = 0
        for event in events:
            try:
                handler(event)
            except Exception as error:
                state.update(
                    {
                        "healthy": False,
                        "alert": "handler_failed",
                        "error": str(error),
                        "failed_event_id": event["event_id"],
                    }
                )
                self.state_store.save(state)
                raise
            state["cursor"] = event["event_id"]
            state["processed_at"] = utc_now()
            state["healthy"] = True
            state["alert"] = None
            state["error"] = None
            state.pop("failed_event_id", None)
            self.state_store.save(state)
            processed += 1
        if now is not None:
            state["observed_at_epoch"] = now
        self.state_store.save(state)
        return {"processed": processed, "state": state}

    def health(self, *, now: float) -> dict[str, Any]:
        state = self.state_store.load()
        last_event_id = self.journal.next_event_id() - 1
        cursor = int(state.get("cursor", 0))
        processed_at = state.get("processed_at")
        age_seconds = (
            now - time.mktime(time.strptime(processed_at, "%Y-%m-%dT%H:%M:%SZ"))
            if processed_at
            else None
        )
        stale = (
            cursor < last_event_id
            or age_seconds is None
            or age_seconds > self.stale_after_seconds
        )
        alert = None
        if stale:
            alert = "poller_stale" if cursor == last_event_id else "poller_backlog"
        return {
            "healthy": not stale and bool(state.get("healthy", False)),
            "cursor": cursor,
            "last_event_id": last_event_id,
            "age_seconds": age_seconds,
            "stale_after_seconds": self.stale_after_seconds,
            "alert": alert,
        }
