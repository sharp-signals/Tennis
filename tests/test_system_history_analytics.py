import unittest

from src.system_history_analytics import (
    build_system_history,
    canonical_snapshots,
    historical_wta_analytics,
    odds_band,
)


def _snapshot(*, analyzed_at, winner="a", key="atp:10", odd_a=1.4, odd_b=3.0):
    return {
        "key": key,
        "match_id": 10,
        "tour": "atp",
        "commence_time_utc": "2026-09-29T12:00:00+00:00",
        "analyzed_at_utc": analyzed_at,
        "player_a": {"id": 1, "name": "A"},
        "player_b": {"id": 2, "name": "B"},
        "market_odds_decimal": {"A": odd_a, "B": odd_b},
        "metrics": {"divergencia": {"indice_favorece": "A"}},
        "outcome": {"winner_side": winner, "result": "6-4 6-4"},
    }


class SystemHistoryAnalyticsTests(unittest.TestCase):
    def test_canonical_snapshot_keeps_the_first_observation_not_repeat(self):
        first = _snapshot(analyzed_at="2026-09-28T06:30:00+00:00", odd_a=1.4)
        later = _snapshot(analyzed_at="2026-09-28T18:30:00+00:00", odd_a=1.2)
        selected, excluded = canonical_snapshots([later, first])
        self.assertEqual(excluded, 1)
        self.assertEqual(selected, [first])

    def test_event_identity_does_not_merge_provider_id_reused_for_other_players(self):
        original = _snapshot(analyzed_at="2026-09-28T06:30:00+00:00")
        reused = _snapshot(analyzed_at="2026-09-28T06:31:00+00:00")
        reused["player_a"] = {"id": 3, "name": "C"}
        reused["player_b"] = {"id": 4, "name": "D"}
        reused["market_odds_decimal"] = {"C": 1.8, "D": 2.0}
        selected, excluded = canonical_snapshots([original, reused])
        self.assertEqual(len(selected), 2)
        self.assertEqual(excluded, 0)

    def test_odds_bands_use_explicit_boundaries(self):
        self.assertEqual(odds_band(1.20), "1.01–1.20")
        self.assertEqual(odds_band(1.21), "1.21–1.30")
        self.assertEqual(odds_band(1.75), "1.61–1.75")
        self.assertEqual(odds_band(1.76), "1.76–2.00")

    def test_wta_reference_handicap_and_recovery_are_clearly_separate(self):
        matches = [{
            "winner": "A", "loser": "B", "winner_odd": 1.25, "loser_odd": 4.0,
            "winner_games": 12, "loser_games": 4, "winner_lost_first": True,
            "deciding_set": True, "winner_tiebreak": False,
        }]
        analytics = historical_wta_analytics(matches)
        favourite_line = next(row for row in analytics["handicap_reference"] if row["player"] == "A" and row["reference_line"] == -4.5)
        underdog_line = next(row for row in analytics["handicap_reference"] if row["player"] == "B" and row["reference_line"] == 4.5)
        self.assertEqual(favourite_line["covers"], 1)
        self.assertEqual(underdog_line["fails"], 1)
        self.assertEqual(analytics["set1_recovery"], [{"player": "A", "lost_first": 1, "recovered": 1, "recovery_pct": 100.0}])

    def test_output_separates_raw_and_canonical_counts(self):
        payload = build_system_history({"snapshots": [_snapshot(analyzed_at="2026-09-28T06:30:00+00:00"), _snapshot(analyzed_at="2026-09-28T18:30:00+00:00")]}, [])
        self.assertEqual(payload["summary"]["raw_snapshots"], 2)
        self.assertEqual(payload["summary"]["canonical_snapshots"], 1)
        self.assertEqual(payload["summary"]["duplicate_snapshots_excluded"], 1)
