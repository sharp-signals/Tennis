import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from scripts.generated_output_contract import is_allowed
from src import generate_player_profile_catalog as catalog


class PlayerProfileCatalogTests(unittest.TestCase):
    def test_generated_catalog_paths_are_allowed_for_bot_publication(self):
        self.assertTrue(is_allowed("data/player_profiles/v2/index.json", "bot"))
        self.assertTrue(is_allowed("docs/jogadores/index.html", "bot"))
        self.assertTrue(is_allowed("data/player_profiles/v2/index.json", "player-profiles"))
        self.assertTrue(is_allowed("docs/jogadores/index.html", "player-profiles"))

    def test_active_players_exclude_future_and_old_rows(self):
        history = pd.DataFrame([
            {"winner_name": "Active A", "loser_name": "Active B", "tourney_date": 20261101},
            {"winner_name": "Future", "loser_name": "Active A", "tourney_date": 20261201},
            {"winner_name": "Old", "loser_name": "Older", "tourney_date": 20200101},
        ])
        players = catalog.select_active_players(
            history,
            cutoff=pd.Timestamp("2026-11-23T12:00:00Z").to_pydatetime(),
            active_days=730,
        )
        self.assertEqual(players, ["Active A", "Active B"])

    def test_player_row_index_preserves_audited_name_aliases(self):
        history = pd.DataFrame([
            {"winner_name": "Taylor Harry Fritz", "loser_name": "Opponent"},
            {"winner_name": "Other", "loser_name": "Taylor Fritz"},
        ])
        index = catalog._player_row_index(history)
        rows = catalog._rows_for_player(history, index, "Taylor Fritz")
        self.assertEqual(len(rows), 2)

    def test_player_subsets_have_distinct_name_cache_keys(self):
        history = pd.DataFrame([
            {"winner_name": "Player A", "loser_name": "Opponent A"},
            {"winner_name": "Player B", "loser_name": "Opponent B"},
        ])
        history.attrs["history_cache_key"] = "shared-parent"
        index = catalog._player_row_index(history)
        player_a = catalog._rows_for_player(history, index, "Player A")
        player_b = catalog._rows_for_player(history, index, "Player B")

        catalog.fetch_data._NAME_INDEX_CACHE.clear()
        self.assertEqual(catalog.fetch_data.resolve_player_name(player_a, "Player A"), "Player A")
        self.assertEqual(catalog.fetch_data.resolve_player_name(player_b, "Player B"), "Player B")
        self.assertNotEqual(
            player_a.attrs["history_cache_key"],
            player_b.attrs["history_cache_key"],
        )

    def test_active_player_selection_collapses_audited_aliases(self):
        history = pd.DataFrame([
            {"winner_name": "Taylor Harry Fritz", "loser_name": "Opponent", "tourney_date": 20261101},
            {"winner_name": "Other", "loser_name": "Taylor Fritz", "tourney_date": 20261102},
        ])
        players = catalog.select_active_players(
            history,
            cutoff=pd.Timestamp("2026-11-23T12:00:00Z").to_pydatetime(),
        )
        self.assertEqual(players.count("Taylor Fritz"), 1)

    def test_batch_reuses_history_and_builds_searchable_html(self):
        history = pd.DataFrame([
            {
                "winner_name": "Player A", "loser_name": "Player B",
                "tourney_date": 20261101, "winner_rank": 15, "loser_rank": 80,
            },
        ])

        received_history_sizes = []

        def profile(_history, player, tour, **kwargs):
            received_history_sizes.append(len(_history))
            return {
                "schema_version": 2,
                "generated_at_utc": kwargs["generated_at_utc"],
                "player": {"name": player, "tour": tour, "current_rank": 15},
                "overall_sample": {
                    "matches": 1, "status": "VERY_LOW", "label": "Amostra muito baixa",
                },
                "alerts": [{"severity": "CRITICAL"}],
                "metrics": [{
                    "metric_id": "recent", "label": "Forma recente", "family": "recent_form",
                    "value": 1.0, "unit": "win_rate", "sample_size": 1,
                    "sample_assessment": {"label": "Amostra muito baixa"},
                    "source": "test", "model_role": "DESCRIPTIVE_ONLY", "context": {"wins": 1, "losses": 0},
                }, {
                    "metric_id": "ranking_by_year", "label": "Ranking anual", "family": "structural_strength",
                    "value": [{"year": 2025, "typical_rank": 30}, {"year": 2026, "typical_rank": 15}],
                    "unit": "ranking_series", "sample_size": 2,
                    "sample_assessment": {"label": "Amostra muito baixa"},
                    "source": "test", "model_role": "DESCRIPTIVE_ONLY", "context": {},
                }],
            }

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(catalog.fetch_data, "get_history", return_value=history) as get_history, \
             patch.object(catalog.fetch_data, "get_historical_odds_history", return_value=pd.DataFrame()), \
             patch.object(catalog, "build_player_profile_v2_record", side_effect=profile):
            root = Path(directory)
            summary = catalog.generate_catalog(
                tours=("atp",), output_root=root / "data", docs_root=root / "docs",
                generated_at_utc="2026-11-23T12:00:00+00:00",
            )

            index = (root / "docs" / "index.html").read_text(encoding="utf-8")
            detail = (root / "docs" / "atp" / "player-a.html").read_text(encoding="utf-8")
            payload = json.loads((root / "data" / "index.json").read_text(encoding="utf-8"))

        self.assertEqual(summary["generated"]["atp"], 2)
        self.assertEqual(get_history.call_count, 1)
        self.assertEqual(received_history_sizes, [1, 1])
        self.assertEqual(len(payload["players"]), 2)
        self.assertIn('id="search"', index)
        self.assertIn("Amostra inferior a 20 jogos", detail)
        self.assertIn("Forma recente", detail)
        self.assertIn("Evolução do ranking típico", detail)
        self.assertIn('class="bar"', detail)


if __name__ == "__main__":
    unittest.main()
