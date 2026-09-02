"""Temporal-integrity and universe-isolation tests for historical replay."""

from __future__ import annotations

import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.historical_replay import UNIVERSE, replay_matches
from src.historical_snapshot import (
    H2H_AVAILABLE,
    H2H_DATA_INSUFFICIENT,
    H2H_NONE_OBSERVED_EX_ANTE,
    TemporalLeakageError,
    assert_aggregate_is_ex_ante,
    build_historical_snapshot,
)
from src.historical_warehouse import HistoricalWarehouse
from scripts.historical_replay import _assert_zero_llm


def match(match_id: str, date: str, a: str, b: str, winner: str | None, *, rank_a=10, rank_b=20, precision="event_exact") -> dict:
    return {
        "canonical_match_id": match_id, "source": "fixture", "endpoint": "fixture",
        "provider_match_id": match_id, "provider_timestamp": None,
        "fetched_at_utc": "2026-01-01T00:00:00+00:00", "source_version": "test",
        "payload_hash": match_id.ljust(64, "0")[:64], "raw_cache_key": None,
        "tour": "ATP", "tournament": "Test", "tournament_id": "1",
        "tournament_level": "ATP 500", "surface": "Hard", "event_start_utc": date,
        "date_precision": precision, "player_a_id": a, "player_a_name": a,
        "player_b_id": b, "player_b_name": b, "player_a_rank": rank_a,
        "player_b_rank": rank_b, "round": "R32", "best_of": 3,
        "identity_temporal_class": "EXACT_EX_ANTE",
        "ranking_temporal_class": "RECONSTRUCTED_EX_ANTE" if rank_a is not None and rank_b is not None else "UNAVAILABLE",
        "outcome_winner_id": winner, "outcome_result": "6-4 6-4" if winner else None,
        "outcome_temporal_class": "EX_POST_ONLY",
    }


class HistoricalReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = HistoricalWarehouse(Path(self.temp.name) / "warehouse.sqlite3")
        for row in (
            match("old-a", "2024-01-01T12:00:00+00:00", "A", "C", "A"),
            match("old-b", "2024-02-01T12:00:00+00:00", "B", "C", "C"),
            match("h2h", "2024-03-01T12:00:00+00:00", "A", "B", "A"),
            match("target", "2024-04-01T12:00:00+00:00", "A", "B", "B"),
            match("future", "2024-05-01T12:00:00+00:00", "A", "B", "B"),
        ):
            self.db.upsert_match(row)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_future_game_and_result_do_not_influence_snapshot(self) -> None:
        target = self.db.get_match("target")
        first = build_historical_snapshot(self.db, target, target["event_start_utc"])
        changed = copy.deepcopy(target)
        changed["outcome_winner_id"] = "A"
        changed["outcome_result"] = None
        second = build_historical_snapshot(self.db, changed, changed["event_start_utc"])
        self.assertEqual(first["snapshot_hash"], second["snapshot_hash"])
        h2h = first["feature_values"]["classified"]["h2h"]
        self.assertEqual(h2h["sample_size"], 1)
        self.assertEqual(h2h["status"], H2H_AVAILABLE)
        self.assertNotIn("future", first["raw_source_references"])

    def test_h2h_none_observed_requires_adequate_prehistory_for_both_players(self) -> None:
        warehouse = HistoricalWarehouse(Path(self.temp.name) / "h2h-none.sqlite3")
        for index in range(10):
            warehouse.upsert_match(match(
                f"a-{index}", f"2024-01-{index + 1:02d}T12:00:00+00:00",
                "A", f"AX{index}", "A",
            ))
            warehouse.upsert_match(match(
                f"b-{index}", f"2024-02-{index + 1:02d}T12:00:00+00:00",
                "B", f"BX{index}", "B",
            ))
        warehouse.upsert_match(match("target-none", "2024-04-01T12:00:00+00:00", "A", "B", None))
        snapshot = build_historical_snapshot(warehouse, "target-none", "2024-04-01T12:00:00+00:00")
        h2h = snapshot["feature_values"]["classified"]["h2h"]
        self.assertEqual(h2h["status"], H2H_NONE_OBSERVED_EX_ANTE)
        self.assertFalse(h2h["available"])
        self.assertEqual((h2h["prehistory_matches_a"], h2h["prehistory_matches_b"]), (10, 10))

    def test_h2h_absence_stays_insufficient_when_one_player_lacks_history(self) -> None:
        warehouse = HistoricalWarehouse(Path(self.temp.name) / "h2h-insufficient.sqlite3")
        for index in range(10):
            warehouse.upsert_match(match(
                f"a-{index}", f"2024-01-{index + 1:02d}T12:00:00+00:00",
                "A", f"AX{index}", "A",
            ))
        warehouse.upsert_match(match("target-insufficient", "2024-04-01T12:00:00+00:00", "A", "B", None))
        snapshot = build_historical_snapshot(
            warehouse, "target-insufficient", "2024-04-01T12:00:00+00:00",
        )
        h2h = snapshot["feature_values"]["classified"]["h2h"]
        self.assertEqual(h2h["status"], H2H_DATA_INSUFFICIENT)
        self.assertFalse(h2h["available"])

    def test_current_ranking_is_never_fetched_and_missing_stays_unavailable(self) -> None:
        target = self.db.get_match("target")
        target["player_a_rank"] = target["player_b_rank"] = None
        target["ranking_temporal_class"] = "UNAVAILABLE"
        with patch("src.fetch_data.fetch_official_ranking") as current_ranking:
            snapshot = build_historical_snapshot(self.db, target, target["event_start_utc"])
        current_ranking.assert_not_called()
        self.assertFalse(snapshot["feature_values"]["classified"]["ranking_a"]["available"])

    def test_unsafe_aggregate_is_rejected_and_buffer_preserved(self) -> None:
        with self.assertRaises(TemporalLeakageError):
            assert_aggregate_is_ex_ante(aggregate_through_utc="2024-04-02T00:00:00Z", as_of_utc="2024-04-01T00:00:00Z")
        target = self.db.get_match("target")
        target["date_precision"] = "tournament_start"
        snapshot = build_historical_snapshot(self.db, target, target["event_start_utc"])
        self.assertEqual(snapshot["temporal_rejections"]["safety_buffer_days"], 21)

    def test_replay_is_not_paper_and_makes_no_llm_call(self) -> None:
        paper = Path(self.temp.name) / "paper_trades.json"
        paper.write_text("sentinel", encoding="utf-8")
        operational_snapshot = Path(self.temp.name) / "operational_snapshots.json"
        operational_snapshot.write_text("sentinel", encoding="utf-8")
        with patch("src.analyze.analyze_match") as anthropic_path, \
             patch("src.fetch_data._rapidapi_get") as rapidapi, \
             patch("src.fetch_data.requests.get") as generic_network:
            result = replay_matches(self.db, ["target"])
        anthropic_path.assert_not_called()
        rapidapi.assert_not_called()
        generic_network.assert_not_called()
        self.assertEqual(result["metrics"]["universe"], UNIVERSE)
        self.assertEqual(result["metrics"]["h2h_status_counts"], {H2H_AVAILABLE: 1})
        self.assertEqual(paper.read_text(encoding="utf-8"), "sentinel")
        self.assertEqual(operational_snapshot.read_text(encoding="utf-8"), "sentinel")
        with self.db.connect() as connection:
            row = connection.execute("SELECT universe FROM replay_outputs").fetchone()
        self.assertEqual(row["universe"], "BACKTEST_RECONSTRUCTED")

    def test_historical_cli_fails_closed_if_paid_llm_is_enabled(self) -> None:
        with patch.dict(os.environ, {"LLM_MODE": "anthropic", "LLM_POLICY": "always", "ALLOW_PAID_LLM": "1"}, clear=False):
            with self.assertRaises(RuntimeError):
                _assert_zero_llm()
        with patch.dict(os.environ, {"LLM_MODE": "disabled", "LLM_POLICY": "never", "ALLOW_PAID_LLM": "0"}, clear=False):
            _assert_zero_llm()


if __name__ == "__main__":
    unittest.main()
