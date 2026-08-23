import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from src import fetch_data


class WeatherResilienceTests(unittest.TestCase):
    def setUp(self):
        fetch_data._GEOCODE_CACHE.clear()
        fetch_data._WEATHER_CACHE.clear()

    def tearDown(self):
        fetch_data._GEOCODE_CACHE.clear()
        fetch_data._WEATHER_CACHE.clear()

    def test_geocode_success_is_cached(self):
        response = Mock()
        response.json.return_value = {"results": [{"latitude": 38.72, "longitude": -9.14}]}
        with patch.object(fetch_data.requests, "get", return_value=response) as request:
            first = fetch_data.geocode_location("Lisboa")
            second = fetch_data.geocode_location("Lisboa")

        self.assertEqual(first, {"lat": 38.72, "lon": -9.14})
        self.assertEqual(second, first)
        request.assert_called_once()

    def test_geocode_malformed_response_degrades_without_caching_failure(self):
        response = Mock()
        response.json.return_value = {"results": [{}]}
        with patch.object(fetch_data.requests, "get", return_value=response) as request:
            self.assertIsNone(fetch_data.geocode_location("Broken"))
            self.assertIsNone(fetch_data.geocode_location("Broken"))

        self.assertEqual(request.call_count, 2)

    def test_weather_retries_malformed_data_and_valid_result_is_cached(self):
        invalid = Mock()
        invalid.json.return_value = {"daily": {"time": ["2026-08-15"], "temperature_2m_max": []}}
        valid = Mock()
        valid.json.return_value = {
            "daily": {
                "time": ["2026-08-15"],
                "temperature_2m_max": [30],
                "temperature_2m_min": [18],
                "precipitation_sum": [0],
                "windspeed_10m_max": [12],
            }
        }
        match_date = datetime(2026, 8, 15, tzinfo=timezone.utc)
        with patch.object(fetch_data.requests, "get", side_effect=[invalid, valid]) as request:
            first = fetch_data.get_weather_forecast(38.72, -9.14, match_date)
            second = fetch_data.get_weather_forecast(38.72, -9.14, match_date)

        self.assertEqual(first["temp_max_c"], 30)
        self.assertEqual(second, first)
        self.assertEqual(request.call_count, 2)


