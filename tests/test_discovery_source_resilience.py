"""Regressões do CHANGE-054 para descoberta factual ATP/WTA resiliente."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import Mock, patch

from src import config, fetch_data, market_integrity, pricing


class DiscoverySourceResilienceTests(unittest.TestCase):
    def setUp(self):
        self.original_key = fetch_data.RAPIDAPI_KEY
        self.original_events = fetch_data._ALL_UPCOMING_EVENTS_CACHE
        self.original_fixtures = fetch_data._fixtures_cache
        self.original_fixtures_dirty = fetch_data._fixtures_cache_dirty
        self.original_tournaments = fetch_data._tournament_cache
        self.original_tournaments_dirty = fetch_data._tournament_cache_dirty
        fetch_data.RAPIDAPI_KEY = "offline-test"
        fetch_data._ALL_UPCOMING_EVENTS_CACHE = None
        fetch_data._fixtures_cache = {}
        fetch_data._fixtures_cache_dirty = False
        fetch_data._tournament_cache = {}
        fetch_data._tournament_cache_dirty = False
        fetch_data._UPCOMING_DISCOVERY_FAILURES.clear()
        fetch_data._reset_discovery_diagnostics()

    def tearDown(self):
        fetch_data.RAPIDAPI_KEY = self.original_key
        fetch_data._ALL_UPCOMING_EVENTS_CACHE = self.original_events
        fetch_data._fixtures_cache = self.original_fixtures
        fetch_data._fixtures_cache_dirty = self.original_fixtures_dirty
        fetch_data._tournament_cache = self.original_tournaments
        fetch_data._tournament_cache_dirty = self.original_tournaments_dirty
        fetch_data._UPCOMING_DISCOVERY_FAILURES.clear()
        fetch_data._reset_discovery_diagnostics()

    @staticmethod
    def _fixture(match_id, tournament_id, tour="atp"):
        return {
            "id": match_id,
            "date": "2026-09-27T12:00:00+00:00",
            "tournamentId": tournament_id,
            "_tour": tour,
            "player1": {"name": "Alpha"},
            "player2": {"name": "Beta"},
        }

    @staticmethod
    def _mark_upcoming_failure(reason="HTTP_403"):
        for tour in ("atp", "wta"):
            fetch_data._record_discovery_source(
                f"upcoming_{tour}",
                fetch_data.DISCOVERY_SOURCE_UNAVAILABLE,
                reason_code=reason,
                http_status=int(reason.removeprefix("HTTP_"))
                if reason.startswith("HTTP_") else None,
            )
        return []

    @staticmethod
    def _mark_upcoming_empty():
        for tour in ("atp", "wta"):
            fetch_data._record_discovery_source(
                f"upcoming_{tour}", fetch_data.DISCOVERY_SUCCESS_EMPTY,
            )
        return []

    def test_upcoming_success_remains_normal_source_and_does_not_call_fallback(self):
        events = [{"type": "atp", "tournament": {"id": 10}}]
        fixture = self._fixture(1, 10)

        def upcoming(_tour):
            fetch_data._record_discovery_source(
                "upcoming_atp", fetch_data.DISCOVERY_SUCCESS_WITH_MATCHES,
                matches=1,
            )
            fetch_data._record_discovery_source(
                "upcoming_wta", fetch_data.DISCOVERY_SUCCESS_EMPTY,
            )
            return events

        with patch.object(fetch_data, "_fetch_extend_upcoming_events", side_effect=upcoming), \
                patch.object(fetch_data, "_fetch_core_date_fixture_window") as fallback, \
                patch.object(
                    fetch_data, "get_tournament_info",
                    return_value={"tier": "ATP 250", "name": "Allowed"},
                ), \
                patch.object(fetch_data, "fetch_tournament_fixtures", return_value=[fixture]):
            actual = fetch_data.fetch_resilient_discovery_fixtures()

        self.assertEqual(actual, [fixture])
        fallback.assert_not_called()
        diagnostics = fetch_data.get_discovery_diagnostics()
        self.assertEqual(diagnostics["discovery_selected_source"], "upcoming_discovery")
        self.assertEqual(
            diagnostics["discovery_status"],
            fetch_data.DISCOVERY_SUCCESS_WITH_MATCHES,
        )

    def test_upcoming_valid_empty_is_no_matches_not_source_failure(self):
        with patch.object(
            fetch_data, "_fetch_extend_upcoming_events",
            side_effect=lambda _tour: self._mark_upcoming_empty(),
        ), patch.object(fetch_data, "_fetch_core_date_fixture_window") as fallback:
            actual = fetch_data.fetch_resilient_discovery_fixtures()

        self.assertEqual(actual, [])
        fallback.assert_not_called()
        self.assertFalse(fetch_data.discovery_unavailable())
        self.assertEqual(
            fetch_data.get_discovery_diagnostics()["discovery_status"],
            fetch_data.DISCOVERY_SUCCESS_EMPTY,
        )

    def test_403_400_and_timeout_recover_through_core_fixtures(self):
        fixture = self._fixture(1, 10)
        core_status = {
            "status": fetch_data.DISCOVERY_SUCCESS_WITH_MATCHES,
            "matches": 1,
            "requests": 8,
            "successful_requests": 8,
            "unavailable_requests": 0,
            "partial": False,
        }
        for reason in ("HTTP_403", "HTTP_400", "TIMEOUT"):
            with self.subTest(reason=reason), patch.object(
                fetch_data, "_fetch_extend_upcoming_events",
                side_effect=lambda _tour, code=reason: self._mark_upcoming_failure(code),
            ), patch.object(
                fetch_data, "_fetch_core_date_fixture_window",
                return_value=([fixture], core_status),
            ), patch.object(
                fetch_data, "get_tournament_info",
                return_value={"tier": "ATP 250", "name": "Allowed"},
            ):
                actual = fetch_data.fetch_resilient_discovery_fixtures()
            self.assertEqual(actual, [fixture])
            self.assertEqual(
                fetch_data.get_discovery_diagnostics()["discovery_selected_source"],
                "core_date_fixtures",
            )
            self.assertFalse(fetch_data.discovery_unavailable())

    def test_real_upcoming_error_paths_keep_typed_http_statuses(self):
        def http_error(status):
            response = Mock(status_code=status)
            error = fetch_data.requests.HTTPError(f"{status} Client Error")
            error.response = response
            response.raise_for_status.side_effect = error
            return response

        with patch.object(
            fetch_data, "_rapidapi_get",
            side_effect=[http_error(403), http_error(403), http_error(400), http_error(400)],
        ):
            self.assertEqual(fetch_data._fetch_extend_upcoming_events("all"), [])

        sources = fetch_data.get_discovery_diagnostics()["discovery_sources"]
        self.assertEqual(sources["upcoming_atp"]["http_status"], 403)
        self.assertEqual(sources["upcoming_wta"]["http_status"], 403)
        self.assertEqual(sources["upcoming_legacy_all"]["http_status"], 400)
        self.assertTrue(all(
            record["status"] == fetch_data.DISCOVERY_SOURCE_UNAVAILABLE
            for record in sources.values()
        ))

    def test_structurally_invalid_upcoming_response_is_unavailable_not_empty(self):
        malformed = [Mock(status_code=200) for _ in range(3)]
        for response in malformed:
            response.json.return_value = {"unexpected": []}
        with patch.object(fetch_data, "_rapidapi_get", side_effect=malformed):
            self.assertEqual(fetch_data._fetch_extend_upcoming_events("all"), [])
        sources = fetch_data.get_discovery_diagnostics()["discovery_sources"]
        self.assertEqual(sources["upcoming_atp"]["reason_code"], "INVALID_RESPONSE")
        self.assertEqual(sources["upcoming_wta"]["reason_code"], "INVALID_RESPONSE")
        self.assertEqual(
            sources["upcoming_legacy_all"]["reason_code"], "INVALID_RESPONSE"
        )

    def test_upcoming_failure_plus_valid_core_empty_means_no_eligible_matches(self):
        core_status = {
            "status": fetch_data.DISCOVERY_SUCCESS_EMPTY,
            "matches": 0,
            "requests": 8,
            "successful_requests": 8,
            "unavailable_requests": 0,
            "partial": False,
        }
        with patch.object(
            fetch_data, "_fetch_extend_upcoming_events",
            side_effect=lambda _tour: self._mark_upcoming_failure(),
        ), patch.object(
            fetch_data, "_fetch_core_date_fixture_window",
            return_value=([], core_status),
        ):
            self.assertEqual(fetch_data.fetch_resilient_discovery_fixtures(), [])

        self.assertFalse(fetch_data.discovery_unavailable())
        self.assertEqual(
            fetch_data.get_discovery_diagnostics()["discovery_selected_source"],
            "core_date_fixtures",
        )

    def test_all_factual_sources_unavailable_raises_discovery_state(self):
        core_status = {
            "status": fetch_data.DISCOVERY_SOURCE_UNAVAILABLE,
            "matches": 0,
            "requests": 8,
            "successful_requests": 0,
            "unavailable_requests": 8,
            "partial": True,
            "reason_codes": ["HTTP_500"],
        }
        with patch.object(
            fetch_data, "_fetch_extend_upcoming_events",
            side_effect=lambda _tour: self._mark_upcoming_failure(),
        ), patch.object(
            fetch_data, "_fetch_core_date_fixture_window",
            return_value=([], core_status),
        ):
            self.assertEqual(fetch_data.fetch_resilient_discovery_fixtures(), [])
        self.assertTrue(fetch_data.discovery_unavailable())

    def test_core_window_covers_every_atp_wta_date_touched_by_72_hours(self):
        now = datetime(2026, 9, 26, 10, tzinfo=timezone.utc)
        seen = []

        def fetch(day, tour, *, return_status=False):
            self.assertTrue(return_status)
            seen.append((day.strftime("%Y-%m-%d"), tour))
            return [], {
                "status": fetch_data.DISCOVERY_SUCCESS_EMPTY,
                "matches": 0,
                "cache": "miss",
            }

        with patch.object(fetch_data, "fetch_date_fixtures", side_effect=fetch):
            matches, status = fetch_data._fetch_core_date_fixture_window(now=now)

        self.assertEqual(matches, [])
        self.assertEqual(status["status"], fetch_data.DISCOVERY_SUCCESS_EMPTY)
        self.assertEqual(status["requests"], 8)
        self.assertEqual(
            seen,
            [
                (date, tour)
                for date in ("2026-09-26", "2026-09-27", "2026-09-28", "2026-09-29")
                for tour in ("atp", "wta")
            ],
        )

    def test_core_discovers_250_and_challenger125_but_excludes_lower_tiers(self):
        fixtures = [
            self._fixture(1, 101, "atp"),
            self._fixture(2, 102, "wta"),
            self._fixture(3, 103, "atp"),
            self._fixture(4, 104, "atp"),
            self._fixture(5, 105, "wta"),
        ]
        tiers = {
            101: "ATP 250",
            102: "WTA 250",
            103: "Challenger 125",
            104: "Challenger 100",
            105: "ITF",
        }
        core_status = {
            "status": fetch_data.DISCOVERY_SUCCESS_WITH_MATCHES,
            "matches": len(fixtures),
            "requests": 8,
            "successful_requests": 8,
            "unavailable_requests": 0,
            "partial": False,
        }
        with patch.object(
            fetch_data, "_fetch_extend_upcoming_events",
            side_effect=lambda _tour: self._mark_upcoming_failure(),
        ), patch.object(
            fetch_data, "_fetch_core_date_fixture_window",
            return_value=(fixtures, core_status),
        ), patch.object(
            fetch_data, "get_tournament_info",
            side_effect=lambda tournament_id, _tour: {"tier": tiers[tournament_id]},
        ):
            actual = fetch_data.fetch_resilient_discovery_fixtures()

        self.assertEqual([item["id"] for item in actual], [1, 2, 3])
        self.assertIn("Challenger 125", config.ALLOWED_TOURNAMENT_TIERS)

    def test_core_deduplicates_fixture_ids_and_never_fabricates_event_id(self):
        one = self._fixture(1, 10)
        duplicate = deepcopy(one)
        duplicate["date"] = "2026-09-27T13:00:00+00:00"
        unique = self._fixture(2, 10)
        actual = fetch_data._deduplicate_fixture_ids([one, duplicate, unique])
        self.assertEqual([item["id"] for item in actual], [1, 2])
        self.assertTrue(all("eventId" not in item for item in actual))

    def test_failed_date_fetch_does_not_overwrite_previous_cache(self):
        day = datetime(2026, 9, 27, tzinfo=timezone.utc)
        fetch_data._fixtures_cache = {
            "atp:2026-09-27": {
                "fetched_at": (datetime.now(timezone.utc) - timedelta(hours=8)).isoformat(),
                "data": [self._fixture(99, 10)],
            }
        }
        before = deepcopy(fetch_data._fixtures_cache)
        with patch.object(
            fetch_data, "_rapidapi_get",
            side_effect=fetch_data.requests.Timeout("offline timeout"),
        ):
            matches, status = fetch_data.fetch_date_fixtures(
                day, "atp", return_status=True,
            )
        self.assertEqual(matches, [])
        self.assertEqual(status["status"], fetch_data.DISCOVERY_SOURCE_UNAVAILABLE)
        self.assertEqual(fetch_data._fixtures_cache, before)

    def test_valid_empty_date_response_is_cached_as_success_empty(self):
        day = datetime(2026, 9, 27, tzinfo=timezone.utc)
        response = Mock(status_code=200)
        response.json.return_value = {"data": [], "hasNextPage": False}
        with patch.object(fetch_data, "_rapidapi_get", return_value=response) as request:
            first, first_status = fetch_data.fetch_date_fixtures(
                day, "wta", return_status=True,
            )
            second, second_status = fetch_data.fetch_date_fixtures(
                day, "wta", return_status=True,
            )
        self.assertEqual(first, second, [])
        self.assertEqual(first_status["status"], fetch_data.DISCOVERY_SUCCESS_EMPTY)
        self.assertEqual(second_status["cache"], "persistent_hit")
        request.assert_called_once()

    def test_upcoming_observation_cannot_authorize_pricing_contract(self):
        payload = {
            "odds_source": "rapidapi_extend_upcoming",
            "odds_operational_pricing_eligible": False,
            "odds_source_contract_version": market_integrity.ODDS_SOURCE_CONTRACT_VERSION,
            "odds_source_contract_fingerprint": market_integrity.ODDS_SOURCE_CONTRACT_FINGERPRINT,
            "market_odds_decimal": {"Alpha": 2.0, "Beta": 2.0},
        }
        divergence = {
            "indice_evidencia_a": 60,
            "indice_evidencia_b": 40,
            "n_fatores": 2,
            "fatores_status": {},
        }
        self.assertFalse(
            pricing.estimate_market_residual_pricing(payload, divergence)["available"]
        )
        self.assertEqual(
            market_integrity.ODDS_SOURCE_CONTRACT_VERSION,
            "rapidapi-recent-gated-v1",
        )
        self.assertEqual(
            market_integrity.ODDS_SOURCE_CONTRACT_FINGERPRINT,
            "d8679462537d9f461ca7",
        )

    def test_discovery_change_preserves_operational_quotas_and_experiment_gate(self):
        self.assertEqual(config.RAPIDAPI_MAX_CALLS_PER_RUN, 2250)
        self.assertEqual(config.RAPIDAPI_MAX_CALLS_PER_DAY, 4500)
        self.assertEqual(config.RAPIDAPI_OPERATIONAL_RESERVE, 1500)
        self.assertEqual(
            config.EXPERIMENTAL_REPORT_ONLY_TIERS,
            frozenset({"Challenger 125"}),
        )
        self.assertEqual(
            config.EXPERIMENTAL_TIER_PAPER_REASON_CODE,
            "EXPERIMENTAL_TIER_CHALLENGER_125",
        )


if __name__ == "__main__":
    unittest.main()
