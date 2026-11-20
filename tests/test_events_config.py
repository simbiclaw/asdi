from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from events.classifier import load_mapping
from events.config import load_pilot_config


ROOT = Path(__file__).resolve().parents[1]


class DefaultFeatureMapTests(unittest.TestCase):
    def test_repository_default_feature_map_loads(self) -> None:
        value = yaml.safe_load((ROOT / "config" / "features.yaml").read_text())
        mapping = load_mapping(value)
        self.assertEqual(set(mapping), {"cli-notes", "http-notes", "ui-note-list"})
        self.assertTrue(
            any(path.endswith("toy_notes/cli.py") for path in mapping["cli-notes"])
        )
        self.assertTrue(
            any(path.endswith("toy_notes/server.py") for path in mapping["http-notes"])
        )


class PilotConfigTests(unittest.TestCase):
    def write(self, root: Path, value: dict) -> Path:
        path = root / "pilot.yaml"
        path.write_text(yaml.safe_dump(value, sort_keys=True))
        return path

    def test_active_pilot_is_bound_to_product_root_and_image(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write(
                Path(temporary),
                {
                    "version": 1,
                    "active": "toy-notes",
                    "pilots": {
                        "toy-notes": {
                            "product_root": "pilots/toy_notes",
                            "run_image": "asdi/toy-notes-run:latest",
                        }
                    },
                },
            )
            selection = load_pilot_config(path)
            self.assertEqual(selection.active, "toy-notes")
            self.assertEqual(selection.product_root.name, "toy_notes")
            self.assertEqual(selection.run_image, "asdi/toy-notes-run:latest")

    def test_missing_active_configuration_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write(
                Path(temporary),
                {"version": 1, "active": "missing", "pilots": {}},
            )
            with self.assertRaisesRegex(ValueError, "no configuration"):
                load_pilot_config(path)


if __name__ == "__main__":
    unittest.main()
