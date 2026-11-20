from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

from tests.test_toy_notes_support import (
    PRODUCT_ROOT,
    ROOT,
    SCHEMAS,
    SELF_TEST,
    product_environment,
    run_process,
)


sys.path.insert(0, str(ROOT))
from tools.validate_schema import validate_file


def feature_front_matter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    if match is None:
        raise AssertionError(f"no front matter in {path}")
    return json.loads(match.group(1))


def yaml_instance(path: Path, temporary: Path) -> Path:
    completed = subprocess.run(
        ["ruby", "-e", 'require "yaml"; require "json"; print JSON.generate(YAML.safe_load(File.read(ARGV[0])))', str(path)],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    destination = temporary / "metadata.json"
    destination.write_text(completed.stdout, encoding="utf-8")
    return destination


def verify_environment(root: Path, evidence: Path, run_id: str | None = None) -> dict[str, str]:
    environment = product_environment(root)
    environment["ASDI_EVIDENCE_DIR"] = str(evidence)
    environment["ASDI_HEAD"] = str(root)
    environment["ASDI_RUN_ID"] = run_id or "r-test-" + uuid.uuid4().hex
    environment.pop("TOY_NOTES_INJECT_DEFECT", None)
    return environment


def verify(root: Path, evidence: Path, *arguments: str, run_id: str | None = None) -> subprocess.CompletedProcess[str]:
    return run_process(
        [str(root / "verify" / "bin" / "verify"), *arguments],
        cwd=root,
        env=verify_environment(root, evidence, run_id),
    )


class ToyNotesHarnessContractTest(unittest.TestCase):
    def test_pilot_config_is_the_reversible_seam(self) -> None:
        text = (ROOT / "config" / "pilot.yaml").read_text(encoding="utf-8")
        self.assertIn("version: 1", text)
        self.assertIn("active: toy-notes", text)
        self.assertIn("product_root: pilots/toy_notes", text)
        self.assertIn("run_image: asdi/toy-notes-run:latest", text)

        decision_log = (ROOT / "state" / "owner-decisions.jsonl").read_text(encoding="utf-8")
        self.assertIn("approve_synthetic_toy_notes", decision_log)

    def test_feature_front_matter_validates_against_repo_schema(self) -> None:
        feature_paths = sorted((PRODUCT_ROOT / "verify" / "features").glob("*.md"))
        self.assertGreaterEqual(len(feature_paths), 3)
        kinds: set[str] = set()
        with tempfile.TemporaryDirectory() as temporary:
            instance = Path(temporary) / "front-matter.json"
            for path in feature_paths:
                front_matter = feature_front_matter(path)
                instance.write_text(json.dumps(front_matter), encoding="utf-8")
                self.assertEqual(
                    validate_file(SCHEMAS / "feature.schema.json", instance),
                    0,
                    f"{path.name} must satisfy feature.schema.json",
                )
                self.assertTrue(front_matter["limits"])
                self.assertEqual(front_matter["negative_control"]["expect"], "fail")
                self.assertTrue(front_matter["negative_control"]["mutate"])
                kinds.add(front_matter["drive"]["kind"])
        self.assertTrue({"cli", "http", "ui"}.issubset(kinds))

    def test_product_metadata_validates_against_repo_schemas(self) -> None:
        cases = [
            ("product.schema.json", PRODUCT_ROOT / ".asdi" / "product.yaml"),
            ("static-gates.schema.json", PRODUCT_ROOT / ".asdi" / "static-gates.yaml"),
            ("rules.schema.json", PRODUCT_ROOT / ".asdi" / "rules.yaml"),
            ("verify.schema.json", PRODUCT_ROOT / "verify" / "verify.yaml"),
        ]
        cases.extend(
            ("seed.schema.json", path)
            for path in sorted((PRODUCT_ROOT / ".asdi" / "seeds").glob("*.yaml"))
        )
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for schema_name, path in cases:
                self.assertEqual(
                    validate_file(SCHEMAS / schema_name, yaml_instance(path, directory)),
                    0,
                    f"{path.name} must satisfy {schema_name}",
                )

    def test_every_product_source_path_is_owned_by_a_feature(self) -> None:
        features = [feature_front_matter(path) for path in (PRODUCT_ROOT / "verify" / "features").glob("*.md")]
        patterns = [pattern for feature in features for pattern in feature["paths"]]
        sources = sorted((PRODUCT_ROOT / "src" / "toy_notes").glob("*.py"))
        self.assertTrue(sources)
        for source in sources:
            relative = source.relative_to(PRODUCT_ROOT).as_posix()
            self.assertTrue(
                any(fnmatch.fnmatchcase(relative, pattern) for pattern in patterns),
                f"{relative} has no feature path glob",
            )

    def test_seed_patches_are_valid_unified_diffs(self) -> None:
        hunk = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@$")
        with tempfile.TemporaryDirectory() as temporary:
            target_root = Path(temporary)
            for patch_path in sorted((PRODUCT_ROOT / ".asdi" / "seeds").glob("*.patch")):
                text = patch_path.read_text(encoding="utf-8")
                headers = [line for line in text.splitlines() if line.startswith("@@")]
                self.assertTrue(headers, f"{patch_path.name} has no hunk header")
                for header in headers:
                    self.assertRegex(header, hunk)
                source = next(
                    line.removeprefix("--- a/")
                    for line in text.splitlines()
                    if line.startswith("--- a/")
                )
                source_root = ROOT if source.startswith("config/") else PRODUCT_ROOT
                destination = target_root / source
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_root / source, destination)
                completed = subprocess.run(
                    ["patch", "--dry-run", "-p1", "-d", str(target_root)],
                    input=text,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(
                    completed.returncode,
                    0,
                    f"{patch_path.name} does not apply: {completed.stderr or completed.stdout}",
                )

    def test_harness_self_test_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            environment = os.environ.copy()
            environment["ASDI_EVIDENCE_DIR"] = temporary
            completed = run_process(
                [sys.executable, str(SELF_TEST)],
                cwd=ROOT,
                env=environment,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertIn("self-test: pass", completed.stdout)
            self.assertIn("result validates", completed.stdout)


class ToyNotesHarnessRuntimeTest(unittest.TestCase):
    def test_drive_result_validates_against_repo_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            evidence = Path(temporary) / "evidence"
            result_path = evidence / "result.json"
            run_id = "r-schema-" + uuid.uuid4().hex
            self.assertEqual(verify(PRODUCT_ROOT, evidence, "launch", run_id=run_id).returncode, 0)
            try:
                driven = verify(
                    PRODUCT_ROOT,
                    evidence,
                    "drive",
                    "cli-notes",
                    "http-notes",
                    "ui-note-list",
                    run_id=run_id,
                )
                self.assertEqual(driven.returncode, 0, driven.stdout + driven.stderr)
                self.assertTrue(result_path.is_file())
                self.assertEqual(validate_file(SCHEMAS / "result.schema.json", result_path), 0)
                result = json.loads(result_path.read_text(encoding="utf-8"))
                self.assertEqual(result["schema"], 2)
                self.assertEqual(result["run_id"], run_id)
                self.assertTrue(result["commit"])
                self.assertEqual(
                    {feature["id"] for feature in result["features"]},
                    {"cli-notes", "http-notes", "ui-note-list"},
                )
                for feature in result["features"]:
                    self.assertEqual(feature["status"], "pass")
                    self.assertEqual(feature["control"], "caught")
                    self.assertTrue(feature["evidence"])
                    self.assertTrue(feature["limits"])
                    for relative in feature["evidence"]:
                        self.assertTrue((evidence / relative).is_file(), relative)
            finally:
                verify(PRODUCT_ROOT, evidence, "cleanup", run_id=run_id)
                self.assertTrue(result_path.is_file())

    def test_changed_features_are_derived_and_unmapped_paths_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            base = workspace / "base"
            head = workspace / "head"
            shutil.copytree(PRODUCT_ROOT, base, ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copytree(PRODUCT_ROOT, head, ignore=shutil.ignore_patterns("__pycache__"))
            evidence = workspace / "evidence"
            run_id = "r-changed-" + uuid.uuid4().hex

            cli_source = head / "src" / "toy_notes" / "cli.py"
            cli_source.write_text(cli_source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            self.assertEqual(verify(head, evidence, "launch", run_id=run_id).returncode, 0)
            try:
                changed = verify(
                    head,
                    evidence,
                    "drive",
                    "--changed",
                    f"{base}..{head}",
                    run_id=run_id,
                )
                self.assertEqual(changed.returncode, 0, changed.stdout + changed.stderr)
                result = json.loads((evidence / "result.json").read_text(encoding="utf-8"))
                self.assertEqual([feature["id"] for feature in result["features"]], ["cli-notes"])

                (head / "src" / "toy_notes" / "unmapped.py").write_text("VALUE = 1\n", encoding="utf-8")
                unmapped = verify(
                    head,
                    evidence,
                    "drive",
                    "--changed",
                    f"{base}..{head}",
                    run_id=run_id,
                )
                self.assertEqual(unmapped.returncode, 2)
                self.assertIn("no feature", unmapped.stdout + unmapped.stderr)
            finally:
                verify(head, evidence, "cleanup", run_id=run_id)

    def test_breaking_each_feature_turns_drive_fail_and_control_caught(self) -> None:
        recipes = {
            "cli-notes": (
                "src/toy_notes/store.py",
                "if self.defect_active():",
                "if True or self.defect_active():",
            ),
            "http-notes": (
                "src/toy_notes/server.py",
                '        elif path == "/notes":\n            self._send_json(200, {"notes": self.store.list()})',
                '        elif False:\n            self._send_json(200, {"notes": self.store.list()})',
            ),
            "ui-note-list": (
                "src/toy_notes/server.py",
                "        if not ui_enabled():",
                "        if True:",
            ),
        }
        for feature_id, (relative, old, new) in recipes.items():
            with self.subTest(feature=feature_id):
                with tempfile.TemporaryDirectory() as temporary:
                    workspace = Path(temporary)
                    head = workspace / "head"
                    shutil.copytree(PRODUCT_ROOT, head, ignore=shutil.ignore_patterns("__pycache__"))
                    target = head / relative
                    text = target.read_text(encoding="utf-8")
                    self.assertIn(old, text)
                    target.write_text(text.replace(old, new, 1), encoding="utf-8")

                    evidence = workspace / "evidence"
                    run_id = "r-break-" + uuid.uuid4().hex
                    self.assertEqual(verify(head, evidence, "launch", run_id=run_id).returncode, 0)
                    try:
                        driven = verify(head, evidence, "drive", feature_id, run_id=run_id)
                        self.assertEqual(driven.returncode, 1, driven.stdout + driven.stderr)
                        result = json.loads((evidence / "result.json").read_text(encoding="utf-8"))
                        observed = {item["id"]: item for item in result["features"]}[feature_id]
                        self.assertEqual(observed["status"], "fail")
                        self.assertEqual(observed["control"], "caught")

                        controlled = verify(head, evidence, "control", feature_id, run_id=run_id)
                        self.assertEqual(controlled.returncode, 0, controlled.stdout + controlled.stderr)
                        self.assertEqual(json.loads(controlled.stdout)["controls"][feature_id], "caught")
                    finally:
                        verify(head, evidence, "cleanup", run_id=run_id)


if __name__ == "__main__":
    unittest.main()
