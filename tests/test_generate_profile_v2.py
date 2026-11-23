import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from src import generate_profile_v2


class GeneratePlayerProfileV2Tests(unittest.TestCase):
    def test_generate_one_writes_profile_and_search_index(self):
        profile = {
            "schema_version": 2,
            "generated_at_utc": "2026-11-23T12:00:00+00:00",
            "player": {"name": "João Sousa", "tour": "atp", "player_id": 7},
            "overall_sample": {"matches": 12, "status": "VERY_LOW"},
            "alerts": [{"severity": "CRITICAL"}],
            "metrics": [],
        }
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(generate_profile_v2.fetch_data, "get_history", return_value=pd.DataFrame()), \
             patch.object(generate_profile_v2.fetch_data, "get_historical_odds_history", return_value=pd.DataFrame()), \
             patch.object(generate_profile_v2.fetch_data, "get_player_id_from_ranking", return_value=7), \
             patch.object(generate_profile_v2, "build_player_profile_v2_record", return_value=profile):
            root = Path(directory)
            path = generate_profile_v2.generate_one("João Sousa", "atp", root)

            self.assertEqual(path.name, "joao-sousa.json")
            index = json.loads((root / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(index["players"][0]["name"], "João Sousa")
            self.assertTrue(index["players"][0]["has_critical_alert"])
            self.assertEqual(index["players"][0]["profile_path"], "atp/joao-sousa.json")
            generate_profile_v2.fetch_data.get_historical_odds_history.assert_called_once_with(
                "atp", refresh_current=False,
            )

    def test_rebuild_index_is_sorted_by_tour_and_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for tour, name in (("wta", "Zeta"), ("atp", "Beta"), ("atp", "Alfa")):
                path = root / tour / f"{name.lower()}.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({
                    "generated_at_utc": "2026-11-23T12:00:00+00:00",
                    "player": {"name": name, "tour": tour},
                    "overall_sample": {"matches": 20, "status": "LIMITED"},
                    "alerts": [],
                    "metrics": [],
                }), encoding="utf-8")

            generate_profile_v2.rebuild_index(root)
            index = json.loads((root / "index.json").read_text(encoding="utf-8"))

        self.assertEqual([row["name"] for row in index["players"]], ["Alfa", "Beta", "Zeta"])


if __name__ == "__main__":
    unittest.main()
