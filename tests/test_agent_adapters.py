from __future__ import annotations

import json
import os
import sys
from unittest import mock
import subprocess
import tempfile
import unittest
from pathlib import Path

from launcher.agent_adapters import ClaudeAgentAdapter, build_agent_launch
from launcher.egress_proxy import EgressHandler
import urllib.parse


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "schemas/examples/run-contract.valid.json"


class ClaudeAdapterTests(unittest.TestCase):
    def test_claude_launch_is_streamed_hooked_and_secret_free(self) -> None:
        launch = build_agent_launch(
            "claude",
            agent_script=ROOT / "launcher/agents/fixture_agent.py",
            instruction_root=ROOT,
            contract_path=CONTRACT,
            run_id="r-fixture",
            commit="c" * 40,
            model="qwen3.6-35b-dspark-local",
            proxy_name="asdi-egress-fixture",
            model_base_url="http://host.docker.internal:4000/v1",
        )
        self.assertEqual(launch.command[0], "/usr/bin/python3")
        self.assertIn("claude_adapter.py", launch.command[1])
        self.assertIn("--model", launch.command)
        self.assertEqual(
            launch.command[launch.command.index("--model") + 1],
            "claude-3-7-sonnet-latest",
        )
        self.assertIn("--cli-version", launch.command)
        self.assertIn("2.1.283", launch.command)
        self.assertEqual(
            launch.environment["ANTHROPIC_BASE_URL"], "http://host.docker.internal:4000"
        )
        for key in launch.environment:
            self.assertNotIn("API_KEY", key.upper())
            self.assertNotIn("TOKEN", key.upper())
        self.assertFalse(any("docker.sock" in bind for bind in launch.binds))
        self.assertTrue(any("AGENTS.md" in bind for bind in launch.binds))
        self.assertTrue(any("CLAUDE.md" in bind for bind in launch.binds))

    def test_adapter_selection_has_isolated_cli_specific_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            contract = Path(temporary) / "contract.json"
            contract.write_text(CONTRACT.read_text())
            fixture = build_agent_launch(
                "fixture",
                agent_script=ROOT / "launcher/agents/fixture_agent.py",
                instruction_root=ROOT,
                contract_path=contract,
                run_id="r-fixture",
                commit="c" * 40,
                model="fixture",
                proxy_name="proxy",
                model_base_url="http://model.invalid/v1",
            )
            claude = build_agent_launch(
                "claude",
                agent_script=fixture.command[1],
                instruction_root=ROOT,
                contract_path=contract,
                run_id="r-fixture",
                commit="c" * 40,
                model="fixture",
                proxy_name="proxy",
                model_base_url="http://model.invalid/v1",
            )
            self.assertNotEqual(fixture.command, claude.command)
            self.assertTrue(claude.command[1].endswith("claude_adapter.py"))

    def test_stop_hook_runs_contract_done_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            workspace.mkdir()
            contract_path = Path(temporary) / "contract.json"
            contract = json.loads(CONTRACT.read_text())
            contract["done_check"] = {
                "command": ["/usr/bin/touch", "done"],
                "timeout_seconds": 5,
            }
            contract_path.write_text(json.dumps(contract))
            passed = subprocess.run(
                [
                    "/usr/bin/python3",
                    str(ROOT / "launcher/agents/claude_adapter.py"),
                    "--done-check",
                    "--workspace",
                    str(workspace),
                    "--contract",
                    str(contract_path),
                ],
                input="{}",
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(passed.returncode, 0, passed.stderr)
            self.assertTrue((workspace / "done").is_file())
            contract["done_check"]["command"] = ["/usr/bin/false"]
            contract_path.write_text(json.dumps(contract))
            failed = subprocess.run(
                [
                    "/usr/bin/python3",
                    str(ROOT / "launcher/agents/claude_adapter.py"),
                    "--done-check",
                    "--workspace",
                    str(workspace),
                    "--contract",
                    str(contract_path),
                ],
                input="{}",
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(failed.returncode, 2)

    def test_model_origin_is_normalized_for_claude(self) -> None:
        self.assertEqual(
            ClaudeAgentAdapter.model_base_url("http://host:4000/v1/"),
            "http://host:4000",
        )

    def test_proxy_removes_agent_credential_headers(self) -> None:
        forwarded = EgressHandler.forwardable_headers(
            {
                "Authorization": "Bearer placeholder",
                "X-Api-Key": "placeholder",
                "Proxy-Authorization": "placeholder",
                "Content-Type": "application/json",
            }
        )
        self.assertEqual(forwarded, {"Content-Type": "application/json"})

    def test_proxy_rewrites_wire_alias_to_local_model_outside_sandbox(self) -> None:
        rewritten = EgressHandler.rewrite_model_request(
            b'{"model":"claude-3-7-sonnet-latest","stream":true}',
            "qwen3.6-35b-dspark-local",
        )
        self.assertEqual(
            json.loads(rewritten),
            {"model": "qwen3.6-35b-dspark-local", "stream": True},
        )

    def test_proxy_origin_path_is_unwrapped_from_absolute_proxy_uri(self) -> None:
        parsed = urllib.parse.urlsplit(
            "http://model.invalid:4000/v1/messages?beta=true"
        )
        self.assertEqual(
            EgressHandler.origin_path(parsed), "/v1/messages?beta=true"
        )

    def test_claude_invocation_streams_events_and_installs_stop_hook(self) -> None:
        module = __import__(
            "launcher.agents.claude_adapter", fromlist=["_build_invocation"]
        )
        original_workspace = os.getcwd()
        captured = {}

        def fake_execve(path, arguments, environment):
            captured["path"] = path
            captured["arguments"] = arguments
            captured["environment"] = environment

        with tempfile.TemporaryDirectory() as temporary:
            contract_path = Path(temporary) / "contract.json"
            contract_path.write_text(CONTRACT.read_text())
            with mock.patch.dict(
                "os.environ",
                {
                    "ANTHROPIC_BASE_URL": "http://model.invalid:4000",
                },
            ):
                with mock.patch.object(
                    sys,
                    "argv",
                    [
                        "claude_adapter.py",
                        "--workspace",
                        "/workspace",
                        "--contract",
                        str(contract_path),
                        "--model",
                        "qwen3.6-35b-dspark-local",
                        "--cli-version",
                        "2.1.283",
                    ],
                ):
                    with mock.patch.object(os, "chdir"):
                        with mock.patch.object(os, "execve", fake_execve):
                            module.main()
        os.chdir(original_workspace)
        self.assertEqual(captured["path"], "/home/sclaw/.local/share/claude/versions/2.1.283")
        arguments = captured["arguments"]
        self.assertIn("--output-format", arguments)
        self.assertEqual(arguments[arguments.index("--output-format") + 1], "stream-json")
        self.assertIn("--permission-prompts", arguments)
        self.assertEqual(arguments[arguments.index("--permission-prompts") + 1], "none")
        settings_path = Path(arguments[arguments.index("--settings") + 1])
        settings = json.loads(settings_path.read_text())
        self.assertIn("hooks", settings)
        self.assertIn("Stop", settings["hooks"])
        self.assertIn("apiKeyHelper", settings)
        self.assertNotIn("proxy-only-key", settings_path.read_text())
        self.assertNotIn("API_KEY", captured["environment"])
        self.assertNotIn("TOKEN", captured["environment"])

    def test_claude_preserves_safe_proxy_routing_environment(self) -> None:
        module = __import__(
            "launcher.agents.claude_adapter", fromlist=["_build_invocation"]
        )
        captured = {}

        def fake_execve(_path, _arguments, environment):
            captured.update(environment)

        with tempfile.TemporaryDirectory() as temporary:
            contract_path = Path(temporary) / "contract.json"
            contract_path.write_text(CONTRACT.read_text())
            proxy_environment = {
                "ANTHROPIC_BASE_URL": "http://model.invalid:4000",
                "HTTP_PROXY": "http://proxy:8081",
                "HTTPS_PROXY": "http://proxy:8081",
                "NO_PROXY": "localhost",
                "LITELLM_MASTER_KEY": "proxy-only-key",
            }
            with mock.patch.dict("os.environ", proxy_environment):
                with mock.patch.object(os, "chdir"):
                    with mock.patch.object(os, "execve", fake_execve):
                        with mock.patch.object(
                            sys,
                            "argv",
                            [
                                "claude_adapter.py",
                                "--workspace",
                                "/workspace",
                                "--contract",
                                str(contract_path),
                                "--model",
                                "claude-3-7-sonnet-latest",
                            ],
                        ):
                            module.main()
        self.assertEqual(captured["HTTP_PROXY"], "http://proxy:8081")
        self.assertEqual(captured["HTTPS_PROXY"], "http://proxy:8081")
        self.assertEqual(captured["NO_PROXY"], "localhost")
        self.assertNotIn("LITELLM_MASTER_KEY", captured)
