from __future__ import annotations

import hashlib
import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "reference/asdi-build-conformance.zip"
SKILL_ROOT = ROOT / "skills/asdi-build-conformance"


class SkillInstallTests(unittest.TestCase):
    def test_project_scoped_conformance_skill_is_installed(self) -> None:
        skill = SKILL_ROOT / "SKILL.md"
        self.assertTrue(skill.is_file())
        text = skill.read_text()
        self.assertIn("name: asdi-build-conformance", text)
        self.assertIn("actual ASDI implementation", text)
        self.assertIn("not the product-specific H-1 verify skill", text)

    def test_skill_is_scoped_to_asdi_not_toy_product(self) -> None:
        manifest = json.loads((SKILL_ROOT / "project.json").read_text())
        self.assertIn("ASDI repository implementation", manifest["scope"])
        self.assertIn("REV K toy-product runtime verification", manifest["not_scope"])
        self.assertTrue(manifest["read_only"])

    def test_all_four_spec_sources_are_pinned(self) -> None:
        manifest = json.loads((SKILL_ROOT / "project.json").read_text())
        for key in ("design", "stack", "build_guide", "trust_handbook"):
            self.assertIn(key, manifest["spec_paths"])
            self.assertTrue((ROOT / manifest["spec_paths"][key]).is_file())

    def test_archive_integrity_is_stable(self) -> None:
        result = subprocess.run(
            ["unzip", "-t", str(ARCHIVE)],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("No errors detected", result.stdout)
        digest = hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
        self.assertEqual(
            digest,
            "e0f144b2a2a403c8f946b1eff10c99f6bc875ff5391c9553baada771993bdcd7",
        )
