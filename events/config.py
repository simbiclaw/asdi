"""Load operational defaults from the authoritative config files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_defaults(path: str | Path) -> dict[str, Any]:
    value = yaml.safe_load(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError("defaults config must be an object")
    stale_after_seconds = value.get("poller_stale_after_seconds")
    if (
        not isinstance(stale_after_seconds, int)
        or isinstance(stale_after_seconds, bool)
        or stale_after_seconds <= 0
    ):
        raise ValueError("poller_stale_after_seconds must be a positive integer")
    return dict(value)
