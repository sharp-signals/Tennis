from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import (
    calibration_store,
    competition_evidence,
    main,
    prelive_decision,
    pricing,
    report_html,
)


ACTIVE = {
    "active": True,
    "version": competition_evidence.POLICY_VERSION,
    "config_hash": competition_evidence.CONFIG_HASH,
    "status": "ACTIVE",
    "effective_from_utc": "2026-10-10T00:00:00+00:00",
    "tour": "atp",
}


def _policy_with_blockers(*features: str) -> dict:
    policy = competition_evidence.policy_metadata(ACTIVE)
    policy["feature_blockers"] = [
        {
            "feature": feature,
            "impact": "DECISION_FACTOR_BLOCKED",
            "reason_code": "COMPETITION_EVIDENCE_NOT_SEPARABLE",
        }
        for feature in features
    ]
    return policy


class ConsumptionBoundaryIntegrationTests(unittest.TestCase):
    def _payload(self, reverse: bool = False) -> dict:
        high, low = ((15, 90) if reverse else (90, 15))
        return {
            "tour": "atp",
            "player_a": "Alpha",
            "player_b": "Beta",
            "ranking_a": {"rank": 10},
            "ranking_b": {"rank": 40},
            "market_odds_decimal": {"Alpha": 1.9, "Beta": 2.0},
            "features": {
                "ranking": {
                    "lider": "Alpha",
                    "diff": 30,
                    "valor_a": 10,
                    "valor_b": 40,
                }
            },
            "rich_stats_a": {
                "scenarios": {
                    "deciding_set_win_pct": high,
                    "deciding_set_count": 30,
                    "first_set_win_then_win_pct": high,
                }
            },
            "rich_stats_b": {
                "scenarios": {
                    "deciding_set_win_pct": low,
                    "deciding_set_count": 30,
                    "first_set_lose_then_win_pct": low,
                }
            },
            "handedness_matchup_a": {
                "win_pct": high,
                "opponent_hand": "L",
            },
            "handedness_matchup_b": {
                "win_pct": low,
                "opponent_hand": "R",
            },
            "tournament_record_a": {
                "edicoes": 5,
                "win_pct_ponderado": high,
            },
            "tournament_record_b": {
                "edicoes": 5,
                "win_pct_ponderado": low,
            },
            "competition_evidence_policy": _policy_with_blockers(
                "recuperacao_sets", "matchup_maos", "historico_torneio",
                "comeback_set1",
            ),
        }

    def test_blocked_raw_aggregates_cannot_reenter_index_pricing_or_decision(self):
        left = self._payload(False)
        right = self._payload(True)
        left_div = report_html.calcular_divergencia_publico(left)
        right_div = report_html.calcular_divergencia_publico(right)

        self.assertEqual(left_div["indice_evidencia_a"], right_div["indice_evidencia_a"])
        self.assertEqual(left_div["fatores_chave"], right_div["fatores_chave"])
        for factor in ("recuperacao_sets", "matchup_maos", "historico_torneio"):
            self.assertFalse(left_div["fatores_status"][factor]["disponivel"])
            self.assertEqual(
                left_div["fatores_status"][factor]["motivo_exclusao"],
                "COMPETITION_EVIDENCE_NOT_SEPARABLE",
            )

        with patch.object(
            pricing.market_integrity,
            "is_operational_pricing_payload",
            return_value=True,
        ):
            left_pricing = pricing.estimate_market_residual_pricing(left, left_div)
            right_pricing = pricing.estimate_market_residual_pricing(right, right_div)
        self.assertEqual(left_pricing, right_pricing)

        assessment = {"report_null": False, "coverage": {}}
        self.assertEqual(
            prelive_decision.build_decision(
                left, left_div, left_pricing, assessment
            ),
            prelive_decision.build_decision(
                right, right_div, right_pricing, assessment
            ),
        )
        self.assertFalse(
            any("fecha" in point or "recupera" in point
                for point in main._factual_key_points(left))
        )

    def test_factor_matrix_preserves_data_and_records_impact(self):
        features = {
            "servico_carreira": {"lider": "Alpha"},
            "ranking": {"lider": "Alpha"},
        }
        guarded, blockers = competition_evidence.guard_features(
            features, active=True, tour="atp"
        )
        self.assertEqual(guarded, features)
        self.assertIn(
            "servico_carreira", {item["feature"] for item in blockers}
        )
        matrix = competition_evidence.factor_impact_matrix(
            guarded, active=True, tour="atp"
        )
        service = next(
            item for item in matrix if item["feature"] == "servico_carreira"
        )
        self.assertEqual(service["impact"], "DECISION_FACTOR_BLOCKED")
        self.assertEqual(service["report_factual_display"], "PRESERVED")


