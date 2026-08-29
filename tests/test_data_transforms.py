import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd

from src import fetch_data, main


class MatchInputTests(unittest.TestCase):
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

    def test_the_odds_pricing_requires_fresh_named_bookmaker_pair(self):
        match = {"player1": {"name": "Alice Player"}, "player2": {"name": "Bea Player"}, "_tour": "atp"}
        event = {
            "id": "event-1", "participants": ["Alice Player", "Bea Player"],
            "bookmakers": [{
                "title": "Test Book", "last_update": datetime.now(timezone.utc).isoformat(),
                "markets": [{"key": "h2h", "outcomes": [
                    {"name": "Alice Player", "price": 1.70}, {"name": "Bea Player", "price": 2.20},
                ]}],
            }],
        }
        with patch.object(fetch_data, "_the_odds_event_for_match", return_value=event):
            odds, provenance = fetch_data.fetch_the_odds_moneyline_with_provenance(match)
        self.assertEqual(odds, {"Alice Player": 1.70, "Bea Player": 2.20})
        self.assertEqual(provenance["bookmaker"], "Test Book")
        self.assertEqual(provenance["capture_kind"], "provider_last_update_verified")

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

    def test_explicit_override_includes_only_the_forced_atp_250(self):
        matches = [
            {"id": 1, "tournamentId": 21348, "_tour": "atp"},
            {"id": 2, "tournamentId": 99999, "_tour": "atp"},
        ]
        responses = {
            21348: {"name": "Winston-Salem Open", "surface": "Hard", "tier": "ATP 250"},
            99999: {"name": "Outro ATP 250", "surface": "Hard", "tier": "ATP 250"},
        }
        with patch.object(main, "FORCED_TOURNAMENT_IDS", {21348: "atp"}), \
             patch.object(main.fetch_data, "get_tournament_info",
                          side_effect=lambda tournament_id, _tour: responses[tournament_id]):
            actual = main._filter_and_enrich_with_tournament_info(matches)

        self.assertEqual([match["id"] for match in actual], [1])
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


class DeterministicStatisticTests(unittest.TestCase):
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

    def test_game_differential_keeps_a_positive_margin_in_a_loss(self):
        history = pd.DataFrame([
            {"winner_name": "B", "loser_name": "A", "best_of": 3,
             "score": "7-6 0-6 7-6"},
        ])
        profile = fetch_data.compute_game_differential_profile(history, "A")
        self.assertEqual(profile["bo3"]["losses"]["positive"], 1)
        self.assertEqual(profile["bo3"]["losses"]["mean"], 4.0)

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
