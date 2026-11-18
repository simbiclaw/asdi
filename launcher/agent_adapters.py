"""ASDI-owned agent CLI adapter seam.

The launcher owns process boundaries and external guardrails. Each adapter
translates one run contract into the smallest CLI-specific invocation; no
adapter is authorized to change verification policy or evidence semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


AdapterName = Literal["fixture", "claude"]


@dataclass(frozen=True)
class AgentLaunch:
    command: list[str]
    binds: list[str]
    environment: dict[str, str]


class FixtureAgentAdapter:
    """The test-only launcher fixture; not a production agent CLI."""

    def __init__(self, agent_script: Path) -> None:
        self.agent_script = agent_script.resolve()

    def build(
        self,
        *,
        run_id: str,
        commit: str,
        contract_path: Path,
        model: str,
        proxy_name: str,
        model_base_url: str,
    model_alias: str = "claude-3-7-sonnet-latest",
    ) -> AgentLaunch:
        del contract_path, model, proxy_name, model_base_url
        return AgentLaunch(
            command=[
                "/usr/bin/python3",
                "/opt/asdi/fixture_agent.py",
                "--workspace",
                "/workspace",
                "--run-id",
                run_id,
                "--commit",
                commit,
            ],
            binds=[
                f"type=bind,source={self.agent_script},destination=/opt/asdi/fixture_agent.py,ro"
            ],
            environment={},
        )


class ClaudeAgentAdapter:
    """Adapter entry for the pinned Claude Code image."""

    def __init__(
        self,
        *,
        adapter_script: Path,
        instruction_root: Path,
        contract_path: Path,
        version: str = "2.1.283",
        wire_model_alias: str = "claude-3-7-sonnet-latest",
    ) -> None:
        self.adapter_script = adapter_script.resolve()
        self.instruction_root = instruction_root.resolve()
        self.contract_path = contract_path.resolve()
        self.version = version
        self.wire_model_alias = wire_model_alias

    @staticmethod
    def model_base_url(model_endpoint: str) -> str:
        """Return the Anthropic-compatible origin, not an OpenAI /v1 path."""

        normalized = model_endpoint.rstrip("/")
        if normalized.endswith("/v1"):
            return normalized[:-3]
        return normalized

    def build(
        self,
        *,
        run_id: str,
        commit: str,
        contract_path: Path,
        model: str,
        proxy_name: str,
        model_base_url: str,
    ) -> AgentLaunch:
        del run_id, commit, contract_path, proxy_name
        agents_md = self.instruction_root / "AGENTS.md"
        claude_md = self.instruction_root / "CLAUDE.md"
        if not agents_md.is_file() or not claude_md.is_file():
            raise RuntimeError("Claude adapter requires AGENTS.md and CLAUDE.md")
        return AgentLaunch(
            command=[
                "/usr/bin/python3",
                "/opt/asdi/claude_adapter.py",
                "--workspace",
                "/workspace",
                "--contract",
                "/opt/asdi/contract.json",
                "--model",
                self.wire_model_alias,
                "--cli-version",
                self.version,
            ],
            binds=[
                f"type=bind,source={self.adapter_script},destination=/opt/asdi/claude_adapter.py,ro",
                f"type=bind,source={self.contract_path},destination=/opt/asdi/contract.json,ro",
                f"type=bind,source={agents_md},destination=/opt/asdi/AGENTS.md,ro",
                f"type=bind,source={claude_md},destination=/opt/asdi/CLAUDE.md,ro",
            ],
            environment={
                "ANTHROPIC_BASE_URL": self.model_base_url(model_base_url),
            },
        )


def build_agent_launch(
    adapter: AdapterName,
    *,
    agent_script: Path,
    instruction_root: Path,
    contract_path: Path,
    run_id: str,
    commit: str,
    model: str,
    proxy_name: str,
    model_base_url: str,
    model_alias: str = "claude-3-7-sonnet-latest",
) -> AgentLaunch:
    if adapter == "fixture":
        return FixtureAgentAdapter(agent_script).build(
            run_id=run_id,
            commit=commit,
            contract_path=contract_path,
            model=model,
            proxy_name=proxy_name,
            model_base_url=model_base_url,
        )
    return ClaudeAgentAdapter(
        adapter_script=Path(__file__).resolve().parent / "agents" / "claude_adapter.py",
        instruction_root=instruction_root,
        contract_path=contract_path,
        wire_model_alias=model_alias,
    ).build(
        run_id=run_id,
        commit=commit,
        contract_path=contract_path,
        model=model,
        proxy_name=proxy_name,
        model_base_url=model_base_url,
    )
