#!/usr/bin/env python3
"""Durable REV K launcher run state."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def load_run_state(runs_root: Path, run_id: str) -> dict[str, Any]:
    path = runs_root / run_id / "launcher-state.json"
    return json.loads(path.read_text())


def list_run_states(runs_root: Path) -> list[dict[str, Any]]:
    states: list[dict[str, Any]] = []
    runs_dir = runs_root
    if not runs_dir.exists():
        return states
    for path in runs_dir.glob("r-*/launcher-state.json"):
        states.append(json.loads(path.read_text()))
    return sorted(states, key=lambda item: item.get("started_at", ""))
