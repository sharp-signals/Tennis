import json
import tempfile
import unittest
from pathlib import Path

from src import player_images


class PlayerImageRegistryTests(unittest.TestCase):
    def test_resolves_by_stable_id_before_name(self):
        registry = {
            "wta:10": {"name": "Different Name", "path": "a.jpg"},
            "wta:20": {"name": "Xinyu Wang", "path": "b.jpg"},
        }
        actual = player_images.find_player_image("WTA", 10, "Xinyu Wang", registry)
        self.assertEqual(actual["path"], "a.jpg")

    def test_unique_accent_insensitive_name_is_safe_fallback(self):
        registry = {"wta:10": {"name": "Donna Vekić", "path": "donna.jpg"}}
        actual = player_images.find_player_image("wta", None, "Donna Vekic", registry)
        self.assertEqual(actual["path"], "donna.jpg")

    def test_invalid_registry_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "images.json"
            path.write_text("not-json", encoding="utf-8")
            self.assertEqual(player_images.load_registry(path), {})


if __name__ == "__main__":
    unittest.main()
