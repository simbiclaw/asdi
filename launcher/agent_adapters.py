"""Explicit, board-neutral runtime adapter registry for REV K launcher runs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AgentAdapter:
    name: str
    script_name: str
    command_name: str
    stream_format: str


ADAPTERS: dict[str, AgentAdapter] = {
    adapter.name: adapter
    for adapter in (
        AgentAdapter("fixture", "fixture_agent.py", "fixture-agent", "asdi-events"),
        AgentAdapter("claude", "claude_adapter.py", "claude", "stream-json"),
    )
}


def adapter_script(root: Path, name: str) -> Path:
    try:
        adapter = ADAPTERS[name]
    except KeyError as error:
        raise ValueError(f"unknown agent adapter: {name}") from error
    return root / adapter.script_name