class CanonicalCutoverIntegrationTests(unittest.TestCase):
    def test_existing_canonical_snapshot_preserves_runtime_artifacts(self):
        identity = {
            "canonical_match_instance_id": "cmiv2:abc",
            "identity_persisted": True,
        }
        snapshot = {
            "key": "cmiv2:abc",
            "canonical_match_instance_id": "cmiv2:abc",
            "report_id": "original-report",
            "tour": "atp",
            "tournament_id": "77",
            "player_a": {"id": 10, "name": "Alpha"},
            "player_b": {"id": 20, "name": "Beta"},
            "commence_time_utc": "2026-10-20T12:00:00+00:00",
            "market_odds_decimal": {"Alpha": 1.8, "Beta": 2.1},
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot_path = root / "snapshots.json"
            report_path = root / "report-original.html"
            paper_path = root / "paper.json"
            snapshot_path.write_text(
                json.dumps({
                    "schema_version": calibration_store.SCHEMA_VERSION,
                    "snapshots": [snapshot],
                }),
                encoding="utf-8",
            )
            report_path.write_text("ORIGINAL HTML", encoding="utf-8")
            paper_path.write_text('{"entries":[{"id":"original"}]}', encoding="utf-8")
            before = {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in (snapshot_path, report_path, paper_path)
            }
            persisted = calibration_store.read_snapshots_by_key(
                ["cmiv2:abc"], path=snapshot_path
            )["cmiv2:abc"]

            # A/B inversion, reschedule and changed odds are deliberately not
            # inputs to the cutover identity decision.
            gate = competition_evidence.canonical_cutover_gate(
                identity,
                activation=ACTIVE,
                tour="atp",
                tournament_id=77,
                player_ids=(20, 10),
                persisted_snapshot=persisted,
            )
            self.assertTrue(gate["skip_new_decision"])
            self.assertFalse(gate["apply_policy"])
            self.assertEqual(
                gate["reason_code"],
                "CANONICAL_MATCH_ALREADY_HAS_PREGAME_SNAPSHOT",
            )
            after = {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in (snapshot_path, report_path, paper_path)
            }
            self.assertEqual(before, after)

    def test_new_canonical_match_is_prospective_policy_target(self):
        gate = competition_evidence.canonical_cutover_gate(
            {
                "canonical_match_instance_id": "cmiv2:new",
                "identity_persisted": True,
            },
            activation=ACTIVE,
            tour="atp",
            tournament_id=88,
            player_ids=(11, 22),
            persisted_snapshot=None,
        )
        self.assertTrue(gate["apply_policy"])
        self.assertEqual(gate["status"], "NEW_CANONICAL_MATCH")

    def test_context_collision_fails_closed(self):
        gate = competition_evidence.canonical_cutover_gate(
            {
                "canonical_match_instance_id": "cmiv2:abc",
                "identity_persisted": True,
            },
            activation=ACTIVE,
            tour="atp",
            tournament_id=77,
            player_ids=(10, 99),
            persisted_snapshot={
                "key": "cmiv2:abc",
                "tour": "atp",
                "tournament_id": 77,
                "player_a": {"id": 10},
                "player_b": {"id": 20},
            },
        )
        self.assertTrue(gate["fail_closed"])


class ScopeAndUnknownCompetitionIntegrationTests(unittest.TestCase):
    def test_wta_and_inactive_controls_are_unchanged(self):
        wta = competition_evidence.activation_for_tour(ACTIVE, "wta")
        self.assertFalse(wta["active"])
        features = {"servico_carreira": {"lider": "A"}}
        self.assertEqual(
            competition_evidence.guard_features(
                features, active=wta["active"], tour="wta"
            ),
            (features, []),
        )
        inactive = {**ACTIVE, "active": False}
        self.assertEqual(
            competition_evidence.guard_features(
                features, active=inactive["active"], tour="atp"
            ),
            (features, []),
        )

    def test_clean_atp_match_level_factor_has_active_inactive_parity(self):
        a = competition_evidence.weighted_binary_record(
            [{"id": 1, "tournament_name": "Vienna Open", "won": True}],
            lambda row: row["won"],
            active=True,
        )
        b = competition_evidence.weighted_binary_record(
            [{"id": 2, "tournament_name": "Vienna Open", "won": False}],
            lambda row: row["won"],
            active=True,
        )
        feature = {
            "lider": "A", "diff": 100, "valor_a": 100, "valor_b": 0,
            "amostra_a": 1, "amostra_b": 1,
        }
        competition_evidence.annotate_feature(
            feature, [a, b], active=True
        )
        features = {"forma_recente": feature}
        guarded, blockers = competition_evidence.guard_features(
            features, active=True, tour="atp"
        )
        self.assertEqual(guarded, features)
        self.assertEqual(blockers, [])

        active_payload = {
            "tour": "atp", "player_a": "A", "player_b": "B",
            "features": copy.deepcopy(features),
            "competition_evidence_policy": {
                **competition_evidence.policy_metadata(ACTIVE),
                "feature_blockers": [],
            },
        }
        inactive_payload = copy.deepcopy(active_payload)
        inactive_payload["competition_evidence_policy"]["active"] = False
        self.assertEqual(
            report_html.calcular_divergencia_publico(active_payload)[
                "indice_evidencia_a"
            ],
            report_html.calcular_divergencia_publico(inactive_payload)[
                "indice_evidencia_a"
            ],
        )

    def test_unknown_and_generic_competitions_never_receive_weight_one(self):
        cases = [
            {},
            {"tournamentId": "999999"},
            {"tournament": {"rankId": 5}},
            {"tournament_name": "International Cup"},
        ]
        for row in cases:
            with self.subTest(row=row):
                result = competition_evidence.classify_match(row)
                self.assertIsNone(result["weight"])
                self.assertEqual(result["status"], "BLOCKED")

    def test_laver_reentry_variants_are_all_zero_and_unknown_blocks(self):
        rows = [
            {"id": 1, "tournament_name": "Laver Cup", "won": True},
            {"id": 2, "tournament": {"name": "Laver Cup"}, "won": True},
            {"id": 3, "tournamentId": 21353, "won": True},
        ]
        result = competition_evidence.weighted_binary_record(
            rows, lambda row: row["won"], active=True
        )
        self.assertEqual(result["weighted_matches"], 0.0)
        self.assertEqual(
            result["competition_evidence"]["laver_excluded"], 3
        )
        unresolved = competition_evidence.weighted_binary_record(
            [{"id": 4, "tournamentId": 999, "won": True}],
            lambda row: row["won"],
            active=True,
        )
        self.assertIsNone(unresolved["weighted_matches"])
        self.assertEqual(
            unresolved["competition_evidence"]["blocker_reason_counts"],
            {"COMPETITION_IDENTITY_UNRESOLVED": 1},
        )


if __name__ == "__main__":
    unittest.main()
