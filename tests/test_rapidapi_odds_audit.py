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
