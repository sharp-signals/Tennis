"""Coverage-enrichment, migration and anti-leakage tests for CHANGE-2026-09-02-023."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from src.historical_enrichment import enrich_from_tennis_data, enrich_opponent_history
from src.historical_acquisition import HistoricalAcquirer, SOURCE, SOURCE_VERSION
from src.historical_replay import replay_matches
from src.historical_snapshot import build_historical_snapshot
from src.historical_warehouse import HistoricalWarehouse, make_cache_key
from scripts.historical_coverage_enrichment import MAX_EXPERIMENT_CALLS


def match(match_id: str, date: str, a: str, b: str, *, surface=None, rank_a=None, rank_b=None, winner=None, tour="ATP"):
    return {
        "canonical_match_id": match_id, "source": "rapidapi", "endpoint": "fixture",
        "provider_match_id": match_id, "provider_timestamp": None,
        "fetched_at_utc": "2026-01-01T00:00:00+00:00", "source_version": "test",
        "payload_hash": match_id.ljust(64, "0")[:64], "raw_cache_key": None,
        "tour": tour, "tournament": None, "tournament_id": None,
        "tournament_level": None, "surface": surface, "event_start_utc": date,
        "date_precision": "event_exact", "player_a_id": a, "player_a_name": a,
        "player_b_id": b, "player_b_name": b, "player_a_rank": rank_a,
        "player_b_rank": rank_b, "round": None, "best_of": 3,
        "identity_temporal_class": "EXACT_EX_ANTE",
        "ranking_temporal_class": "RECONSTRUCTED_EX_ANTE" if rank_a is not None or rank_b is not None else "UNAVAILABLE",
        "outcome_winner_id": winner, "outcome_result": "6-4 6-4" if winner else None,
        "outcome_temporal_class": "EX_POST_ONLY",
    }


class HistoricalEnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "warehouse.sqlite3"
        self.db = HistoricalWarehouse(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_experiment_call_cap_is_150(self):
        self.assertEqual(MAX_EXPERIMENT_CALLS, 150)

    def enrichment(self, match_id, field, value, key="row-1"):
        return {
            "match_id": match_id, "field_name": field, "value": value,
            "source": "tennis-data.co.uk", "source_record_key": key,
            "source_date": "2026-01-02", "temporal_class": "RECONSTRUCTED_EX_ANTE",
            "match_method": "exact_pair_exact_date", "match_confidence": "deterministic_unique",
        }

    def test_v1_to_v2_migration_is_additive_and_preserves_matches(self):
        self.db.upsert_match(match("target", "2026-01-02T12:00:00+00:00", "Alpha One", "Beta Two"))
        with self.db.connect() as connection:
            connection.execute("DROP TABLE match_enrichments")
            connection.execute("UPDATE warehouse_meta SET value='1' WHERE key='schema_version'")
        migrated = HistoricalWarehouse(self.path)
        migrated = HistoricalWarehouse(self.path)  # idempotent second open
        self.assertIsNotNone(migrated.get_match("target"))
        self.assertEqual(migrated.table_count("match_enrichments"), 0)
        with migrated.connect() as connection:
            version = connection.execute("SELECT value FROM warehouse_meta WHERE key='schema_version'").fetchone()[0]
        self.assertEqual(version, "2")

    def test_v1_raw_cache_is_reused_after_schema_migration(self):
        params = {"tour": "atp", "player_id": 1, "page": 1}
        legacy_key = make_cache_key(
            SOURCE, "getPlayerPastMatches", params,
            source_version=SOURCE_VERSION, schema_version=1,
        )
        self.db.put_raw_response(
            cache_key=legacy_key, source=SOURCE, endpoint="getPlayerPastMatches",
            params=params, status=200, payload={"data": [{"id": 1}]},
            source_version=SOURCE_VERSION,
        )
        acquirer = HistoricalAcquirer(self.db)
        with patch("src.historical_acquisition.fetch_data._rapidapi_get") as network:
            payload, key, cache_hit = acquirer.fetch_json(
                "getPlayerPastMatches", "https://example.invalid", params,
            )
        network.assert_not_called()
        self.assertTrue(cache_hit)
        self.assertEqual(key, legacy_key)
        self.assertEqual(payload["data"][0]["id"], 1)

    def test_original_value_has_precedence_and_conflict_is_visible(self):
        self.db.upsert_match(match("target", "2026-01-02T12:00:00+00:00", "Alpha One", "Beta Two", surface="Hard"))
        self.db.add_match_enrichment(self.enrichment("target", "surface", "Clay"))
        effective = self.db.get_effective_match("target")
        self.assertEqual(effective["surface"], "Hard")
        self.assertTrue(self.db.list_match_enrichments("target")[0]["conflict"])

    def test_enrichment_is_idempotent_and_fills_only_missing_value(self):
        self.db.upsert_match(match("target", "2026-01-02T12:00:00+00:00", "Alpha One", "Beta Two"))
        item = self.enrichment("target", "player_a_rank", 12)
        self.assertTrue(self.db.add_match_enrichment(item))
        self.assertFalse(self.db.add_match_enrichment(item))
        self.assertEqual(self.db.get_effective_match("target")["player_a_rank"], 12)

    def test_pair_date_join_maps_ranks_by_names_not_target_outcome(self):
        self.db.upsert_match(match(
            "target", "2026-01-02T18:00:00+00:00", "Alpha One", "Beta Two", winner="Beta Two",
        ))
        frame = pd.DataFrame([{
            "Date": "2026-01-02", "winner_name": "One A.", "loser_name": "Two B.",
            "winner_rank": 11, "loser_rank": 22, "surface": "Hardcourt",
            "Tournament": "Example Open", "Series": "ATP250", "B365W": 1.8, "B365L": 2.1,
        }])
        with patch("src.historical_enrichment.load_tennis_data_year", return_value=(frame, {"tour": "atp", "year": 2026})):
            report = enrich_from_tennis_data(self.db, cache_dir=Path(self.temp.name) / "cache")
        effective = self.db.get_effective_match("target")
        self.assertEqual((effective["player_a_rank"], effective["player_b_rank"]), (11, 22))
        self.assertEqual(effective["surface"], "Hard")
        self.assertEqual(report["matches_matched"], 1)
        self.assertEqual(self.db.usable_market_quote_count("target"), 0)
        with patch("src.historical_enrichment.load_tennis_data_year", return_value=(frame, {})):
            enrich_from_tennis_data(self.db, cache_dir=Path(self.temp.name) / "cache")
        self.assertEqual(self.db.table_count("market_quotes"), 2)

    def test_ambiguous_date_window_is_rejected(self):
        self.db.upsert_match(match("target", "2026-01-02T18:00:00+00:00", "Alpha One", "Beta Two"))
        frame = pd.DataFrame([
            {"Date": date, "winner_name": "One A.", "loser_name": "Two B.", "winner_rank": 1, "loser_rank": 2}
            for date in ("2026-01-01", "2026-01-03")
        ])
        with patch("src.historical_enrichment.load_tennis_data_year", return_value=(frame, {})):
            report = enrich_from_tennis_data(self.db, cache_dir=Path(self.temp.name) / "cache")
        self.assertEqual(report["matches_ambiguous"], 1)
        self.assertIsNone(self.db.get_effective_match("target")["player_a_rank"])

    def test_unique_one_day_window_is_accepted_but_fuzzy_name_is_not(self):
        self.db.upsert_match(match("target", "2026-01-02T18:00:00+00:00", "Alpha One", "Beta Two"))
        frame = pd.DataFrame([
            {"Date": "2026-01-03", "winner_name": "One A.", "loser_name": "Two B.", "winner_rank": 3, "loser_rank": 4},
            {"Date": "2026-01-02", "winner_name": "Onez A.", "loser_name": "Two B.", "winner_rank": 1, "loser_rank": 2},
        ])
        with patch("src.historical_enrichment.load_tennis_data_year", return_value=(frame, {})):
            report = enrich_from_tennis_data(self.db, cache_dir=Path(self.temp.name) / "cache")
        self.assertEqual(report["match_methods"]["exact_pair_date_window_1d"], 1)
        self.assertEqual(self.db.get_effective_match("target")["player_a_rank"], 3)

    def test_opponent_acquisition_stops_after_ten_strictly_prior_matches(self):
        target = match("target", "2026-01-20T12:00:00+00:00", "1", "2")
        self.db.upsert_match(target)

        def one_page(acquirer, tour, player_id, **_kwargs):
            acquirer.metrics.calls_made += 1
            for index in range(10):
                row = match(
                    f"history-{player_id}-{index}", f"2026-01-{index + 1:02d}T12:00:00+00:00",
                    str(player_id), f"opponent-{player_id}-{index}", winner=str(player_id),
                )
                self.db.upsert_match(row)
            # A future record must not count toward sufficiency.
            self.db.upsert_match(match(
                f"future-{player_id}", "2026-01-21T12:00:00+00:00", str(player_id), "future",
            ))
            return {"pages": [{"page": 1}], "stop_reason": "max_pages", "source_exhausted": False}

        with patch("src.historical_enrichment.HistoricalAcquirer.acquire_player_past_match_pages", new=one_page):
            report = enrich_opponent_history(self.db, [target], max_calls=5)
        self.assertEqual(report["players_sufficient"], 2)
        self.assertEqual(report["acquisition"]["calls_made"], 2)
        self.assertTrue(all(player["prior_matches"] == 10 for player in report["players"]))

    def test_opponent_acquisition_round_robins_tours_and_players(self):
        targets = [
            match("atp-target", "2026-02-01T12:00:00+00:00", "1", "2", tour="ATP"),
            match("wta-target", "2026-02-01T12:00:00+00:00", "3", "4", tour="WTA"),
        ]
        for target in targets:
            self.db.upsert_match(target)
        requests = []

        def one_page(acquirer, tour, player_id, **_kwargs):
            acquirer.metrics.calls_made += 1
            requests.append((tour.upper(), str(player_id)))
            return {"pages": [{"page": 1}], "stop_reason": "max_pages", "source_exhausted": False}

        with patch("src.historical_enrichment.HistoricalAcquirer.acquire_player_past_match_pages", new=one_page):
            report = enrich_opponent_history(self.db, targets, max_calls=4)
        self.assertEqual([tour for tour, _ in requests], ["ATP", "WTA", "ATP", "WTA"])
        self.assertEqual(requests, [("ATP", "1"), ("WTA", "3"), ("ATP", "2"), ("WTA", "4")])
        self.assertEqual(report["calls_by_tour"], {"ATP": 2, "WTA": 2})
        self.assertEqual(report["scheduler"], "tour_then_player_page_round_robin")
        self.assertEqual(report["players_by_tour"]["ATP"]["players_total"], 2)
        self.assertEqual(report["players_by_tour"]["WTA"]["players_total"], 2)

    def test_enriched_surface_enters_only_strictly_prior_history(self):
        self.db.upsert_match(match("past", "2026-01-01T12:00:00+00:00", "Alpha One", "Other Three", winner="Alpha One"))
        self.db.upsert_match(match("target", "2026-01-02T12:00:00+00:00", "Alpha One", "Beta Two"))
        self.db.add_match_enrichment(self.enrichment("past", "surface", "Hard", key="past"))
        self.db.add_match_enrichment(self.enrichment("target", "surface", "Hard", key="target"))
        snapshot = build_historical_snapshot(self.db, "target", "2026-01-02T12:00:00+00:00")
        self.assertEqual(snapshot["feature_values"]["classified"]["surface_a"]["sample_size"], 1)

    def test_replay_deduplicates_before_coverage_denominator(self):
        self.db.upsert_match(match("target", "2026-01-02T12:00:00+00:00", "Alpha One", "Beta Two"))
        result = replay_matches(self.db, ["target", "target"], mode="coverage_enrichment")
        metrics = result["metrics"]
        self.assertEqual(metrics["requested_positions"], 2)
        self.assertEqual(metrics["unique_matches_requested"], 1)
        self.assertEqual(metrics["matches_reconstructed_unique"], 1)
        self.assertEqual(metrics["unique_reconstruction_coverage"], 1.0)
        with self.db.connect() as connection:
            run = connection.execute(
                "SELECT mode,sample_universe FROM replay_runs WHERE replay_run_id=?",
                (result["replay_run_id"],),
            ).fetchone()
        self.assertEqual(run["mode"], "coverage_enrichment")
        self.assertEqual(json.loads(run["sample_universe"])["match_ids"], ["target"])

    def test_pilot_and_default_replay_modes_are_persisted(self):
        self.db.upsert_match(match("target", "2026-01-02T12:00:00+00:00", "Alpha One", "Beta Two"))
        pilot = replay_matches(self.db, ["target"], mode="pilot")
        normal = replay_matches(self.db, ["target"])
        with self.db.connect() as connection:
            modes = {
                row["replay_run_id"]: row["mode"]
                for row in connection.execute("SELECT replay_run_id,mode FROM replay_runs")
            }
        self.assertEqual(modes[pilot["replay_run_id"]], "pilot")
        self.assertEqual(modes[normal["replay_run_id"]], "offline_replay")


if __name__ == "__main__":
    unittest.main()
