import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pandas as pd

from src import fetch_data, main, market_integrity, match_identity_v2


class RankingEvolutionCoverageTests(unittest.TestCase):
    @staticmethod
    def _row(player, opponent, date, points):
        return {
            "winner_name": player,
            "loser_name": opponent,
            "winner_rank_points": points,
            "loser_rank_points": 100,
            "tourney_date": int(date.strftime("%Y%m%d")),
        }

    def test_wider_factual_anchors_preserve_observation_metadata(self):
        reference = datetime(2026, 10, 15, tzinfo=timezone.utc)
        history = pd.DataFrame([
            self._row("Player A", "Opponent 1", reference - timedelta(days=127), 800),
            self._row("Player A", "Opponent 2", reference - timedelta(days=285), 600),
        ])

        actual = fetch_data.compute_ranking_evolution(
            history, "Player A", 1000, reference_date=reference,
        )

        self.assertEqual(actual["points_6m_ago"], 800.0)
        self.assertEqual(actual["points_12m_ago"], 600.0)
        self.assertEqual(actual["change_6m_pct"], 25.0)
        self.assertEqual(actual["change_12m_pct"], 66.7)
        self.assertEqual(actual["observations"]["6m"]["anchor_offset_days"], 55)
        self.assertEqual(actual["observations"]["6m"]["tolerance_days"], 60)
        self.assertEqual(actual["observations"]["12m"]["anchor_offset_days"], 80)
        self.assertEqual(actual["source"], "historical_match_ranking_points")

    def test_future_observations_are_never_used_in_replay(self):
        reference = datetime(2026, 10, 15, tzinfo=timezone.utc)
        history = pd.DataFrame([
            self._row("Player A", "Opponent", reference + timedelta(days=1), 900),
        ])

        actual = fetch_data.compute_ranking_evolution(
            history, "Player A", 1000, reference_date=reference,
        )

        self.assertIsNone(actual)

    def test_observations_outside_both_tolerances_remain_unavailable(self):
        reference = datetime(2026, 10, 15, tzinfo=timezone.utc)
        history = pd.DataFrame([
            self._row("Player A", "Opponent 1", reference - timedelta(days=121), 800),
            self._row("Player A", "Opponent 2", reference - timedelta(days=274), 600),
        ])

        actual = fetch_data.compute_ranking_evolution(
            history, "Player A", 1000, reference_date=reference,
        )

        self.assertIsNone(actual)


class TournamentHistoryIdentityTests(unittest.TestCase):
    @staticmethod
    def _row(name, date, winner="Player A", loser="Opponent"):
        return {
            "tourney_name": name,
            "tourney_date": date,
            "winner_name": winner,
            "loser_name": loser,
        }

    def test_sponsor_and_provider_suffixes_resolve_to_one_event(self):
        history = pd.DataFrame([
            self._row("Shanghai", 20231001),
            self._row("Shanghai Masters", 20241001, loser="Opponent 2"),
            self._row("Road to the Rolex Shanghai Masters", 20240901, loser="Opponent 3"),
        ])

        actual = fetch_data.compute_tournament_record_from_history(
            history,
            "Player A",
            "different-provider-id",
            "Shanghai Rolex Masters - Shanghai",
        )

        self.assertEqual(actual["matches"], 2)
        self.assertEqual(actual["observation_status"], "AVAILABLE")
        self.assertEqual(actual["edicoes"], 2)
        self.assertEqual(actual["canonical_tournament_key"], "shanghai")
        self.assertEqual(
            actual["matched_tournament_names"],
            ["Shanghai", "Shanghai Masters"],
        )
        self.assertEqual(actual["factual_match_basis"], "CANONICAL_TOURNAMENT_NAME_V1")

    def test_challenger_open_and_challenger_labels_share_city_identity(self):
        history = pd.DataFrame([
            self._row("Jinan", 20230901),
            self._row("Jinan Open", 20240901, loser="Opponent 2"),
        ])

        actual = fetch_data.compute_tournament_record_from_history(
            history, "Player A", None, "Jinan Challenger",
        )

        self.assertEqual(actual["matches"], 2)
        self.assertEqual(actual["edicoes"], 2)
        self.assertEqual(actual["canonical_tournament_key"], "jinan")

    def test_special_and_numbered_events_remain_separate(self):
        history = pd.DataFrame([
            self._row("Tokyo", 20231001),
            self._row("Tokyo Olympics", 20210724, loser="Opponent 2"),
            self._row("Nottingham", 20240601, loser="Opponent 3"),
            self._row("Nottingham 2", 20240608, loser="Opponent 4"),
        ])

        tokyo = fetch_data.compute_tournament_record_from_history(
            history, "Player A", None, "Japan Open",
        )
        nottingham = fetch_data.compute_tournament_record_from_history(
            history, "Player A", None, "Nottingham 2 Challenger",
        )

        self.assertEqual(tokyo["matched_tournament_names"], ["Tokyo"])
        self.assertEqual(nottingham["matched_tournament_names"], ["Nottingham 2"])

    def test_us_open_punctuation_does_not_split_the_same_major(self):
        self.assertEqual(
            fetch_data._tournament_history_key("U.S. Open - New York"),
            fetch_data._tournament_history_key("US Open"),
        )

    def test_verified_absence_is_not_reported_as_source_failure(self):
        history = pd.DataFrame([
            self._row("Other Tournament", 20241001),
        ])

        actual = fetch_data.compute_tournament_record_from_history(
            history, "Player A", None, "Shanghai Masters",
        )
        coverage = main._tournament_record_coverage(actual, "local_history")

        self.assertEqual(actual["observation_status"], "NONE_OBSERVED")
        self.assertEqual(actual["matches"], 0)
        self.assertEqual(actual["edicoes"], 0)
        self.assertIsNone(actual["win_pct_ponderado"])
        self.assertEqual(coverage["status"], "NONE_OBSERVED")
        self.assertEqual(coverage["reason"], "no_prior_tournament_record_observed")

    def test_missing_tournament_identity_remains_unavailable(self):
        history = pd.DataFrame([{
            "winner_name": "Player A",
            "loser_name": "Opponent",
            "tourney_date": 20241001,
        }])

        actual = fetch_data.compute_tournament_record_from_history(
            history, "Player A", None, "Shanghai Masters",
        )
        coverage = main._tournament_record_coverage(actual, "local_history")

        self.assertIsNone(actual)
        self.assertEqual(coverage["status"], "UNAVAILABLE")
        self.assertEqual(coverage["reason"], "tournament_record_unavailable")