class FixtureResilienceTests(unittest.TestCase):
    def setUp(self):
        self.original_key = fetch_data.RAPIDAPI_KEY
        self.original_fixtures = fetch_data._fixtures_cache
        self.original_dirty = fetch_data._fixtures_cache_dirty
        self.original_tournaments = fetch_data._tournament_cache
        self.original_tournament_dirty = fetch_data._tournament_cache_dirty
        fetch_data._fixtures_cache = {}
        fetch_data._fixtures_cache_dirty = False
        fetch_data._tournament_cache = {}
        fetch_data._tournament_cache_dirty = False

    def tearDown(self):
        fetch_data.RAPIDAPI_KEY = self.original_key
        fetch_data._fixtures_cache = self.original_fixtures
        fetch_data._fixtures_cache_dirty = self.original_dirty
        fetch_data._tournament_cache = self.original_tournaments
        fetch_data._tournament_cache_dirty = self.original_tournament_dirty

    def test_corrupt_cache_entry_is_ignored_instead_of_crashing(self):
        fetch_data.RAPIDAPI_KEY = ""
        fetch_data._fixtures_cache = {
            "atp:2026-08-15": {"fetched_at": "not-a-date", "data": [{"id": 1}]},
            "torneio:99": {"fetched_at": None, "data": [{"id": 2}]},
        }

        self.assertEqual(fetch_data.fetch_date_fixtures(datetime(2026, 8, 15), "atp"), [])
        self.assertEqual(fetch_data.fetch_tournament_fixtures(99, "atp"), [])

    def test_tournament_fixtures_filter_doubles_missing_dates_and_paginate(self):
        fetch_data.RAPIDAPI_KEY = "offline-test"
        first = Mock()
        first.json.return_value = {
            "data": [
                {"id": 1, "date": "2026-08-15", "player1": {"name": "A"}, "player2": {"name": "B"}},
                {"id": 2, "date": "2026-08-15", "player1": {"name": "A/C"}, "player2": {"name": "B/D"}},
                {"id": 3, "date": None, "player1": {"name": "A"}, "player2": {"name": "B"}},
            ],
            "hasNextPage": True,
        }
        second = Mock()
        second.json.return_value = {
            "data": [{"id": 4, "date": "2026-08-16", "player1": {"name": "C"}, "player2": {"name": "D"}}],
            "hasNextPage": False,
        }
        with patch.object(fetch_data, "_rapidapi_get", side_effect=[first, second]) as request:
            actual = fetch_data.fetch_tournament_fixtures(99, "atp")

        self.assertEqual([match["id"] for match in actual], [1, 4])
        self.assertTrue(all(match["_tour"] == "atp" for match in actual))
        self.assertEqual(request.call_count, 2)
        self.assertTrue(fetch_data._fixtures_cache_dirty)

    def test_malformed_fixture_payload_returns_empty_list(self):
        fetch_data.RAPIDAPI_KEY = "offline-test"
        response = Mock()
        response.json.return_value = ["unexpected"]
        with patch.object(fetch_data, "_rapidapi_get", return_value=response):
            self.assertEqual(fetch_data.fetch_tournament_fixtures(99, "atp"), [])

    def test_tournament_info_rejects_malformed_payload(self):
        fetch_data.RAPIDAPI_KEY = "offline-test"
        response = Mock()
        response.json.return_value = {"data": []}
        with patch.object(fetch_data, "_rapidapi_get", return_value=response):
            self.assertIsNone(fetch_data.get_tournament_info(99, "atp"))

    def test_discovery_falls_back_or_keeps_only_allowed_tiers(self):
        with patch.object(fetch_data, "_fetch_extend_upcoming_events", return_value=[]):
            fallback = fetch_data.discover_tracked_tournaments()
        self.assertEqual(fallback, dict(fetch_data.TRACKED_TOURNAMENT_IDS))

        events = [
            {"type": "atp", "tournament": {"id": 10}},
            {"type": "atp", "tournament": {"id": 10}},
            {"type": "wta", "tournament": {"id": 20}},
            {"type": "itf", "tournament": {"id": 30}},
        ]
        info = {
            10: {"tier": "ATP 500"},
            20: {"tier": "WTA 250"},
        }
        with patch.object(fetch_data, "_fetch_extend_upcoming_events", return_value=events), \
             patch.object(fetch_data, "get_tournament_info", side_effect=lambda tournament_id, _tour: info[tournament_id]):
            actual = fetch_data.discover_tracked_tournaments()

        self.assertEqual(actual, {10: "atp"})


class PlayerNameResolutionTests(unittest.TestCase):
    """Regressão para nomes compostos longos (ex: WTA) que falhavam a
    resolução por ranking e deixavam todos os dados ricos sem dados."""

    def _ranking(self):
        return {
            "camila osorio": {"player_id": 111},
            "ann li": {"player_id": 222},
            "maria sakkari": {"player_id": 444},
        }

    def test_long_composite_name_resolves_by_token_overlap(self):
        with patch.object(fetch_data, "fetch_official_ranking", return_value=self._ranking()):
            # o nome longo da fixture deve casar com "Camila Osorio"
            got = fetch_data.get_player_id_from_ranking("wta", "Maria Camila Osorio Serrano")
        self.assertEqual(got, 111)

    def test_token_overlap_does_not_create_false_positive(self):
        with patch.object(fetch_data, "fetch_official_ranking", return_value=self._ranking()):
            # "Maria Sakkari" não deve casar com "Maria Camila" por partilhar só "Maria"
            got = fetch_data.get_player_id_from_ranking("wta", "Maria Sakkari")
        self.assertEqual(got, 444)

    def test_unknown_name_still_returns_none(self):
        with patch.object(fetch_data, "fetch_official_ranking", return_value=self._ranking()):
            got = fetch_data.get_player_id_from_ranking("wta", "Jogador Inexistente")
        self.assertIsNone(got)


if __name__ == "__main__":
    unittest.main()
