import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from src import fetch_data, main


class MatchInputTests(unittest.TestCase):
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


class DeterministicStatisticTests(unittest.TestCase):
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

    def test_recent_stats_are_normalized_and_require_first_serve_metric(self):
        stats = {
            "recentStats": {
                "firstServeWinPer": "72.5",
                "secondServeWinPer": 51,
                "bpSavedPer": 64,
                "bpConvertedPer": 42,
                "playerStats": {"firstServe": 120, "firstServeOf": 200},
            }
        }

        actual = fetch_data.compute_serve_return_from_recent_stats(stats)

        self.assertEqual(actual["avg_first_serve_won_pct"], 72.5)
        self.assertEqual(actual["avg_first_serve_in_pct"], 60.0)
        self.assertIsNone(fetch_data.compute_serve_return_from_recent_stats({"recentStats": {}}))

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


if __name__ == "__main__":
    unittest.main()
