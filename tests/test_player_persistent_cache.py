"""Testes offline da integração da cache persistente de jogador."""

from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from src import fetch_data
from src.cache_store import JsonCacheStore


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


class PlayerPersistentCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        self.original_store = fetch_data._PLAYER_CACHE_STORE
        self.original_key = fetch_data.RAPIDAPI_KEY
        fetch_data._PLAYER_CACHE_STORE = JsonCacheStore(self.tmp.name)
        fetch_data._CAREER_STATS_CACHE.clear()
        fetch_data._PERF_BREAKDOWN_CACHE.clear()
        fetch_data._RECENT_MATCHES_CACHE.clear()
        fetch_data._PROFILE_CACHE.clear()

    def tearDown(self) -> None:
        fetch_data._PLAYER_CACHE_STORE = self.original_store
        fetch_data.RAPIDAPI_KEY = self.original_key
        fetch_data._CAREER_STATS_CACHE.clear()
        fetch_data._PERF_BREAKDOWN_CACHE.clear()
        fetch_data._RECENT_MATCHES_CACHE.clear()
        fetch_data._PROFILE_CACHE.clear()

    def test_player_hand_prefers_id_and_persists_by_name(self) -> None:
        fetch_data.RAPIDAPI_KEY = "offline-test"
        profile = {"data": {"information": {"plays": "Right-handed"}}}
        with patch.object(fetch_data, "fetch_player_profile_by_id", return_value=profile) as by_id, \
             patch.object(fetch_data, "fetch_player_profile") as by_name:
            first = fetch_data.fetch_player_hand("wta", 123, "Example Player")
        self.assertEqual(first, "R")
        by_id.assert_called_once_with("wta", 123)
        by_name.assert_not_called()

        fetch_data.RAPIDAPI_KEY = ""
        with patch.object(fetch_data, "fetch_player_profile_by_id") as blocked:
            second = fetch_data.fetch_player_hand("wta", 123, "Example Player")
        self.assertEqual(second, "R")
        blocked.assert_not_called()

    def test_career_stats_persists_and_is_reused_without_api_key(self) -> None:
        payload = {"data": {"playerStats": {"statMatchesPlayed": 42}}}
        fetch_data.RAPIDAPI_KEY = "offline-test"

        with patch.object(
            fetch_data,
            "_rapidapi_get",
            return_value=FakeResponse(payload),
        ) as request:
            first = fetch_data.fetch_player_career_stats("atp", 123)

        self.assertEqual(payload["data"], first)
        self.assertEqual(1, request.call_count)

        fetch_data._CAREER_STATS_CACHE.clear()
        fetch_data.RAPIDAPI_KEY = ""

        with patch.object(fetch_data, "_rapidapi_get") as blocked_request:
            second = fetch_data.fetch_player_career_stats("atp", 123)

        self.assertEqual(first, second)
        blocked_request.assert_not_called()

    def test_recent_matches_reads_persistent_cache_before_api_guard(self) -> None:
        expected = [{"id": 7, "player1Id": 123, "player2Id": 456}]
        path = fetch_data._player_cache_path("wta", 123)
        fetch_data._PLAYER_CACHE_STORE.set_entry(
            path,
            "recent_matches",
            expected,
            metadata={"tour": "wta", "player_id": 123},
        )
        fetch_data.RAPIDAPI_KEY = ""

        with patch.object(fetch_data, "_rapidapi_get") as blocked_request:
            actual = fetch_data.fetch_player_recent_matches("wta", 123)

        self.assertEqual(expected, actual)
        blocked_request.assert_not_called()

    def test_perf_breakdown_persists_aggregated_result(self) -> None:
        payload = {
            "data": {
                "2026": {
                    "rank": {
                        "top10": {"aw": 2, "al": 1},
                    }
                }
            }
        }
        fetch_data.RAPIDAPI_KEY = "offline-test"

        with patch.object(
            fetch_data,
            "_rapidapi_get",
            return_value=FakeResponse(payload),
        ) as request:
            first = fetch_data.fetch_player_perf_breakdown("atp", 321)

        self.assertEqual(
            {
                "vs_rank_level": {
                    "top10": {
                        "wins": 2,
                        "losses": 1,
                        "matches": 3,
                        "win_pct": 66.7,
                    }
                }
            },
            first,
        )
        self.assertEqual(1, request.call_count)

        fetch_data._PERF_BREAKDOWN_CACHE.clear()
        fetch_data.RAPIDAPI_KEY = ""

        with patch.object(fetch_data, "_rapidapi_get") as blocked_request:
            second = fetch_data.fetch_player_perf_breakdown("atp", 321)

        self.assertEqual(first, second)
        blocked_request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
