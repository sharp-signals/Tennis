import unittest

from scripts import audit_rapidapi_odds


class RapidApiOddsAuditTests(unittest.TestCase):
    def test_matching_upcoming_event_requires_both_full_names(self):
        payload = {
            "matches": [
                {"player1": {"name": "Alex Smith"}, "player2": {"name": "Bea Jones"}},
                {"player1": {"name": "Alice Smith"}, "player2": {"name": "Bea Jones"}, "odds": {"k1": 1.3, "k2": 3.7}},
            ]
        }
        actual = audit_rapidapi_odds._matching_upcoming_event(payload, "Alice Smith", "Bea Jones")
        self.assertEqual(actual["odds"], {"k1": 1.3, "k2": 3.7})

    def test_event_id_does_not_confuse_player_or_market_ids(self):
        payload = {
            "playerId": 42,
            "marketId": 1,
            "result": {"id": "event-7", "participant1": "A", "participant2": "B", "status": "scheduled"},
        }
        self.assertEqual(audit_rapidapi_odds._event_id(payload), "event-7")

    def test_market_integrity_available_is_compatible(self):
        provenance = {"market_integrity": {"status": "AVAILABLE"}}
        self.assertTrue(audit_rapidapi_odds._market_integrity_compatible(provenance))
        self.assertFalse(audit_rapidapi_odds._market_integrity_compatible(None))

    def test_audit_match_keeps_tournament_name_for_optional_source_probe(self):
        match = audit_rapidapi_odds._match_from_audit_input(
            player_a="Cori Gauff", player_b="Elena Rybakina",
            event_date="2026-09-10", tour="wta",
            player_a_id=54663, player_b_id=36558,
            tournament_id=None, round_id=None,
            upcoming_match={
                "date": "2026-09-11T00:30:00Z",
                "tournament": {"id": 16743, "name": "U.S. Open - New York"},
            },
        )
        self.assertEqual(match["tournament_name"], "U.S. Open - New York")