class CourtPaceEvidenceTests(unittest.TestCase):
    def test_shanghai_rolex_name_resolves_to_the_versioned_cpi_registry(self):
        info = fetch_data.lookup_court_pace("Shanghai Rolex Masters - Shanghai", 2026)

        self.assertIsNotNone(info)
        self.assertEqual(info["tournament_key"], "shanghai")
        self.assertEqual(info["bucket"], "medium_slow")
        self.assertEqual(info["ano_usado"], 2025)
        self.assertFalse(info["ano_exato"])
        self.assertEqual(info["source"], "courtspeed_cpi")

    def test_clay_and_grass_are_explicitly_not_speed_classified(self):
        clay = fetch_data.court_pace_context("Rome Masters", 2026, "Clay")
        grass = fetch_data.court_pace_context("Wimbledon", 2026, "Grass")

        self.assertEqual(clay["status"], "not_applicable")
        self.assertIn("terra batida", clay["motivo_exclusao"])
        self.assertEqual(grass["status"], "not_applicable")
        self.assertIn("relva", grass["motivo_exclusao"])

    def test_hard_speed_form_never_mixes_clay_or_grass_history(self):
        history = pd.DataFrame([
            {"winner_name": "A", "loser_name": "B", "surface": "Hard", "tourney_name": "Shanghai Masters", "tourney_date": 20251001},
            {"winner_name": "A", "loser_name": "C", "surface": "Clay", "tourney_name": "Rome Masters", "tourney_date": 20251001},
        ])

        result = fetch_data.compute_court_speed_form(history, "A", "medium_slow")

        self.assertEqual(result["matches"], 1)
        self.assertEqual(result["wins"], 1)
        self.assertFalse(result["eligible_for_index"])
        self.assertEqual(result["sample_minimum"], 10)

    @staticmethod
    def _event_rows(name, date, ace_total, matches=12):
        rows = []
        first_won = 20 + ace_total / 4
        second_won = 10 + ace_total / 8
        bp_saved = min(5, 1 + ace_total / 5)
        score = "7-6(4) 7-6(5)" if ace_total >= 12 else "6-4 6-4"
        for index in range(matches):
            rows.append({
                "tourney_name": name,
                "tourney_date": date,
                "surface": "Hard",
                "winner_name": f"Winner {name} {index}",
                "loser_name": f"Loser {name} {index}",
                "w_ace": ace_total / 2,
                "l_ace": ace_total / 2,
                "w_svpt": 50,
                "l_svpt": 50,
                "w_1stWon": first_won,
                "l_1stWon": first_won,
                "w_2ndWon": second_won,
                "l_2ndWon": second_won,
                "w_SvGms": 10,
                "l_SvGms": 10,
                "w_bpFaced": 5,
                "l_bpFaced": 5,
                "w_bpSaved": bp_saved,
                "l_bpSaved": bp_saved,
                "score": score,
            })
        return rows

    def test_unclassified_hard_event_uses_only_prior_empirical_events(self):
        rows = []
        for index in range(12):
            rows.extend(self._event_rows(
                f"Reference {index}", 20250101 + index * 100,
                4 + index,
            ))
        rows.extend(self._event_rows("Porto Challenger", 20260101, 22))
        # A future outlier must not change Porto's reference distribution.
        rows.extend(self._event_rows("Future Event", 20260301, 40))
        history = pd.DataFrame(rows)

        profiles = fetch_data.build_empirical_court_speed_profiles(
            history, before=datetime(2026, 2, 1, tzinfo=timezone.utc)
        )
        context = fetch_data.court_pace_context(
            "Porto Challenger - Porto", 2026, "Hard",
            empirical_profiles=profiles,
        )

        self.assertEqual(context["status"], "available")
        self.assertEqual(context["source"], "event_pace_composite_v2")
        self.assertEqual(context["bucket"], "fast")
        self.assertEqual(context["event_matches"], 12)
        self.assertEqual(context["reference_events"], 12)
        self.assertEqual(context["proxy_metric"], "event_match_dynamics_composite")
        self.assertEqual(
            set(context["pace_components"]),
            {
                "hold_rate_pct", "break_rate_pct",
                "service_points_won_pct", "ace_rate_pct",
                "tiebreak_set_rate_pct",
            },
        )
        self.assertNotIn(("main", "future event", 2026), profiles)

    def test_cpi_remains_authoritative_over_empirical_profile(self):
        context = fetch_data.court_pace_context(
            "Shanghai Rolex Masters - Shanghai", 2026, "Hard",
            empirical_profiles={
                ("main", "shanghai", 2026): {
                    "bucket": "fast",
                    "source": "event_pace_composite_v2",
                }
            },
        )

        self.assertEqual(context["source"], "courtspeed_cpi")
        self.assertEqual(context["bucket"], "medium_slow")

    def test_provider_city_suffix_resolves_empirical_event_identity(self):
        context = fetch_data.court_pace_context(
            "Guadalajara Open Akron - Guadalajara", 2026, "Hard",
            empirical_profiles={
                ("main", "guadalajara", 2026): {
                    "bucket": "medium",
                    "source": "event_pace_composite_v2",
                }
            },
        )

        self.assertEqual(context["status"], "available")
        self.assertEqual(context["bucket"], "medium")

    def test_empirical_profile_uses_recent_same_event_before_current_sample(self):
        context = fetch_data.court_pace_context(
            "Guadalajara Open Akron - Guadalajara", 2026, "Hard",
            empirical_profiles={
                ("main", "guadalajara", 2025): {
                    "bucket": "medium_fast",
                    "source": "event_pace_composite_v2",
                    "ano_usado": 2025,
                    "ano_exato": True,
                }
            },
        )

        self.assertEqual(context["status"], "available")
        self.assertEqual(context["bucket"], "medium_fast")
        self.assertEqual(context["ano_usado"], 2025)
        self.assertFalse(context["ano_exato"])

    def test_empirical_profiles_keep_main_and_challenger_baselines_separate(self):
        rows = []
        for scope, prefix, base_aces in (
            ("main", "Main", 4), ("challenger", "Challenger", 18)
        ):
            for index in range(12):
                event_rows = self._event_rows(
                    f"{prefix} {index}", 20250101 + index * 100,
                    base_aces + index,
                )
                for row in event_rows:
                    row["_history_competition_scope"] = scope
                rows.extend(event_rows)
            target_rows = self._event_rows(
                f"{prefix} 12", 20260101, base_aces + 12,
            )
            for row in target_rows:
                row["_history_competition_scope"] = scope
            rows.extend(target_rows)
        history = pd.DataFrame(rows)

        profiles = fetch_data.build_empirical_court_speed_profiles(history)

        self.assertIn(("main", "main 12", 2026), profiles)
        self.assertIn(("challenger", "challenger 12", 2026), profiles)
        self.assertEqual(
            profiles[("main", "main 12", 2026)]["reference_events"], 12
        )
        self.assertEqual(
            profiles[("challenger", "challenger 12", 2026)]["reference_events"],
            12,
        )

    def test_player_speed_form_combines_cpi_and_empirical_classifications(self):
        history = pd.DataFrame([
            {
                "winner_name": "A", "loser_name": "B", "surface": "Hard",
                "tourney_name": "Shanghai Masters", "tourney_date": 20251001,
            },
            {
                "winner_name": "A", "loser_name": "C", "surface": "Hard",
                "tourney_name": "Porto Challenger", "tourney_date": 20251008,
            },
        ])
        profiles = {
            ("main", "porto challenger", 2025): {
                "bucket": "medium_slow",
                "source": "event_pace_composite_v2",
            }
        }

        result = fetch_data.compute_court_speed_form(
            history, "A", "medium_slow", empirical_profiles=profiles,
            before=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

        self.assertEqual(result["matches"], 2)
        self.assertEqual(
            result["classification_sources"],
            ["courtspeed_cpi", "event_pace_composite_v2"],
        )

    def test_player_speed_form_exposes_hold_break_return_and_recovery(self):
        history = pd.DataFrame([{
            "winner_name": "A", "loser_name": "B", "surface": "Hard",
            "tourney_name": "Shanghai Masters", "tourney_date": 20251001,
            "score": "4-6 6-3 6-2",
            "w_svpt": 60, "w_1stWon": 30, "w_2ndWon": 15,
            "w_SvGms": 10, "w_bpFaced": 3, "w_bpSaved": 2,
            "l_svpt": 60, "l_1stWon": 25, "l_2ndWon": 10,
            "l_SvGms": 10, "l_bpFaced": 5, "l_bpSaved": 3,
        }])

        result = fetch_data.compute_court_speed_form(
            history, "A", "medium_slow",
            before=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

        context = result["performance_context"]
        self.assertEqual(context["hold_rate_pct"], 90.0)
        self.assertEqual(context["break_rate_pct"], 20.0)
        self.assertEqual(context["service_points_won_pct"], 75.0)
        self.assertEqual(context["return_points_won_pct"], 41.7)
        self.assertEqual(context["first_set_recovery_pct"], 100.0)
        self.assertEqual(context["first_set_recovery_attempts"], 1)


class MatchInputTests(unittest.TestCase):
    def test_tennisdata_download_discovery_supports_atp_and_wta_versioned_paths(self):
        response = Mock()
        response.text = """
            <a href="token-v2/2026/2026.xlsx">ATP</a>
            <a href='token-v2/2026w/2026.xlsx'>WTA</a>
        """
        response.raise_for_status.return_value = None

        with patch.object(fetch_data, "_TENNISDATA_DOWNLOAD_INDEX", None), \
             patch.object(fetch_data.requests, "get", return_value=response) as request:
            atp_url = fetch_data._tennisdata_couk_download_url("atp", 2026)
            wta_url = fetch_data._tennisdata_couk_download_url("wta", 2026)

        self.assertEqual(
            atp_url,
            "https://www.tennis-data.co.uk/token-v2/2026/2026.xlsx",
        )
        self.assertEqual(
            wta_url,
            "https://www.tennis-data.co.uk/token-v2/2026w/2026.xlsx",
        )
        request.assert_called_once()

    def test_tennisdata_year_uses_discovered_url_and_referer(self):
        response = Mock(content=b"xlsx")
        response.raise_for_status.return_value = None
        normalized = pd.DataFrame([{"winner_name": "A", "loser_name": "B"}])

        with patch.object(
            fetch_data,
            "_tennisdata_couk_download_url",
            return_value="https://www.tennis-data.co.uk/token/2025/2025.xlsx",
        ), patch.object(fetch_data.requests, "get", return_value=response) as request, \
             patch.object(fetch_data.pd, "read_excel", return_value=normalized):
            result = fetch_data._load_tennisdata_couk("atp", 2025)

        self.assertEqual(len(result), 1)
        _args, kwargs = request.call_args
        self.assertEqual(
            kwargs["headers"]["Referer"],
            "https://www.tennis-data.co.uk/data.php",
        )

    def test_atp_historical_odds_fall_back_to_the_persisted_year_cache(self):
        year = datetime.now(timezone.utc).year
        cached = pd.DataFrame([
            {
                "winner_name": "Alex De Minaur",
                "loser_name": "Opponent",
                "B365W": 1.70,
                "B365L": 2.20,
            }
        ])
        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as temp_dir:
            try:
                os.chdir(temp_dir)
                os.makedirs("data/history_cache", exist_ok=True)
                cached.to_csv(
                    f"data/history_cache/atp_tdcouk_{year}.csv", index=False
                )
                with patch.object(
                    fetch_data, "_load_tennisdata_couk", return_value=None
                ):
                    result = fetch_data._load_tennisdata_couk_multi_year("atp", 1)
            finally:
                os.chdir(original_cwd)

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["winner_name"], "Alex De Minaur")

    def test_official_ranking_prefers_fixture_player_id_and_never_invents_low_rank(self):
        ranking = {
            "different spelling": {
                "name": "Different Spelling", "rank": 87, "points": 700, "player_id": 44,
            },
        }
        resolved, source = fetch_data.resolve_official_ranking(
            ranking, "Name That Does Not Match", 44
        )
        self.assertEqual(resolved["rank"], 87)
        self.assertEqual(source, "rapidapi_official_ranking_id")

        unresolved, no_source = fetch_data.resolve_official_ranking(
            ranking, "Unknown Player", 999
        )
        self.assertIsNone(unresolved)
        self.assertIsNone(no_source)

    def test_historical_odds_history_uses_tennis_data_without_replacing_primary_history(self):
        odds_frame = pd.DataFrame([
            {"winner_name": "A", "loser_name": "B", "B365W": 1.70, "B365L": 2.20}
        ])
        with patch.dict(fetch_data._HISTORICAL_ODDS_HISTORY_CACHE, {}, clear=True), \
             patch.object(fetch_data, "_load_tennisdata_couk_multi_year", return_value=odds_frame) as loader:
            result = fetch_data.get_historical_odds_history("atp")
            cached = fetch_data.get_historical_odds_history("atp")

        self.assertIs(result, odds_frame)
        self.assertIs(cached, odds_frame)
        loader.assert_called_once_with("atp", fetch_data.HISTORY_YEARS_TO_LOAD)

    def test_canonical_history_context_uses_first_pre_match_snapshot_and_no_future_result(self):
        earlier = {
            "tour": "atp", "key": "atp:1", "match_id": 1,
            "commence_time_utc": "2026-09-01T12:00:00+00:00",
            "analyzed_at_utc": "2026-09-01T06:30:00+00:00",
            "player_a": {"id": 10, "name": "Player A"}, "player_b": {"id": 11, "name": "Player B"},
            "market_odds_decimal": {"Player A": 1.55, "Player B": 2.50},
            "outcome": {"winner_side": "a"},
        }
        future = {
            **earlier, "key": "atp:2", "match_id": 2,
            "commence_time_utc": "2026-10-01T12:00:00+00:00",
            "market_odds_decimal": {"Player A": 1.55, "Player B": 2.50},
            "outcome": {"winner_side": "b"},
        }
        with patch.object(fetch_data, "_load_canonical_snapshot_odds", return_value=[earlier, future]):
            result = fetch_data.compute_canonical_snapshot_odds_context(
                "atp", "Player A", 1.55, "2026-09-30T12:00:00+00:00",
            )
        self.assertEqual(result["exact_band"], "1.51-1.60")
        self.assertEqual(result["exact"], {"n": 1, "wins": 1, "losses": 0, "win_rate_pct": 100.0})
        self.assertEqual(result["general"]["n"], 1)

    def test_embedded_odds_keep_original_capture_provenance(self):
        match = {"player1": {"name": "Alice Player"}, "player2": {"name": "Bea Player"}, "_tour": "wta"}
        key = fetch_data._odds_names_key("Alice Player", "Bea Player")
        embedded = {
            f"*:{key}": {
                "n1": "Alice Player", "n2": "Bea Player", "o1": 1.44, "o2": 2.90,
                "captured_at_utc": "2026-08-29T10:00:00+00:00", "endpoint": "https://provider.test/upcoming",
            }
        }
        with patch.dict(fetch_data._RAPIDAPI_EMBEDDED_ODDS, embedded, clear=True):
            odds, provenance = fetch_data.fetch_rapidapi_moneyline_with_provenance(match)
        self.assertEqual(odds["Alice Player"], 1.44)
        self.assertEqual(provenance["captured_at_utc"], "2026-08-29T10:00:00+00:00")
        self.assertEqual(provenance["endpoint"], "https://provider.test/upcoming")
        self.assertTrue(provenance["from_cache"])

    def test_rapidapi_recent_pricing_requires_verified_named_bookmaker_pair(self):
        match = {"player1": {"name": "Alice Player"}, "player2": {"name": "Bea Player"}, "_tour": "atp"}
        class Response:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                timestamp = str(datetime.now(timezone.utc).timestamp())
                return {"result": {"Full Time Result": {
                    "Test Book": {"od1": "1.70", "od2": "2.20", "addTime": timestamp},
                    "Z Backup": {"od1": "1.70", "od2": "2.20", "addTime": timestamp},
                }}}

        verified_event = {"valid": True, "event_id": "event-1", "participant1": "Alice Player", "participant2": "Bea Player"}
        with patch.object(fetch_data, "_rapidapi_event_record_for_match", return_value=verified_event), \
                patch.object(fetch_data, "_rapidapi_get", return_value=Response()), \
                patch.dict(fetch_data._RAPIDAPI_FRESH_ODDS_CACHE, {}, clear=True):
            odds, provenance = fetch_data.fetch_rapidapi_recent_moneyline_with_provenance(match)
        self.assertEqual(odds, {"Alice Player": 1.70, "Bea Player": 2.20})
        self.assertEqual(provenance["bookmaker"], "Test Book")
        self.assertEqual(provenance["capture_kind"], "rapidapi_response_observed_at_capture")
        self.assertEqual(provenance["provider_timestamp_status"], "unreliable_for_freshness")

    def test_exact_name_event_remains_valid_for_pricing_but_not_v2_identity(self):
        future = (datetime.now(timezone.utc) + pd.Timedelta(hours=4)).isoformat()
        match = {
            "id": 9000, "_tour": "atp", "date": future,
            "tournamentId": 44, "player1Id": 10, "player2Id": 20,
            "player1": {"id": 10, "name": "Alice Player"},
            "player2": {"id": 20, "name": "Bea Player"},
        }
        event = fetch_data._validated_event_record({"result": {
            "eventId": "event-by-name",
            "participant1": "Alice Player",
            "participant2": "Bea Player",
            "status": "scheduled",
            "startTime": future,
        }}, match, require_explicit_event_id=True)

        class Response:
            status_code = 200

            @staticmethod
            def raise_for_status():
                return None

            @staticmethod
            def json():
                timestamp = str(datetime.now(timezone.utc).timestamp())
                return {"result": {"Full Time Result": {
                    "Test Book": {"od1": "1.70", "od2": "2.20", "addTime": timestamp},
                }}}

        with patch.object(
            fetch_data, "_rapidapi_event_record_for_match", return_value=event,
        ), patch.object(
            fetch_data, "_rapidapi_get", return_value=Response(),
        ), patch.dict(fetch_data._RAPIDAPI_FRESH_ODDS_CACHE, {}, clear=True):
            odds, provenance = fetch_data.fetch_rapidapi_recent_moneyline_with_provenance(
                match
            )

        self.assertEqual(odds, {"Alice Player": 1.70, "Bea Player": 2.20})
        self.assertTrue(provenance["operational_pricing_eligible"])
        self.assertEqual(provenance["identity_mapping_status"], "VERIFIED")
        self.assertEqual(
            provenance["event_identity_validation_basis"], "EXACT_NAMES"
        )
        self.assertFalse(
            match_identity_v2.event_id_is_strong_identity_evidence(provenance)
        )

    def test_rapidapi_pricing_maps_odds_using_verified_provider_order(self):
        match = {"player1": {"name": "Alice Player"}, "player2": {"name": "Bea Player"}, "_tour": "atp"}

        class Response:
            status_code = 200
            def raise_for_status(self): return None
            def json(self):
                timestamp = str(datetime.now(timezone.utc).timestamp())
                return {"result": {"Full Time Result": {
                    "Test Book": {"od1": "2.20", "od2": "1.70", "addTime": timestamp},
                    "Z Backup": {"od1": "2.20", "od2": "1.70", "addTime": timestamp},
                }}}

        # A API publicou Bea primeiro; Alice tem obrigatoriamente de receber od2.
        verified_event = {"valid": True, "event_id": "event-2", "participant1": "Bea Player", "participant2": "Alice Player"}
        with patch.object(fetch_data, "_rapidapi_event_record_for_match", return_value=verified_event), \
                patch.object(fetch_data, "_rapidapi_get", return_value=Response()), \
                patch.dict(fetch_data._RAPIDAPI_FRESH_ODDS_CACHE, {}, clear=True):
            odds, provenance = fetch_data.fetch_rapidapi_recent_moneyline_with_provenance(match)
        self.assertEqual(odds, {"Alice Player": 1.70, "Bea Player": 2.20})
        expected_alice_probability = (1 / 1.70) / ((1 / 1.70) + (1 / 2.20))
        self.assertAlmostEqual(
            provenance["market_integrity"]["median_devig_probability_a"],
            expected_alice_probability,
        )

    def test_event_integrity_rejects_finished_event_with_matching_players(self):
        match = {"id": 77, "date": "2026-08-30T15:00:00+00:00", "player1": {"name": "Arthur Fery"}, "player2": {"name": "Ignacio Buse"}}
        payload = {"result": {"id": "old-event", "participant1": "Arthur Fery", "participant2": "Ignacio Buse", "status": "finished"}}
        with patch.object(fetch_data, "_rapidapi_event_record_for_match", return_value=fetch_data._validated_event_record(payload, match)):
            integrity = fetch_data.rapidapi_event_integrity(match)
        self.assertEqual(integrity["status"], "rejected")
        self.assertEqual(integrity["reason"], "event_not_prelive")

    def test_rapidapi_recent_pricing_keeps_quote_when_provider_timestamp_is_stale(self):
        match = {"player1": {"name": "Alice Player"}, "player2": {"name": "Bea Player"}, "_tour": "atp"}

        class Response:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                stale = (datetime.now(timezone.utc) - pd.Timedelta(minutes=16)).timestamp()
                return {"result": {"Full Time Result": {
                    "Test Book": {"od1": "1.70", "od2": "2.20", "addTime": str(stale)},
                    "Z Backup": {"od1": "1.70", "od2": "2.20", "addTime": str(stale)},
                }}}

        verified_event = {"valid": True, "event_id": "event-1", "participant1": "Alice Player", "participant2": "Bea Player"}
        with patch.object(fetch_data, "_rapidapi_event_record_for_match", return_value=verified_event), \
                patch.object(fetch_data, "_rapidapi_get", return_value=Response()), \
                patch.dict(fetch_data._RAPIDAPI_FRESH_ODDS_CACHE, {}, clear=True):
            odds, provenance = fetch_data.fetch_rapidapi_recent_moneyline_with_provenance(match)
        self.assertEqual(odds, {"Alice Player": 1.70, "Bea Player": 2.20})
        self.assertEqual(provenance["capture_kind"], "rapidapi_response_observed_at_capture")
        self.assertEqual(provenance["provider_timestamp_status"], "unreliable_for_freshness")
        self.assertTrue(provenance["raw_payload_sha256"])
        self.assertEqual(len(provenance["market_quotes"]), 2)

    def test_event_lookup_accepts_audited_cori_coco_alias_without_relaxing_pair_validation(self):
        future = (datetime.now(timezone.utc) + pd.Timedelta(hours=4)).isoformat()
        match = {
            "id": 9001,
            "date": future,
            "player1": {"name": "Mirra Andreeva"},
            "player2": {"name": "Cori Gauff"},
        }

        class Response:
            status_code = 200

            def __init__(self, payload):
                self.payload = payload

            def json(self):
                return self.payload

        calls = []

        def lookup(url):
            calls.append(url)
            if "Coco%20Gauff" in url:
                return Response({"result": {
                    "id": "coco-event",
                    "participant1": "Mirra Andreeva",
                    "participant2": "Coco Gauff",
                    "status": "scheduled",
                    "startTime": future,
                }})
            return Response({"result": {}})

        identity_store = Mock()
        identity_store.get_entry.return_value = None
        with patch.object(fetch_data, "_rapidapi_get", side_effect=lookup), \
                patch.object(fetch_data, "_EVENT_IDENTITY_STORE", identity_store), \
                patch.dict(fetch_data._RAPIDAPI_EVENT_LOOKUP_CACHE, {}, clear=True), \
                patch.dict(fetch_data._RAPIDAPI_EVENT_LOOKUP_DIAGNOSTICS, {}, clear=True):
            record = fetch_data._rapidapi_event_record_for_match(match)

        self.assertTrue(record["valid"])
        self.assertEqual(record["event_id"], "coco-event")
        self.assertEqual(record["identity_source"], "bounded_event_get:audited_alias_direct")
        self.assertEqual(record["event_identity_validation_basis"], "EXACT_NAMES")
        persisted = identity_store.set_entry.call_args.args[2]
        self.assertEqual(
            persisted["event_identity_validation_basis"], "EXACT_NAMES"
        )
        self.assertTrue(any("Coco%20Gauff" in url for url in calls))

    def test_persistent_verified_event_identity_is_reused_only_for_same_future_fixture(self):
        future = (datetime.now(timezone.utc) + pd.Timedelta(hours=4)).isoformat()
        match = {
            "id": 9010,
            "date": future,
            "player1": {"name": "Alice Player"},
            "player2": {"name": "Bea Player"},
        }
        store = Mock()
        store.get_entry.return_value = {
            "event_id": "saved-event",
            "participant1": "Bea Player",
            "participant2": "Alice Player",
            "event_start": future,
            "event_identity_validation_basis": "PLAYER_IDS",
        }
        with patch.object(fetch_data, "_EVENT_IDENTITY_STORE", store):
            record = fetch_data._cached_event_record_for_match(match)
        self.assertTrue(record["valid"])
        self.assertEqual(record["event_id"], "saved-event")
        self.assertEqual(record["participant1"], "Bea Player")
        self.assertEqual(record["identity_source"], "verified_persistent")
        self.assertEqual(record["event_identity_validation_basis"], "PLAYER_IDS")

    def test_extend_upcoming_bridge_resolves_event_without_name_lookup(self):
        future = (datetime.now(timezone.utc) + pd.Timedelta(hours=4)).isoformat()
        match = {
            "id": 9012, "_tour": "wta", "date": future,
            "tournamentId": 55, "roundId": 3,
            "player1Id": 101, "player2Id": 202,
            "player1": {"id": 101, "name": "Aryna Sabalenka"},
            "player2": {"id": 202, "name": "Jessica Pegula"},
        }
        candidate = {
            "id": "event-bridge-1", "participant1": "Jessica Pegula",
            "participant2": "Aryna Sabalenka", "status": "scheduled",
            "startTime": future, "matchId": "202-101-55-3",
        }
        identity_store = Mock()
        identity_store.get_entry.return_value = None
        with patch.object(fetch_data, "_fetch_extend_upcoming_events", return_value=[]), \
                patch.object(fetch_data, "_fetch_extend_event_bridge_records", return_value=[candidate]), \
                patch.object(fetch_data, "_EVENT_IDENTITY_STORE", identity_store), \
                patch.dict(fetch_data._RAPIDAPI_EVENT_INDEX, {}, clear=True), \
                patch.dict(fetch_data._RAPIDAPI_EMBEDDED_ODDS, {}, clear=True), \
                patch.object(fetch_data, "_RAPIDAPI_EVENT_INDEX_READY", set()):
            fetch_data.prepare_rapidapi_odds_index([match])
            record = fetch_data._rapidapi_event_record_for_match(match)
        self.assertTrue(record["valid"])
        self.assertEqual(record["event_id"], "event-bridge-1")
        self.assertEqual(record["participant1"], "Jessica Pegula")
        self.assertEqual(
            record["event_identity_validation_basis"], "STRUCTURAL_MATCH_ID"
        )

    def test_embedded_event_id_prevents_an_extra_extend_index_call(self):
        future = (datetime.now(timezone.utc) + pd.Timedelta(hours=4)).isoformat()
        match = {
            "id": 9014, "_tour": "wta", "date": future,
            "player1Id": 18455, "player2Id": 11712,
            "player1": {"id": 18455, "name": "Aryna Sabalenka"},
            "player2": {"id": 11712, "name": "Jessica Pegula"},
        }
        embedded = {
            "eventId": "embedded-event", "_tour": "wta", "status": "scheduled",
            "startTime": future,
            "player1": {"id": 18455, "name": "A. Sabalenka"},
            "player2": {"id": 11712, "name": "J. Pegula"},
        }
        identity_store = Mock()
        identity_store.get_entry.return_value = None
        with patch.object(fetch_data, "_fetch_extend_upcoming_events", return_value=[embedded]), \
                patch.object(fetch_data, "_fetch_extend_event_bridge_records") as extend_index, \
                patch.object(fetch_data, "_EVENT_IDENTITY_STORE", identity_store), \
                patch.dict(fetch_data._RAPIDAPI_EVENT_INDEX, {}, clear=True), \
                patch.dict(fetch_data._RAPIDAPI_EMBEDDED_ODDS, {}, clear=True), \
                patch.dict(fetch_data._RAPIDAPI_EVENT_LOOKUP_CACHE, {}, clear=True), \
                patch.dict(fetch_data._RAPIDAPI_EVENT_LOOKUP_DIAGNOSTICS, {}, clear=True), \
                patch.object(fetch_data, "_ALL_UPCOMING_EVENTS_CACHE", [embedded]), \
                patch.object(fetch_data, "_RAPIDAPI_EVENT_INDEX_READY", set()):
            fetch_data.prepare_rapidapi_odds_index([match])
            record = fetch_data._rapidapi_event_record_for_match(match)
            metrics = fetch_data.get_rapidapi_identity_metrics()
        self.assertEqual(record["event_id"], "embedded-event")
        self.assertEqual(record["identity_index_source"], "embedded_upcoming")
        self.assertEqual(record["event_identity_validation_basis"], "PLAYER_IDS")
        self.assertEqual(metrics["by_tour"]["wta"]["index_resolutions"], 1)
        self.assertEqual(metrics["by_tour"]["wta"]["cache_hits"], 0)
        self.assertEqual(metrics["matches"][0]["cache_status"], "NOT_APPLICABLE")
        extend_index.assert_not_called()

    def test_persistent_event_identity_is_reported_as_cache_hit(self):
        future = (datetime.now(timezone.utc) + pd.Timedelta(hours=4)).isoformat()
        match = {
            "id": 9015, "_tour": "wta", "date": future,
            "player1": {"name": "Aryna Sabalenka"},
            "player2": {"name": "Jessica Pegula"},
        }
        identity_store = Mock()
        identity_store.get_entry.return_value = {
            "event_id": "persisted-event", "participant1": "Aryna Sabalenka",
            "participant2": "Jessica Pegula", "event_start": future,
            "event_identity_validation_basis": "EXACT_NAMES",
        }
        with patch.object(fetch_data, "_EVENT_IDENTITY_STORE", identity_store), \
                patch.dict(fetch_data._RAPIDAPI_EVENT_INDEX, {}, clear=True), \
                patch.dict(fetch_data._RAPIDAPI_EVENT_LOOKUP_CACHE, {}, clear=True), \
                patch.dict(fetch_data._RAPIDAPI_EVENT_LOOKUP_DIAGNOSTICS, {}, clear=True):
            record = fetch_data._rapidapi_event_record_for_match(match)
            metrics = fetch_data.get_rapidapi_identity_metrics()
        self.assertEqual(record["event_id"], "persisted-event")
        self.assertEqual(record["event_identity_validation_basis"], "EXACT_NAMES")
        self.assertEqual(metrics["by_tour"]["wta"]["persistent_cache_hits"], 1)
        self.assertEqual(metrics["by_tour"]["wta"]["cache_hits"], 1)
        self.assertEqual(metrics["by_tour"]["wta"]["cache_misses"], 0)

    def test_in_run_event_identity_is_reported_separately(self):
        future = (datetime.now(timezone.utc) + pd.Timedelta(hours=4)).isoformat()
        match = {
            "id": 9016, "_tour": "wta", "date": future,
            "player1": {"name": "Aryna Sabalenka"},
            "player2": {"name": "Jessica Pegula"},
        }
        cached = {
            "valid": True, "event_id": "run-event", "participant1": "Aryna Sabalenka",
            "participant2": "Jessica Pegula", "event_start": future,
            "event_identity_validation_basis": "PLAYER_IDS",
        }
        with patch.dict(
            fetch_data._RAPIDAPI_EVENT_LOOKUP_CACHE, {"9016": cached}, clear=True,
        ), patch.dict(fetch_data._RAPIDAPI_EVENT_INDEX, {}, clear=True), patch.dict(
            fetch_data._RAPIDAPI_EVENT_LOOKUP_DIAGNOSTICS, {}, clear=True,
        ):
            record = fetch_data._rapidapi_event_record_for_match(match)
            metrics = fetch_data.get_rapidapi_identity_metrics()
        self.assertEqual(record["event_id"], "run-event")
        self.assertEqual(record["event_identity_validation_basis"], "PLAYER_IDS")
        self.assertEqual(metrics["by_tour"]["wta"]["in_run_cache_hits"], 1)
        self.assertEqual(metrics["by_tour"]["wta"]["persistent_cache_hits"], 0)

    def test_extend_bridge_accepts_abbreviated_display_names_only_with_exact_match_id(self):
        future = (datetime.now(timezone.utc) + pd.Timedelta(hours=4)).isoformat()
        match = {
            "id": 9013, "_tour": "wta", "date": future,
            "tournamentId": 55, "roundId": 3,
            "player1Id": 101, "player2Id": 202,
            "player1": {"id": 101, "name": "Aryna Sabalenka"},
            "player2": {"id": 202, "name": "Jessica Pegula"},
        }
        candidate = {
            "id": "event-bridge-short-names", "participant1": "J. Pegula",
            "participant2": "A. Sabalenka", "status": "scheduled",
            "startTime": future, "matchId": "202-101-55-3",
        }
        identity_store = Mock()
        identity_store.get_entry.return_value = None
        with patch.object(fetch_data, "_fetch_extend_upcoming_events", return_value=[]), \
                patch.object(fetch_data, "_fetch_extend_event_bridge_records", return_value=[candidate]), \
                patch.object(fetch_data, "_EVENT_IDENTITY_STORE", identity_store), \
                patch.dict(fetch_data._RAPIDAPI_EVENT_INDEX, {}, clear=True), \
                patch.dict(fetch_data._RAPIDAPI_EMBEDDED_ODDS, {}, clear=True), \
                patch.object(fetch_data, "_RAPIDAPI_EVENT_INDEX_READY", set()):
            fetch_data.prepare_rapidapi_odds_index([match])
            record = fetch_data._rapidapi_event_record_for_match(match)
        self.assertTrue(record["valid"])
        self.assertEqual(record["event_id"], "event-bridge-short-names")
        self.assertEqual(record["participant1"], "Jessica Pegula")
        self.assertEqual(record["participant2"], "Aryna Sabalenka")
        self.assertEqual(record["identity_source"], "verified_match_id")

    def test_identity_bridge_prefers_bilateral_player_ids_for_wta_and_atp_controls(self):
        future = (datetime.now(timezone.utc) + pd.Timedelta(hours=4)).isoformat()
        cases = (
            ("wta", 18455, "Aryna Sabalenka", 11712, "Jessica Pegula"),
            ("wta", 54663, "Cori Gauff", 36558, "Elena Rybakina"),
            ("atp", 1001, "Alexander Zverev", 1002, "Karen Khachanov"),
            ("atp", 1003, "Frances Tiafoe", 1004, "Ben Shelton"),
        )
        identity_store = Mock()
        identity_store.get_entry.return_value = None
        for index, (tour, first_id, first_name, second_id, second_name) in enumerate(cases):
            match = {
                "id": 9200 + index, "_tour": tour, "date": future,
                "player1Id": first_id, "player2Id": second_id,
                "player1": {"id": first_id, "name": first_name},
                "player2": {"id": second_id, "name": second_name},
            }
            candidate = {
                "eventId": f"verified-{index}", "status": "scheduled", "startTime": future,
                "participant1": {"id": second_id, "name": f"{second_name.split()[-1]} X."},
                "participant2": {"id": first_id, "name": f"{first_name.split()[-1]} Y."},
            }
            with self.subTest(first_name=first_name), \
                    patch.object(fetch_data, "_fetch_extend_upcoming_events", return_value=[]), \
                    patch.object(fetch_data, "_fetch_extend_event_bridge_records", return_value=[candidate]), \
                    patch.object(fetch_data, "_EVENT_IDENTITY_STORE", identity_store), \
                    patch.object(fetch_data, "_rapidapi_get") as individual_lookup, \
                    patch.dict(fetch_data._RAPIDAPI_EVENT_INDEX, {}, clear=True), \
                    patch.dict(fetch_data._RAPIDAPI_EMBEDDED_ODDS, {}, clear=True), \
                    patch.object(fetch_data, "_ALL_UPCOMING_EVENTS_CACHE", []), \
                    patch.object(fetch_data, "_RAPIDAPI_EVENT_INDEX_READY", set()):
                fetch_data.prepare_rapidapi_odds_index([match])
                record = fetch_data._rapidapi_event_record_for_match(match)
            self.assertEqual(record["event_id"], f"verified-{index}")
            self.assertEqual(record["identity_source"], "verified_player_ids")
            self.assertEqual(record["event_identity_validation_basis"], "PLAYER_IDS")
            individual_lookup.assert_not_called()

    def test_event_lookup_is_bounded_and_does_not_generate_initial_combinations(self):
        future = (datetime.now(timezone.utc) + pd.Timedelta(hours=4)).isoformat()
        match = {
            "id": 9300, "_tour": "wta", "date": future,
            "player1": {"name": "Aryna Sabalenka"},
            "player2": {"name": "Jessica Pegula"},
        }

        class EmptyResponse:
            status_code = 200

            @staticmethod
            def json():
                return {"result": {}}

        calls = []
        identity_store = Mock()
        identity_store.get_entry.return_value = None
        with patch.object(fetch_data, "_rapidapi_get", side_effect=lambda url: calls.append(url) or EmptyResponse()), \
                patch.object(fetch_data, "_EVENT_IDENTITY_STORE", identity_store), \
                patch.dict(fetch_data._RAPIDAPI_EVENT_LOOKUP_CACHE, {}, clear=True), \
                patch.dict(fetch_data._RAPIDAPI_EVENT_LOOKUP_DIAGNOSTICS, {}, clear=True):
            record = fetch_data._rapidapi_event_record_for_match(match)
            metrics = fetch_data.get_rapidapi_identity_metrics()
        self.assertIsNone(record)
        self.assertLessEqual(len(calls), fetch_data.RAPIDAPI_EVENT_FALLBACK_MAX_ATTEMPTS)
        self.assertTrue(all("A.%20Sabalenka" not in url and "J.%20Pegula" not in url for url in calls))
        self.assertEqual(metrics["by_tour"]["wta"]["lookup_attempts"], len(calls))
        self.assertEqual(metrics["by_tour"]["wta"]["cache_misses"], 1)
        self.assertEqual(metrics["by_tour"]["wta"]["fallback_after_miss"], 1)
        self.assertEqual(metrics["by_tour"]["wta"]["cache_hits"], 0)

    def test_complete_provider_ids_cannot_be_overridden_by_matching_names(self):
        future = (datetime.now(timezone.utc) + pd.Timedelta(hours=4)).isoformat()
        match = {
            "_tour": "wta", "date": future, "player1Id": 18455, "player2Id": 11712,
            "player1": {"id": 18455, "name": "Aryna Sabalenka"},
            "player2": {"id": 11712, "name": "Jessica Pegula"},
        }
        wrong = {
            "eventId": "wrong", "startTime": future, "status": "scheduled",
            "participant1": {"id": 999, "name": "Aryna Sabalenka"},
            "participant2": {"id": 998, "name": "Jessica Pegula"},
        }
        self.assertIsNone(fetch_data._validated_event_record(wrong, match))

    def test_partial_conflicting_provider_id_cannot_be_overridden_by_names(self):
        future = (datetime.now(timezone.utc) + pd.Timedelta(hours=4)).isoformat()
        match = {
            "_tour": "wta", "date": future, "player1Id": 18455, "player2Id": 11712,
            "player1": {"id": 18455, "name": "Aryna Sabalenka"},
            "player2": {"id": 11712, "name": "Jessica Pegula"},
        }
        wrong = {
            "eventId": "wrong", "startTime": future, "status": "scheduled",
            "participant1": {"id": 999, "name": "Aryna Sabalenka"},
            "participant2": {"name": "Jessica Pegula"},
        }
        self.assertIsNone(fetch_data._validated_event_record(wrong, match))

    def test_wta_h2h_stats_500_degrades_only_its_coverage_family(self):
        class Response:
            def __init__(self, payload=None, status_code=200):
                self.payload = payload or {}
                self.status_code = status_code

            def raise_for_status(self):
                if self.status_code >= 400:
                    error = fetch_data.requests.HTTPError(f"{self.status_code} WTA h2h")
                    error.response = self
                    raise error

            def json(self):
                return self.payload

        h2h_matches = [{
            "id": 1, "date": "2026-08-01T12:00:00+00:00",
            "player1Id": 18455, "player2Id": 11712, "match_winner": 18455,
        }]
        recent_a = [{
            "id": 2, "date": "2026-09-08T12:00:00+00:00", "court": "hard",
            "player1Id": 18455, "player2Id": 88, "match_winner": 18455,
        }]
        recent_b = [{
            "id": 3, "date": "2026-09-08T14:00:00+00:00", "court": "hard",
            "player1Id": 11712, "player2Id": 99, "match_winner": 11712,
        }]

        def route(url):
            if "/wta/h2h/stats/" in url:
                return Response(status_code=500)
            if "/wta/h2h/matches/" in url:
                return Response({"data": h2h_matches})
            if "/wta/player/past-matches/18455" in url:
                return Response({"data": recent_a})
            if "/wta/player/past-matches/11712" in url:
                return Response({"data": recent_b})
            self.fail(f"unexpected endpoint: {url}")

        with patch.object(fetch_data, "RAPIDAPI_KEY", "test"), \
                patch.object(fetch_data, "_rapidapi_get", side_effect=route), \
                patch.object(fetch_data, "_read_player_cache_entry", return_value=None), \
                patch.object(fetch_data, "_write_player_cache_entry"), \
                patch.dict(fetch_data._H2H_CACHE, {}, clear=True), \
                patch.dict(fetch_data._RECENT_MATCHES_CACHE, {}, clear=True):
            rich_stats, rich_coverage = fetch_data.fetch_h2h_stats_with_coverage(
                "wta", 18455, 11712,
            )
            actual_h2h_matches = fetch_data.fetch_h2h_matches("wta", 18455, 11712)
            actual_recent_a = fetch_data.fetch_player_recent_matches("wta", 18455)
            actual_recent_b = fetch_data.fetch_player_recent_matches("wta", 11712)

        start = datetime(2026, 9, 11, tzinfo=timezone.utc)
        form_a = fetch_data.compute_form_from_recent(actual_recent_a, 18455, start, 10, "hard")["form"]
        form_b = fetch_data.compute_form_from_recent(actual_recent_b, 11712, start, 10, "hard")["form"]
        h2h = fetch_data.compute_h2h_from_api(actual_h2h_matches, 18455, 11712)
        available = {"status": "AVAILABLE", "source": "independent_test_source", "reason": None}
        coverage = {
            "h2h_rich_stats": rich_coverage,
            "h2h": {"status": "AVAILABLE", "source": "rapidapi_h2h_matches", "reason": None},
            "historical_matches": {"a": available, "b": available},
            "recent_form": {"a": available, "b": available},
            "ranking": {"a": available, "b": available},
        }

        self.assertIsNone(rich_stats)
        self.assertEqual(rich_coverage["status"], "UNAVAILABLE")
        self.assertEqual(rich_coverage["endpoint_family"], "wta/h2h/stats")
        self.assertEqual(rich_coverage["reason"], "http_500")
        self.assertEqual(rich_coverage["http_status"], 500)
        self.assertEqual(h2h["overall"], {"a_wins": 1, "b_wins": 0, "total_matches": 1})
        self.assertEqual(form_a, {"wins": 1, "losses": 0, "matches": 1})
        self.assertEqual(form_b, {"wins": 1, "losses": 0, "matches": 1})
        self.assertEqual(main._report_data_status(coverage), "DEGRADED")

    def test_event_lookup_uses_generic_full_and_initial_surname_forms(self):
        self.assertEqual(
            fetch_data._rapidapi_event_name_variants("Aryna Sabalenka"),
            ["Aryna Sabalenka", "A. Sabalenka", "Sabalenka A."],
        )
        self.assertEqual(
            fetch_data._event_names_key("A. Sabalenka", "J. Pegula"),
            fetch_data._event_names_key("Aryna Sabalenka", "Jessica Pegula"),
        )
        self.assertEqual(
            fetch_data._event_names_key("Sabalenka A.", "Pegula J."),
            fetch_data._event_names_key("Aryna Sabalenka", "Jessica Pegula"),
        )
        self.assertEqual(
            fetch_data._event_names_key("T. M. Etcheverry", "A. Zverev"),
            fetch_data._event_names_key("Tomas Martin Etcheverry", "Alexander Zverev"),
        )

    def test_embedded_odds_accept_confirmed_short_names_and_preserve_sides(self):
        match = {
            "_tour": "wta",
            "player1": {"name": "Aryna Sabalenka"},
            "player2": {"name": "Jessica Pegula"},
        }
        key = fetch_data._odds_names_key("Aryna Sabalenka", "Jessica Pegula")
        embedded = {f"*:{key}": {
            "n1": "A. Sabalenka", "n2": "J. Pegula", "o1": 1.44, "o2": 2.80,
        }}
        with patch.dict(fetch_data._RAPIDAPI_EMBEDDED_ODDS, embedded, clear=True):
            odds, provenance = fetch_data.fetch_rapidapi_embedded_moneyline_with_provenance(match)
        self.assertEqual(odds, {"Aryna Sabalenka": 1.44, "Jessica Pegula": 2.80})
        self.assertEqual(provenance["provider_side_a"], "player1")

    def test_embedded_odds_use_verified_player_ids_when_provider_names_differ(self):
        match = {
            "_tour": "wta", "player1Id": 101, "player2Id": 202,
            "player1": {"id": 101, "name": "Aryna Sabalenka"},
            "player2": {"id": 202, "name": "Jessica Pegula"},
        }
        key = fetch_data._odds_names_key("Aryna Sabalenka", "Jessica Pegula")
        embedded = {f"*:{key}": {
            "n1": "A. Saba", "n2": "J. Peg", "p1_id": "202", "p2_id": "101",
            "o1": 2.80, "o2": 1.44,
        }}
        with patch.dict(fetch_data._RAPIDAPI_EMBEDDED_ODDS, embedded, clear=True):
            odds, provenance = fetch_data.fetch_rapidapi_embedded_moneyline_with_provenance(match)
        self.assertEqual(odds, {"Aryna Sabalenka": 1.44, "Jessica Pegula": 2.80})
        self.assertEqual(provenance["identity_mapping_status"], "VERIFIED_PROVIDER_PLAYER_IDS")

    def test_prelive_lookup_does_not_reject_delayed_fixture_only_for_its_scheduled_time(self):
        match = {
            "id": 9011,
            "date": "2000-01-01T00:00:00+00:00",
            "player1": {"name": "Alice Player"},
            "player2": {"name": "Bea Player"},
        }
        identity_store = Mock()
        identity_store.get_entry.return_value = None
        with patch.object(fetch_data, "_rapidapi_get") as lookup, \
                patch.object(fetch_data, "_EVENT_IDENTITY_STORE", identity_store), \
                patch.dict(fetch_data._RAPIDAPI_EVENT_LOOKUP_CACHE, {}, clear=True):
            lookup.return_value.status_code = 200
            lookup.return_value.json.return_value = {"result": {
                "id": "delayed-event", "participant1": "Alice Player",
                "participant2": "Bea Player", "status": "scheduled",
                "startTime": "2000-01-01T00:00:00+00:00",
            }}
            record = fetch_data._rapidapi_event_record_for_match(match)
        self.assertTrue(record["valid"])

    def test_recent_odds_exposes_event_lookup_failure_reason(self):
        match = {
            "id": 91,
            "date": "2026-09-09T15:00:00+00:00",
            "player1": {"name": "Alice Player"},
            "player2": {"name": "Bea Player"},
        }
        with patch.object(fetch_data, "_rapidapi_event_record_for_match", return_value=None), \
                patch.dict(fetch_data._RAPIDAPI_EVENT_LOOKUP_DIAGNOSTICS, {}, clear=True):
            odds, provenance = fetch_data.fetch_rapidapi_recent_moneyline_with_provenance(match)
        self.assertIsNone(odds)
        self.assertEqual(provenance["unavailable_reason"], "event_identity_unavailable")

    def test_the_odds_api_is_off_by_default_even_when_secret_exists(self):
        with patch.object(fetch_data, "THE_ODDS_API_ENABLED", False), \
                patch.object(fetch_data, "ODDS_API_KEY", "configured-but-not-authorized"), \
                patch.object(fetch_data.requests, "get") as request:
            fetch_data.prepare_the_odds_market_index([{
                "_tour": "atp", "tournament_name": "U.S. Open - New York",
            }])
        request.assert_not_called()

    def test_the_odds_api_maps_tokyo_to_atp_japan_open(self):
        for tournament_name in (
            "Japan Open - Tokyo",
            "Kinoshita Group Japan Open Tennis Championships",
            "ATP Tokyo",
        ):
            keys = fetch_data._the_odds_sport_keys_for_match({
                "_tour": "atp", "tournament_name": tournament_name,
            })
            self.assertIn("tennis_atp_japan_open", keys)

    def test_the_odds_api_maps_sponsored_shanghai_name_to_masters_competition(self):
        for tournament_name in (
            "Shanghai Rolex Masters - Shanghai",
            "Rolex Shanghai Masters",
        ):
            keys = fetch_data._the_odds_sport_keys_for_match({
                "_tour": "atp", "tournament_name": tournament_name,
            })
            self.assertIn("tennis_atp_shanghai_masters", keys)

    def test_the_odds_api_selection_reserves_a_competition_per_tour(self):
        matches = [
            {"_tour": "atp", "tournament_name": "China Open - Beijing"},
            {"_tour": "atp", "tournament_name": "Japan Open - Tokyo"},
            {"_tour": "wta", "tournament_name": "China Open - Beijing"},
        ]
        selected, deferred = fetch_data._select_the_odds_sport_keys(matches, 2)
        self.assertEqual(selected, ["tennis_atp_china_open", "tennis_wta_china_open"])
        self.assertEqual(deferred, ["tennis_atp_japan_open"])

    def test_the_odds_api_selection_prioritizes_tournament_with_most_eligible_matches(self):
        matches = (
            [{"_tour": "atp", "tournament_name": "Shanghai Rolex Masters - Shanghai"}] * 12
            + [{"_tour": "atp", "tournament_name": "China Open - Beijing"}]
            + [{"_tour": "atp", "tournament_name": "Japan Open - Tokyo"}]
            + [{"_tour": "wta", "tournament_name": "China Open - Beijing"}]
        )
        selected, deferred = fetch_data._select_the_odds_sport_keys(matches, 3)
        self.assertEqual(selected[:2], ["tennis_atp_shanghai_masters", "tennis_wta_china_open"])
        self.assertEqual(deferred, ["tennis_atp_japan_open"])

    def test_the_odds_pricing_uses_fresh_market_timestamp_and_same_bookmaker_pair(self):
        match = {
            "player1": {"name": "Alice Player"}, "player2": {"name": "Bea Player"},
            "_tour": "atp", "tournament_name": "U.S. Open - New York",
        }
        now = datetime.now(timezone.utc).isoformat()
        event = {
            "id": "odds-event-1", "home_team": "Alice Player", "away_team": "Bea Player",
            "bookmakers": [{
                "title": "Test Book", "markets": [{"key": "h2h", "last_update": now, "outcomes": [
                    {"name": "Alice Player", "price": 1.28}, {"name": "Bea Player", "price": 4.10},
                ]}],
            }],
        }
        with patch.object(fetch_data, "THE_ODDS_API_ENABLED", True), \
                patch.dict(fetch_data._THE_ODDS_EVENTS, {"tennis_atp_us_open": [event]}, clear=True):
            odds, provenance = fetch_data.fetch_the_odds_moneyline_with_provenance(match)
        self.assertEqual(odds, {"Alice Player": 1.28, "Bea Player": 4.10})
        self.assertEqual(provenance["bookmaker"], "Test Book")
        self.assertEqual(provenance["capture_kind"], "provider_last_update_verified")
        self.assertEqual(provenance["freshness_status"], "FRESH")
        self.assertTrue(provenance["operational_pricing_eligible"])
        self.assertTrue(market_integrity.is_operational_pricing_provenance(provenance))

    def test_the_odds_pricing_rejects_stale_market_timestamp(self):
        match = {
            "player1": {"name": "Alice Player"}, "player2": {"name": "Bea Player"},
            "_tour": "atp", "tournament_name": "U.S. Open - New York",
        }
        stale = (datetime.now(timezone.utc) - pd.Timedelta(minutes=16)).isoformat()
        event = {
            "id": "odds-event-1", "home_team": "Alice Player", "away_team": "Bea Player",
            "bookmakers": [{
                "title": "Test Book", "markets": [{"key": "h2h", "last_update": stale, "outcomes": [
                    {"name": "Alice Player", "price": 1.28}, {"name": "Bea Player", "price": 4.10},
                ]}],
            }],
        }
        with patch.object(fetch_data, "THE_ODDS_API_ENABLED", True), \
                patch.dict(fetch_data._THE_ODDS_EVENTS, {"tennis_atp_us_open": [event]}, clear=True):
            odds, provenance = fetch_data.fetch_the_odds_moneyline_with_provenance(match)
        self.assertIsNone(odds)
        self.assertIsNone(provenance)

    def test_embedded_pricing_rejects_same_surname_but_wrong_full_name(self):
        match = {"player1": {"name": "Alice Smith"}, "player2": {"name": "Bea Jones"}, "_tour": "atp"}
        key = fetch_data._odds_names_key("Alice Smith", "Bea Jones")
        embedded = {
            f"*:{key}": {
                "n1": "Alex Smith", "n2": "Bea Jones", "o1": 1.71, "o2": 2.18,
                "captured_at_utc": datetime.now(timezone.utc).isoformat(), "endpoint": "https://provider.test/upcoming",
            }
        }
        with patch.dict(fetch_data._RAPIDAPI_EMBEDDED_ODDS, embedded, clear=True):
            odds, provenance = fetch_data.fetch_rapidapi_embedded_moneyline_with_provenance(match)
        self.assertIsNone(odds)
        self.assertIsNone(provenance)

    def test_tournament_info_is_fetched_by_frequency_and_filters_unknown_tiers(self):
        matches = [
            {"id": 1, "tournamentId": 20, "_tour": "atp"},
            {"id": 2, "tournamentId": 10, "_tour": "atp"},
            {"id": 3, "tournamentId": 10, "_tour": "atp"},
            {"id": 4, "tournamentId": 30, "_tour": "wta"},
        ]
        responses = {
            10: {"name": "Lisboa", "surface": "Clay", "tier": "ATP 500", "country": "PT"},
            20: {"name": "Futures", "surface": "Hard", "tier": "Future", "country": "PT"},
            30: None,
        }

        with patch.object(
            main.fetch_data,
            "get_tournament_info",
            side_effect=lambda tournament_id, _tour: responses[tournament_id],
        ) as lookup:
            actual = main._filter_and_enrich_with_tournament_info(matches)

        self.assertEqual([call.args[0] for call in lookup.call_args_list], [10, 20, 30])
        self.assertEqual([match["id"] for match in actual], [2, 3])
        self.assertEqual(actual[0]["tournament_name"], "Lisboa")
        self.assertEqual(actual[0]["surface"], "Clay")

    def test_atp_250_tiers_are_included_without_explicit_override(self):
        matches = [
            {"id": 1, "tournamentId": 21348, "_tour": "atp"},
            {"id": 2, "tournamentId": 99999, "_tour": "atp"},
        ]
        responses = {
            21348: {"name": "Winston-Salem Open", "surface": "Hard", "tier": "ATP 250"},
            99999: {"name": "Outro ATP 250", "surface": "Hard", "tier": "ATP 250"},
        }
        with patch.object(main, "FORCED_TOURNAMENT_IDS", {}), \
             patch.object(main.fetch_data, "get_tournament_info",
                          side_effect=lambda tournament_id, _tour: responses[tournament_id]):
            actual = main._filter_and_enrich_with_tournament_info(matches)

        self.assertEqual([match["id"] for match in actual], [1, 2])
        self.assertEqual(actual[0]["tournament_name"], "Winston-Salem Open")
        self.assertEqual(actual[0]["tier"], "ATP 250")

    def test_deduplication_keeps_first_occurrence_and_entries_without_id(self):
        matches = [
            {"id": 7, "date": "first"},
            {"id": 7, "date": "duplicate"},
            {"date": "without-id-a"},
            {"date": "without-id-b"},
        ]

        actual = main._deduplicate_matches(matches)

        self.assertEqual([item["date"] for item in actual], ["first", "without-id-a", "without-id-b"])

    def test_parse_utc_adds_timezone_only_when_missing(self):
        naive = main._parse_utc("2026-08-15T12:00:00")
        explicit = main._parse_utc("2026-08-15T12:00:00+02:00")

        self.assertEqual(naive.tzinfo, timezone.utc)
        self.assertEqual(explicit.utcoffset().total_seconds(), 7200)

    def test_match_format_uses_bo5_only_for_atp_grand_slams(self):
        self.assertEqual(main._match_format({"_tour": "atp", "tier": "Grand Slam"}), "bo5")
        self.assertEqual(main._match_format({"_tour": "wta", "tier": "Grand Slam"}), "bo3")
        self.assertEqual(main._match_format({"best_of": "5", "_tour": "wta"}), "bo5")

    def test_prelive_filter_excludes_started_or_scored_fixtures(self):
        fixtures = [
            {"id": 1, "status": "scheduled"},
            {"id": 2, "live": True},
            {"id": 3, "status": "suspended", "score": "6-4 2-1"},
            {"id": 4, "status": "interrupted", "result": "6-4 2-1"},
            {"id": 5, "status": "resumed"},
            {"id": 6, "status": "completed"},
            {"id": 7, "state": "unknown", "score": "6-4"},
        ]
        self.assertEqual([item["id"] for item in main._filter_prelive_matches(fixtures)], [1])

    def test_prelive_filter_keeps_scheduled_fixture_when_its_time_has_passed(self):
        fixtures = [
            {"id": 1, "date": "2000-01-01T00:00:00Z", "status": "scheduled"},
            {"id": 2, "date": "2099-01-01T00:00:00Z", "status": "scheduled"},
        ]
        self.assertEqual([item["id"] for item in main._filter_prelive_matches(fixtures)], [1, 2])

    def test_prelive_filter_keeps_scheduled_fixture_with_time_game(self):
        """timeGame é a hora agendada do fornecedor, não evidência de início."""
        fixtures = [
            {"id": 1, "status": "scheduled", "timeGame": "2026-09-28T10:00:00Z"},
            {"id": 2, "status": "scheduled", "timeGame": "2026-09-28T12:30:00Z"},
        ]
        self.assertEqual([item["id"] for item in main._filter_prelive_matches(fixtures)], [1, 2])


class DeterministicStatisticTests(unittest.TestCase):
    def test_indoor_outdoor_context_understands_provider_contract(self):
        self.assertEqual(fetch_data.indoor_outdoor_context("I.hard"), "indoor")
        self.assertEqual(fetch_data.indoor_outdoor_context("Indoor Hard"), "indoor")
        self.assertEqual(fetch_data.indoor_outdoor_context("Hard"), "outdoor")
        self.assertEqual(fetch_data.indoor_outdoor_context("Clay"), "outdoor")
        self.assertIsNone(fetch_data.indoor_outdoor_context("Desconhecido"))

    def test_indoor_outdoor_reads_surface_when_court_column_is_absent(self):
        history = pd.DataFrame([
            {"winner_name": "A", "loser_name": "B", "surface": "I.hard"},
            {"winner_name": "C", "loser_name": "A", "surface": "Hard"},
        ])

        actual = fetch_data.compute_indoor_outdoor_stats(history, "A")

        self.assertEqual(actual["indoor"]["wins"], 1)
        self.assertEqual(actual["outdoor"]["losses"], 1)

    def test_indoor_outdoor_recent_uses_match_level_court_id(self):
        matches = [
            {
                "date": "2026-10-10T12:00:00Z",
                "player1Id": 10,
                "player2Id": 20,
                "match_winner": 10,
                "tournament": {"courtId": 3, "name": "Indoor Event"},
            },
            {
                "date": "2026-10-08T12:00:00Z",
                "player1Id": 10,
                "player2Id": 30,
                "match_winner": 30,
                "tournament": {"courtId": 1, "name": "Outdoor Event"},
            },
        ]

        actual = fetch_data.compute_indoor_outdoor_from_recent(
            matches, 10, datetime(2026, 10, 15, tzinfo=timezone.utc),
        )

        self.assertEqual(actual["indoor"]["wins"], 1)
        self.assertEqual(actual["outdoor"]["losses"], 1)
        self.assertEqual(actual["indoor"]["source"], "rapidapi_player_past_matches")

    def test_indoor_outdoor_perf_breakdown_uses_persisted_factual_buckets(self):
        rich = {"by_surface": {
            "hard": {"wins": 8, "losses": 2, "matches": 10},
            "clay": {"wins": 3, "losses": 2, "matches": 5},
            "grass": {"wins": 1, "losses": 1, "matches": 2},
            "hard_indoor": {"wins": 4, "losses": 1, "matches": 5},
        }}

        actual = fetch_data.compute_indoor_outdoor_from_perf_breakdown(rich)

        self.assertEqual(actual["indoor"]["matches"], 5)
        self.assertEqual(actual["indoor"]["win_pct"], 80.0)
        self.assertEqual(actual["outdoor"]["matches"], 17)
        self.assertEqual(actual["outdoor"]["win_pct"], 70.6)

    def test_surface_transition_uses_recent_court_id_and_excludes_future_match(self):
        matches = [
            {
                "date": "2026-10-10T12:00:00Z",
                "player1Id": 10,
                "player2Id": 20,
                "tournament": {"courtId": 2},
            },
            {
                "date": "2026-10-12T12:00:00Z",
                "player1Id": 10,
                "player2Id": 30,
                "tournament": {"courtId": 2},
            },
            {
                "date": "2026-10-17T12:00:00Z",
                "player1Id": 10,
                "player2Id": 40,
                "tournament": {"courtId": 5},
            },
        ]

        actual = fetch_data.compute_surface_transition(
            pd.DataFrame(), "Player A", "Grass",
            before=datetime(2026, 10, 15, tzinfo=timezone.utc),
            recent_matches=matches, player_id=10,
        )

        self.assertTrue(actual["em_transicao"])
        self.assertEqual(actual["piso_recente_dominante"], "clay")
        self.assertEqual(actual["jogos_recentes_total"], 2)
        self.assertEqual(actual["source"], "rapidapi_player_past_matches")

    def test_surface_transition_local_fallback_is_anchored_before_fixture(self):
        history = pd.DataFrame([
            {
                "winner_name": "A", "loser_name": "B",
                "surface": "Clay", "tourney_date": 20261001,
            },
            {
                "winner_name": "C", "loser_name": "A",
                "surface": "Grass", "tourney_date": 20261020,
            },
        ])

        actual = fetch_data.compute_surface_transition(
            history, "A", "Hard",
            before=datetime(2026, 10, 15, tzinfo=timezone.utc),
        )

        self.assertTrue(actual["em_transicao"])
        self.assertEqual(actual["piso_recente_dominante"], "clay")
        self.assertEqual(actual["source"], "local_match_history")

    def test_h2h_normalizes_surface_family(self):
        history = pd.DataFrame([
            {"winner_name": "A", "loser_name": "B", "surface": "Hardcourt"},
            {"winner_name": "B", "loser_name": "A", "surface": "Indoor Hard"},
            {"winner_name": "A", "loser_name": "B", "surface": "Clay"},
        ])
        actual = fetch_data.compute_h2h(history, "A", "B", "Outdoor Hard")
        self.assertEqual(actual["overall"]["total_matches"], 3)
        self.assertEqual(actual["on_surface"], {"a_wins": 1, "b_wins": 1, "total_matches": 2})
        self.assertEqual(actual["surface_family"], "hard")

    def test_name_resolution_handles_compound_surname_variants_exactly(self):
        history = pd.DataFrame([
            {"winner_name": "Merida D.", "loser_name": "Other P."},
            {"winner_name": "Other P.", "loser_name": "Merida D."},
        ])
        self.assertEqual(
            fetch_data.resolve_player_name(history, "Daniel Merida Aguilar"),
            "Merida D.",
        )

    def test_comeback_normalizes_text_best_of_and_falls_back_to_set_columns(self):
        history = pd.DataFrame([
            {"winner_name": "A", "loser_name": "B", "best_of": "3", "score": None, "W1": 4, "L1": 6},
            {"winner_name": "C", "loser_name": "A", "best_of": "3.0", "score": None, "W1": 6, "L1": 4},
            {"winner_name": "A", "loser_name": "D", "best_of": 5, "score": "4-6 6-3 6-2 6-4", "W1": None, "L1": None},
        ])
        actual = fetch_data.compute_set1_comeback_stats(history, "A")
        self.assertEqual(actual["bo3"]["matches_lost_set1"], 2)
        self.assertEqual(actual["bo3"]["matches_lost_set1_won_overall"], 1)
        self.assertEqual(actual["bo3"]["comeback_rate_pct"], 50.0)
        self.assertEqual(actual["bo5"]["comeback_rate_pct"], 100.0)
        diagnostics = fetch_data.diagnose_set1_comeback(history, "A")
        self.assertEqual(diagnostics["parseable_first_sets"], 3)
        self.assertIsNone(diagnostics["reason"])

    def test_first_set_parsers_reject_invalid_scores(self):
        self.assertTrue(fetch_data._first_set_winner_is_match_winner("7-6(4) 4-6 6-3"))
        self.assertFalse(fetch_data._first_set_winner_is_match_winner("4-6 6-3 6-2"))
        self.assertIsNone(fetch_data._first_set_winner_is_match_winner("W/O"))
        self.assertIsNone(fetch_data._first_set_winner_from_cols(None, 4))
        self.assertFalse(fetch_data._first_set_winner_from_cols("4", "6"))

    def test_completed_sets_excludes_retirements_and_noise(self):
        self.assertEqual(fetch_data._count_completed_sets("6-4 3-6 7-6(5)"), 3)
        self.assertEqual(fetch_data._count_completed_sets("6-4 3-2 RET"), 0)
        self.assertEqual(fetch_data._count_completed_sets("W/O"), 0)
        self.assertEqual(fetch_data._count_completed_sets(None), 0)

    def test_game_differential_is_factual_and_separates_bo3_bo5(self):
        history = pd.DataFrame([
            {"winner_name": "A", "loser_name": "B", "best_of": "3", "score": "6-0 0-6 7-6(4)"},
            {"winner_name": "C", "loser_name": "A", "best_of": 3, "score": "6-4 6-4"},
            {"winner_name": "A", "loser_name": "D", "best_of": 5, "score": "6-4 6-4 6-4"},
            {"winner_name": "A", "loser_name": "E", "best_of": 3, "score": "6-4 2-1 RET"},
        ])
        profile = fetch_data.compute_game_differential_profile(history, "A")
        self.assertEqual(profile["bo3"]["wins"]["n"], 1)
        self.assertEqual(profile["bo3"]["wins"]["mean"], 1.0)
        self.assertEqual(profile["bo3"]["losses"]["mean"], -4.0)
        self.assertEqual(profile["bo5"]["wins"]["cover_ge"]["6"], 1)

    def test_game_differential_accepts_wta_set_columns_and_ignores_retirements(self):
        history = pd.DataFrame([
            {"winner_name": "A", "loser_name": "B", "best_of": 3,
             "W1": 6, "L1": 4, "W2": 6, "L2": 3, "B365W": 1.32, "B365L": 3.4},
            {"winner_name": "C", "loser_name": "A", "best_of": 3,
             "W1": 6, "L1": 2, "W2": 2, "L2": 1, "B365W": 1.40, "B365L": 3.0},
        ])
        profile = fetch_data.compute_game_differential_profile(history, "A")
        odds = fetch_data.compute_historical_moneyline_margins(history, "A")

        self.assertEqual(profile["bo3"]["wins"]["mean"], 5.0)
        self.assertEqual(profile["bo3"]["losses"]["n"], 0)
        self.assertEqual(odds["odds_columns"], ("B365W", "B365L"))
        self.assertEqual(odds["buckets"]["1.31-1.40"]["n"], 1)
        band = odds["buckets"]["1.31-1.40"]["by_format"]["bo3"]
        self.assertEqual(band["win_margins"], [5])
        self.assertEqual(band["loss_margins"], [])

    def test_game_differential_treats_whitespace_only_unused_sets_as_missing(self):
        history = pd.DataFrame([
            {"winner_name": "A", "loser_name": "B", "best_of": 3,
             "W1": 6, "L1": 4, "W2": 6, "L2": 3, "W3": "\t", "L3": None},
            {"winner_name": "A", "loser_name": "C", "best_of": 3,
             "W1": 6, "L1": 3, "W2": 6, "L2": None},
        ])

        profile = fetch_data.compute_game_differential_profile(history, "A")

        # O primeiro é uma vitória BO3 completa em dois sets; o segundo tem
        # uma coluna de score truncada e deve continuar excluído.
        self.assertEqual(profile["bo3"]["wins"]["n"], 1)
        self.assertEqual(profile["bo3"]["wins"]["margins"], [5])

    def test_game_differential_keeps_a_positive_margin_in_a_loss(self):
        history = pd.DataFrame([
            {"winner_name": "B", "loser_name": "A", "best_of": 3,
             "score": "7-6 0-6 7-6"},
        ])
        profile = fetch_data.compute_game_differential_profile(history, "A")
        self.assertEqual(profile["bo3"]["losses"]["positive"], 1)
        self.assertEqual(profile["bo3"]["losses"]["mean"], 4.0)

    def test_game_differential_keeps_all_equivalent_name_variants(self):
        history = pd.DataFrame([
            {"winner_name": "Alex de Minaur", "loser_name": "Player B",
             "best_of": 3, "score": "6-4 6-4", "B365W": 1.70, "B365L": 2.20},
            {"winner_name": "Player C", "loser_name": "Alex De Minaur",
             "best_of": 3, "score": "6-4 6-4", "B365W": 1.70, "B365L": 2.20},
            {"winner_name": "Álex de Minaur", "loser_name": "Player D",
             "best_of": 3, "score": "6-3 6-3", "B365W": 1.70, "B365L": 2.20},
        ])

        profile = fetch_data.compute_game_differential_profile(
            history, "Alex De Minaur",
        )

        self.assertEqual(profile["bo3"]["analyzable_matches"], 3)
        self.assertEqual(profile["bo3"]["wins"]["n"], 2)
        self.assertEqual(profile["bo3"]["losses"]["n"], 1)
        odds_profile = fetch_data.compute_historical_moneyline_margins(
            history, "Alex De Minaur",
        )
        self.assertEqual(odds_profile["buckets"]["1.61-1.80"]["n"], 2)
        self.assertEqual(odds_profile["buckets"]["2.10-2.30"]["n"], 1)
        margin_profile = fetch_data.compute_game_margin_stats(
            history, "Alex De Minaur",
        )
        self.assertEqual(margin_profile["n_vitorias"], 2)
        self.assertEqual(margin_profile["n_derrotas"], 1)

    def test_game_differential_combines_recent_by_id_and_deduplicates_history(self):
        history = pd.DataFrame([
            {"winner_name": "Alex de Minaur", "loser_name": "Player B",
             "best_of": 3, "score": "6-4 6-4", "tourney_date": 20261001},
            {"winner_name": "Player C", "loser_name": "Alex De Minaur",
             "best_of": 3, "score": "6-4 6-4", "tourney_date": 20261002},
        ])
        recent = [
            {"id": "duplicate", "date": "2026-10-01T12:00:00Z",
             "player1Id": 39309, "player2Id": 2,
             "player1": {"name": "Alex De Minaur"},
             "player2": {"name": "Player B"},
             "match_winner": 39309, "result": "6-4 6-4",
             "result_type": "completed"},
            {"id": "new", "date": "2026-10-03T12:00:00Z",
             "player1Id": 4, "player2Id": 39309,
             "player1": {"name": "Player D"},
             "player2": {"name": "Alex De Minaur"},
             "match_winner": 39309, "result": "4-6 4-6",
             "result_type": "completed"},
            {"id": "retired", "date": "2026-10-04T12:00:00Z",
             "player1Id": 39309, "player2Id": 5,
             "player1": {"name": "Alex De Minaur"},
             "player2": {"name": "Player E"},
             "match_winner": 39309, "result": "6-4 2-1 ret.",
             "result_type": "retired"},
            {"id": "future", "date": "2026-10-06T12:00:00Z",
             "player1Id": 39309, "player2Id": 6,
             "player1": {"name": "Alex De Minaur"},
             "player2": {"name": "Player F"},
             "match_winner": 39309, "result": "6-4 6-4",
             "result_type": "completed"},
        ]

        profile = fetch_data.compute_game_differential_profile(
            history,
            "Alex De Minaur",
            recent_matches=recent,
            player_id=39309,
            before="2026-10-05T00:00:00Z",
        )

        self.assertEqual(profile["bo3"]["analyzable_matches"], 3)
        self.assertEqual(profile["bo3"]["wins"]["n"], 2)
        self.assertEqual(profile["bo3"]["losses"]["n"], 1)
        self.assertEqual(
            profile["bo3"]["source_matches"],
            {"history": 1, "recent_api": 2},
        )

    def test_recent_stats_are_normalized_and_require_first_serve_metric(self):
        stats = {
            "recentStats": {
                "firstServeWinPer": "72.5",
                "secondServeWinPer": 51,
                "bpSavedPer": 64,
                "bpConvertedPer": 42,
                "playerStats": {
                    "statMatchesPlayed": 5,
                    "firstServe": 120,
                    "firstServeOf": 200,
                },
            }
        }

        actual = fetch_data.compute_serve_return_from_recent_stats(stats)

        self.assertEqual(actual["avg_first_serve_won_pct"], 72.5)
        self.assertEqual(actual["avg_first_serve_in_pct"], 60.0)
        self.assertEqual(actual["matches_used"], 5)
        self.assertIsNone(fetch_data.compute_serve_return_from_recent_stats({"recentStats": {}}))

    def test_career_service_is_distinct_from_recent_provider_window(self):
        career = {
            "playerStats": {
                "statMatchesPlayed": 100,
                "winningOnFirstServePercentage": 68,
                "winningOnSecondServe": 240,
                "winningOnSecondServeOf": 500,
                "breakpointsWonPercentage": 43,
                "firstServePercentage": 62,
            }
        }
        actual = fetch_data.compute_serve_return_from_career_stats(career)
        self.assertEqual(actual["matches_used"], 100)
        self.assertEqual(actual["avg_first_serve_won_pct"], 68.0)
        self.assertEqual(actual["avg_second_serve_won_pct"], 48.0)
        self.assertEqual(actual["source"], "rapidapi_career_stats")

    def test_legacy_rich_sheet_recovers_factual_career_service(self):
        rich = {
            "domination": {"own_first_serve_won_pct": 65},
            "style": {"matches_played": 680},
        }
        actual = fetch_data.compute_serve_return_from_rich_stats(rich)
        self.assertEqual(actual["matches_used"], 680)
        self.assertEqual(actual["avg_first_serve_won_pct"], 65.0)
        self.assertEqual(actual["source"], "rapidapi_career_stats_legacy_sheet")

    def test_zero_match_percentages_are_treated_as_missing(self):
        stats = {"recentStats": {
            "firstServeWinPer": 0,
            "bpSavedPer": 0,
            "playerStats": {"statMatchesPlayed": 0},
        }}

        self.assertIsNone(fetch_data.compute_serve_return_from_recent_stats(stats))
        self.assertIsNone(fetch_data.compute_recent_pressure_profile(stats))

    def test_profile_hand_and_matchup_are_resolved_deterministically(self):
        profile = {"data": {"information": {"plays": "Left-handed, two-handed backhand"}}}
        stats = {"vs_left_handed": {"matches": 4, "wins": 3, "losses": 1}}

        hand = fetch_data.compute_hand_from_profile(profile)
        matchup = fetch_data.resolve_handedness_matchup(stats, hand)

        self.assertEqual(hand, "L")
        self.assertEqual(matchup, {"win_pct": 75.0, "matches": 4, "opponent_hand": "L"})
        self.assertIsNone(fetch_data.resolve_handedness_matchup(stats, "R"))

    def test_scenarios_ignore_malformed_matches(self):
        matches = [
            {"player1Id": 1, "player2Id": 2, "match_winner": 1, "result": "4-6 6-3 6-2"},
            {"player1Id": 1, "player2Id": 3, "match_winner": 3, "result": "6-4 3-6 2-6"},
            {"player1Id": 9, "player2Id": 8, "match_winner": 9, "result": "6-0 6-0"},
            {"player1Id": 1, "player2Id": 4, "match_winner": 1, "result": "invalid"},
        ]

        actual = fetch_data.compute_scenarios_from_past_matches(matches, 1)

        self.assertEqual(actual["first_set_lose_then_win_pct"], 100)
        self.assertEqual(actual["first_set_win_then_win_pct"], 0)

    def test_scenarios_filter_strictly_by_declared_format(self):
        matches = [
            {"player1Id": 1, "player2Id": 2, "match_winner": 1,
             "result": "4-6 6-3 6-2", "bestOf": 3},
            {"player1Id": 1, "player2Id": 3, "match_winner": 1,
             "result": "4-6 6-3 6-2 6-4", "bestOf": 5},
            {"player1Id": 1, "player2Id": 4, "match_winner": 4,
             "result": "4-6 3-6 6-3 6-4 4-6", "bestOf": 5},
            {"player1Id": 1, "player2Id": 5, "match_winner": 1,
             "result": "4-6 6-3 6-2"},
        ]
        actual = fetch_data.compute_scenarios_from_past_matches(
            matches, 1, expected_best_of=5,
        )
        self.assertEqual(actual["first_set_lose_count"], 2)
        self.assertEqual(actual["first_set_lose_then_win_pct"], 50)

    def test_deciding_set_stats_normalizes_string_best_of_values(self):
        history = pd.DataFrame([
            {"winner_name": "A", "loser_name": "B", "best_of": "5",
             "score": "6-4 3-6 6-3 4-6 6-2"},
            {"winner_name": "C", "loser_name": "A", "best_of": "3",
             "score": "6-4 3-6 6-2"},
        ])

        actual = fetch_data.compute_deciding_set_stats(history, "A")

        self.assertEqual(actual["bo5"]["matches_went_the_distance"], 1)
        self.assertEqual(actual["bo5"]["win_rate_pct"], 100.0)
        self.assertEqual(actual["bo3"]["matches_went_the_distance"], 1)

    def test_layoff_uses_only_the_requested_player_and_valid_dates(self):
        matches = [
            {"player1Id": 1, "player2Id": 2, "date": "2026-08-10T00:00:00Z"},
            {"player1Id": 3, "player2Id": 1, "date": "2026-07-01T00:00:00Z"},
            {"player1Id": 8, "player2Id": 9, "date": "2025-01-01T00:00:00Z"},
            {"player1Id": 1, "player2Id": 4, "date": "not-a-date"},
        ]

        actual = fetch_data.compute_layoff_from_past_matches(
            matches,
            1,
            datetime(2026, 8, 15, tzinfo=timezone.utc),
        )

        self.assertEqual(actual, {"days_since_last_match": 5, "days_out": 40})

    def test_market_adjusted_form_removes_margin_and_uses_player_side(self):
        matches = [
            {"date": "2026-08-03", "player1Id": 1, "player2Id": 2,
             "match_winner": 1, "odd1": "2.0", "odd2": "2.0"},
            {"date": "2026-08-02", "player1Id": 3, "player2Id": 1,
             "match_winner": 3, "odd1": "1.5", "odd2": "3.0"},
            {"date": "2026-08-01", "player1Id": 1, "player2Id": 4,
             "match_winner": 1, "odd1": None, "odd2": "2.0"},
        ]

        actual = fetch_data.compute_market_adjusted_form(matches, 1)

        self.assertEqual(actual["matches"], 2)
        self.assertEqual(actual["actual_wins"], 1)
        self.assertEqual(actual["overall_wins"], 2)
        self.assertEqual(actual["total_recent_matches"], 3)
        self.assertEqual(actual["excluded_missing_odds"], 1)
        self.assertEqual(actual["excluded_missing_odds_wins"], 1)
        self.assertEqual(actual["coverage_pct"], 66.7)
        self.assertEqual(actual["expected_wins"], 0.83)
        self.assertEqual(actual["performance_vs_market"], 0.17)
        self.assertEqual(actual["sample_status"], "limitado")

    def test_market_adjusted_form_keeps_results_when_no_odds_are_available(self):
        matches = [
            {"player1Id": 1, "player2Id": 2, "match_winner": 1},
            {"player1Id": 3, "player2Id": 1, "match_winner": 3},
        ]
        actual = fetch_data.compute_market_adjusted_form(matches, 1)
        self.assertEqual(actual["total_recent_matches"], 2)
        self.assertEqual(actual["overall_wins"], 1)
        self.assertEqual(actual["odds_eligible_matches"], 0)
        self.assertEqual(actual["excluded_missing_odds"], 2)
        self.assertIsNone(actual["expected_wins"])
        self.assertIsNone(actual["performance_vs_market"])

    def test_opposition_quality_preserves_rank_and_sample(self):
        stats = {"yearStats": {"avgOppRank": "42.5", "matchesPlayed": "24"}}
        self.assertEqual(
            fetch_data.compute_opposition_quality(stats),
            {"avg_opponent_rank": 42.5, "matches": 24, "sample_status": "robusto"},
        )
        self.assertIsNone(fetch_data.compute_opposition_quality({"yearStats": {}}))

    def test_recent_pressure_profile_preserves_components_without_fake_score(self):
        stats = {"recentStats": {
            "firstServeWinPer": 72, "secondServeWinPer": 51,
            "bpSavedPer": 64, "bpConvertedPer": 42,
            "oppFirstServeWinPer": 66, "oppSecondServeWinPer": 45,
            "playerStats": {"statMatchesPlayed": 12},
            "opponentStats": {"statMatchesPlayed": 12},
        }}
        actual = fetch_data.compute_recent_pressure_profile(stats)
        self.assertEqual(actual["matches"], 12)
        self.assertEqual(actual["first_serve_won_pct"], 72.0)
        self.assertEqual(actual["opponent_second_serve_won_pct"], 45.0)
        self.assertNotIn("score", actual)
        self.assertEqual(actual["sample_status"], "robusto")

    def test_surface_momentum_compares_recent_years_with_career(self):
        perf = {
            "by_surface": {"hard": {"matches": 100, "win_pct": 60.0}},
            "by_year": {
                "2025": {"court": {"1": {"aw": 6, "al": 4}}},
                "2026": {"court": {"1": {"aw": 8, "al": 2}}},
                "2024": {"court": {"1": {"aw": 1, "al": 9}}},
            },
        }
        actual = fetch_data.compute_surface_momentum(perf, "Hard", 2026)
        self.assertEqual(actual["recent_win_pct"], 70.0)
        self.assertEqual(actual["delta_pp"], 10.0)
        self.assertEqual(actual["years"], [2025, 2026])
        self.assertEqual(actual["sample_status"], "robusto")
        self.assertIsNone(fetch_data.compute_surface_momentum(perf, "Grass", 2026))


if __name__ == "__main__":
    unittest.main()
