import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src import player_images
from src import report_html
from scripts import sync_player_images


class PlayerImageRegistryTests(unittest.TestCase):
    @staticmethod
    def _manual_override(root: Path, **changes):
        asset = root / "docs" / "assets" / "players" / "manual" / "test-player.jpg"
        asset.parent.mkdir(parents=True)
        asset.write_bytes(b"licensed-image")
        entry = {
            "tour": "atp",
            "player_id": 42,
            "name": "Test Player",
            "source_url": "https://commons.wikimedia.org/wiki/File:Test_Player.jpg",
            "author": "Test Author",
            "license": "CC BY-SA 4.0",
            "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
            "path": "../assets/players/manual/test-player.jpg",
            "modifications": "recorte quadrado; sem outras adaptações",
        }
        entry.update(changes)
        return {"atp:42": entry}

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

    def test_valid_manual_override_precedes_commons_and_renders_existing_credit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            overrides = self._manual_override(root)
            registry = {"atp:42": {"name": "Test Player", "path": "commons.jpg"}}

            actual = player_images.find_player_image(
                "atp", 42, "Test Player", registry,
                overrides=overrides, project_root=root,
            )
            rendered = report_html.build_report_html_v2({
                "player_a": "Test Player", "player_b": "Fallback Player",
                "player_image_a": actual,
            }, {}, report_html._calcular_divergencia)

            self.assertEqual(actual["provenance"], "MANUAL_LICENSED_OVERRIDE")
            self.assertEqual(actual["path"], "../assets/players/manual/test-player.jpg")
            self.assertIn('src="../assets/players/manual/test-player.jpg"', rendered)
            self.assertIn("Sem fotografia de Fallback Player", rendered)
            self.assertIn("Test Author", rendered)
            self.assertIn("CC BY-SA 4.0", rendered)
            self.assertIn("recorte quadrado; sem outras adaptações", rendered)
            self.assertIn(actual["source_url"], rendered)

    def test_manual_override_without_license_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            overrides = self._manual_override(root, license="")
            registry = {"atp:42": {"name": "Test Player", "path": "commons.jpg"}}

            actual = player_images.find_player_image(
                "atp", 42, "Test Player", registry,
                overrides=overrides, project_root=root,
            )

            self.assertEqual(actual["path"], "commons.jpg")

    def test_manual_override_without_source_url_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            overrides = self._manual_override(root, source_url="")

            actual = player_images.find_player_image(
                "atp", 42, "Test Player", {},
                overrides=overrides, project_root=root,
            )

            self.assertIsNone(actual)

    def test_manual_override_without_local_asset_falls_back_safely(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            overrides = self._manual_override(
                root, path="../assets/players/manual/missing.jpg",
            )
            registry = {"atp:42": {"name": "Test Player", "path": "commons.jpg"}}

            actual = player_images.find_player_image(
                "atp", 42, "Test Player", registry,
                overrides=overrides, project_root=root,
            )

            self.assertEqual(actual["path"], "commons.jpg")

    def test_blockx_remains_initials_without_reusable_licence_proof(self):
        actual = player_images.find_player_image("atp", 88766, "Alexander Blockx")
        html = report_html.build_report_html_v2(
            {"player_a": "Alexander Blockx", "player_b": "Other Player"},
            {}, report_html._calcular_divergencia,
        )

        self.assertIsNone(actual)
        self.assertIn("Sem fotografia de Alexander Blockx", html)
        self.assertIn(">AB</div>", html)

        curated = sync_player_images._load_curated_review_reasons()
        self.assertEqual(curated[("atp", "88766")], "LICENSED_SOURCE_UNAVAILABLE")

    def test_asset_outside_player_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "private.jpg"
            outside.write_bytes(b"not-an-allowed-asset")
            overrides = self._manual_override(root, path="../../../private.jpg")

            actual = player_images.find_player_image(
                "atp", 42, "Test Player", {},
                overrides=overrides, project_root=root,
            )

            self.assertIsNone(actual)

    def test_record_review_restores_curated_unavailable_reason(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            review_path = root / "player_images_review.json"
            curated_path = root / "player_image_review_overrides.json"
            review_path.write_text(json.dumps({"players": [{
                "tour": "atp", "player_id": 88766, "name": "Alexander Blockx",
                "rank": 34, "reason": "jogador sem fotografia P18 no Wikidata",
            }]}), encoding="utf-8")
            curated_path.write_text(json.dumps({"players": [{
                "tour": "atp", "player_id": 88766, "name": "Alexander Blockx",
                "reason": "LICENSED_SOURCE_UNAVAILABLE",
            }]}), encoding="utf-8")

            with patch.object(sync_player_images, "REVIEW_PATH", review_path), \
                    patch.object(sync_player_images, "CURATED_REVIEW_PATH", curated_path):
                sync_player_images._record_review({
                    "tour": "atp", "player_id": 88766, "name": "Alexander Blockx",
                    "rank": 34, "reason": "jogador sem fotografia P18 no Wikidata",
                })

            review = json.loads(review_path.read_text(encoding="utf-8"))["players"]
            blockx = next(item for item in review if item.get("player_id") == 88766)
            self.assertEqual(blockx["reason"], "LICENSED_SOURCE_UNAVAILABLE")

    def test_sync_keeps_player_in_review_when_no_valid_override_or_commons_image_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry_path = root / "player_images.json"
            review_path = root / "player_images_review.json"
            curated_path = root / "player_image_review_overrides.json"
            registry_path.write_text('{"schema_version": 1, "players": {}}', encoding="utf-8")
            review_path.write_text(json.dumps({"players": [{
                "tour": "atp", "player_id": 88766, "name": "Alexander Blockx",
                "rank": 116, "reason": "jogador sem fotografia P18 no Wikidata",
            }]}), encoding="utf-8")
            curated_path.write_text(json.dumps({"players": [{
                "tour": "atp", "player_id": 88766, "name": "Alexander Blockx",
                "reason": "LICENSED_SOURCE_UNAVAILABLE",
            }]}), encoding="utf-8")
            ranking = {"Alexander Blockx": {
                "player_id": 88766, "name": "Alexander Blockx", "rank": 116,
            }}

            with patch.object(player_images, "REGISTRY_PATH", registry_path), \
                    patch.object(sync_player_images, "REVIEW_PATH", review_path), \
                    patch.object(sync_player_images, "CURATED_REVIEW_PATH", curated_path), \
                    patch.object(player_images, "load_manual_overrides", return_value={}), \
                    patch.object(sync_player_images.fetch_data, "fetch_official_ranking", return_value=ranking), \
                    patch.object(sync_player_images, "_find_wikidata_item", return_value=(None, "sem P18")):
                sync_player_images.sync(limit=1, tours=("atp",), delay=0)

            review = json.loads(review_path.read_text(encoding="utf-8"))["players"]
            blockx = next(item for item in review if item.get("player_id") == 88766)
            self.assertEqual(blockx["reason"], "LICENSED_SOURCE_UNAVAILABLE")

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
