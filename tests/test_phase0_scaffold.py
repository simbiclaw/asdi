from __future__ import annotations

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.validate_schema import validate_file
from merge.dry_run import evaluate


ROOT = Path(__file__).resolve().parents[1]


class Phase0ScaffoldTests(unittest.TestCase):
    def test_all_examples_validate(self) -> None:
        result = subprocess.run(
            ["python3", str(ROOT / "tools" / "validate_examples.py")],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("validated 12 REV K examples", result.stdout)

    def test_invalid_run_contract_fails_closed(self) -> None:
        value = json.loads((ROOT / "schemas/examples/run-contract.valid.json").read_text())
        invalid = copy.deepcopy(value)
        del invalid["done_check"]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "invalid.json"
            path.write_text(json.dumps(invalid))
            result = validate_file(
                ROOT / "schemas/run-contract.schema.json", path
            )
        self.assertEqual(result, 1)

    def test_compose_zone_topology_is_enforced(self) -> None:
        completed = subprocess.run(
            ["ruby", "-e", 'require "yaml"; require "json"; print JSON.generate(YAML.safe_load(File.read("compose.yaml")))'],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        compose = json.loads(completed.stdout)
        networks = compose["networks"]
        self.assertTrue(networks["prod"]["internal"])
        self.assertTrue(networks["agent"]["internal"])
        self.assertTrue(networks["ops"]["internal"])
        self.assertFalse(networks["egress"].get("internal", False))
        self.assertNotIn("prod", compose["services"]["agent-canary"]["networks"])
        self.assertNotIn("agent", compose["services"]["prod-canary"]["networks"])
        self.assertNotIn("prod", compose["services"]["egress-proxy"]["networks"])

    def test_config_yaml_is_parseable_and_fail_closed(self) -> None:
        completed = subprocess.run(
            [
                "ruby",
                "-e",
                'require "yaml"; require "json"; puts JSON.generate(Dir["config/*.yaml"].to_h { |f| [File.basename(f, ".yaml"), YAML.safe_load(File.read(f))] })',
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        configs = json.loads(completed.stdout)
        self.assertFalse(configs["dependencies"]["allow_install_scripts"])
        self.assertTrue(configs["coverage"]["t0_promotion_requires"]["all_seeds_caught"])
        self.assertIn("agents", configs["identities"]["identities"])

    def test_merge_policy_refuses_agent_and_requires_human_at_t0(self) -> None:
        refused = evaluate(
            actor="agents",
            statuses={"ci", "asdi/policy"},
            up_to_date=True,
            classification="agent-mergeable",
            trm_level="T0",
        )
        self.assertEqual(refused["decision"], "refused")
        human = evaluate(
            actor="merge-bot",
            statuses={"ci", "asdi/policy"},
            up_to_date=True,
            classification="agent-mergeable",
            trm_level="T0",
        )
        self.assertEqual(human["decision"], "human_required")
        blocked = evaluate(
            actor="merge-bot",
            statuses={"ci"},
            up_to_date=False,
            classification="agent-mergeable",
            trm_level="T1",
        )
        self.assertEqual(blocked["decision"], "blocked")
