import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src import player_images
from scripts import sync_player_images


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

    def test_missing_image_is_downloaded_and_added_to_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry_path = root / "player_images.json"
            asset_dir = root / "players"
            registry = {}
            response = Mock(content=b"image", url="https://example.test/player.jpg")
            response.headers = {"Content-Type": "image/jpeg"}
            metadata = {
                "download_url": response.url, "author": "Author", "license": "CC BY 4.0",
                "license_url": "https://license.test", "source_url": "https://source.test",
            }
            with patch.object(player_images, "REGISTRY_PATH", registry_path), \
                    patch.object(sync_player_images, "ASSET_DIR", asset_dir), \
                    patch.object(sync_player_images, "_find_wikidata_item", return_value=("Q1", "")), \
                    patch.object(sync_player_images, "_wikidata_image", return_value="Player.jpg"), \
                    patch.object(sync_player_images, "_commons_metadata", return_value=(metadata, "")), \
                    patch.object(sync_player_images, "_get", return_value=response):
                actual = sync_player_images.ensure_player_image(
                    "wta", 42, "Test Player", registry=registry, session=Mock(headers={}),
                )
            self.assertEqual(actual["path"], "../assets/players/wta-42-test-player.jpg")
            self.assertEqual((asset_dir / "wta-42-test-player.jpg").read_bytes(), b"image")
            self.assertIn("wta:42", player_images.load_registry(registry_path))


if __name__ == "__main__":
    unittest.main()
