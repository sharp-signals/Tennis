"""Regression guard for the approved PR120/PR121 integration."""
import copy
import unittest
from src import report_html


class AuditIntegrationTests(unittest.TestCase):
    def test_pr121_diagnostic_remains_visible_without_mutating_decision(self):
        payload = {"prelive_decision": {
  "state": "PRICING_UNAVAILABLE",
  "reason": "event_identity_unavailable",
  "coverage": {"weighted_pct": 85.4, "status": "reduzida"},
        }}
        original = copy.deepcopy(payload)
        html = report_html._mod_decision_box(payload)
        self.assertIn("associado com segurança aos dois jogadores", html)
        self.assertIn("edge e PAPER bloqueados", html)
        self.assertEqual(payload, original)

    def test_pr120_operational_coverage_remains_explicit(self):
        payload = {"prelive_decision": {
  "state": "EDGE_POSITIVE", "player": "A",
  "fenzobot_index": 80, "expected_edge_pct": 2.0,
  "market": {"market": "Moneyline A", "odd": 1.8},
  "coverage": {"weighted_pct": 85.4, "status": "reduzida"},
        }}
        original = copy.deepcopy(payload)
        html = report_html._mod_decision_box(payload)
        self.assertIn("Cobertura ponderada operacional", html)
        self.assertIn("Entrada PAPER automática", html)
        self.assertEqual(payload, original)
