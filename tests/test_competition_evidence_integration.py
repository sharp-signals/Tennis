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
    match_identity_v2,
    paper_trading,
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
        for payload in (left, right):
            direct = competition_evidence.direct_consumers_from_payload(payload)
            _, blockers = competition_evidence.guard_features(
                payload["features"],
                active=True,
                tour="atp",
                direct_consumers=direct,
            )
            payload["competition_evidence_policy"]["feature_blockers"] = blockers
            self.assertTrue(
                {"recuperacao_sets", "matchup_maos", "historico_torneio"}
                .issubset({item["feature"] for item in blockers})
            )
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


class ActiveRuntimeIntegrationTests(unittest.TestCase):
    @staticmethod
    def _record(wins: int, matches: int, prefix: str) -> dict:
        rows = [
            {
                "id": f"{prefix}-{index}",
                "tournament_name": "Vienna Open",
                "won": index < wins,
            }
            for index in range(matches)
        ]
        return competition_evidence.weighted_binary_record(
            rows, lambda row: row["won"], active=True
        )

    def _payload(self, reverse_raw: bool = False) -> dict:
        strong = self._record(8, 10, "strong")
        weak = self._record(3, 10, "weak")
        service_a = {
            "matches_used": 10,
            "avg_first_serve_won_pct": 0.68,
            "weighted_matches_used": 10.0,
            "weighted_avg_first_serve_won_pct": 0.68,
            "competition_evidence": copy.deepcopy(
                strong["competition_evidence"]
            ),
        }
        service_b = {
            "matches_used": 10,
            "avg_first_serve_won_pct": 0.59,
            "weighted_matches_used": 10.0,
            "weighted_avg_first_serve_won_pct": 0.59,
            "competition_evidence": copy.deepcopy(
                weak["competition_evidence"]
            ),
        }
        quality_a = {
            "matches": 10, "score": 9, "weighted_score": 9.0,
            "competition_evidence": copy.deepcopy(
                strong["competition_evidence"]
            ),
        }
        quality_b = {
            "matches": 10, "score": 2, "weighted_score": 2.0,
            "competition_evidence": copy.deepcopy(
                weak["competition_evidence"]
            ),
        }
        high, low = ((12, 91) if reverse_raw else (91, 12))
        policy = competition_evidence.policy_metadata(ACTIVE)
        return {
            "tour": "atp",
            "player_a": "Alpha",
            "player_b": "Beta",
            "player_a_id": 10,
            "player_b_id": 20,
            "ranking_a": {"rank": 10, "points": 3000},
            "ranking_b": {"rank": 40, "points": 1100},
            "ranking_evolution_a": {"change_6m_pct": 20, "change_12m_pct": 18},
            "ranking_evolution_b": {"change_6m_pct": -4, "change_12m_pct": -2},
            "market_odds_decimal": {"Alpha": 2.05, "Beta": 1.80},
            "surface": "Hard",
            "fatigue_signal_a": {
                "fatigue_source": "api_recent",
                "matches_last_7d": 1,
                "sets_last_7d": 2,
                "last_match_sets": 2,
                "days_since_last_match": 5,
            },
            "fatigue_signal_b": {
                "fatigue_source": "api_recent",
                "matches_last_7d": 3,
                "sets_last_7d": 7,
                "last_match_sets": 3,
                "days_since_last_match": 8,
            },
            "surface_transition_a": {
                "em_transicao": False,
                "piso_recente_dominante": "hard",
            },
            "surface_transition_b": {
                "em_transicao": True,
                "piso_recente_dominante": "clay",
            },
            "recent_form_a": copy.deepcopy(strong),
            "recent_form_b": copy.deepcopy(weak),
            "recent_quality_a": quality_a,
            "recent_quality_b": quality_b,
            "indoor_outdoor_a": {"outdoor": copy.deepcopy(strong)},
            "indoor_outdoor_b": {"outdoor": copy.deepcopy(weak)},
            "sazonal_a": copy.deepcopy(strong),
            "sazonal_b": copy.deepcopy(weak),
            "surface_stats_a": {"Hard": copy.deepcopy(strong)},
            "surface_stats_b": {"Hard": copy.deepcopy(weak)},
            "court_speed_hoje": {"status": "available"},
            "court_speed_a": {
                **copy.deepcopy(strong), "eligible_for_index": True,
            },
            "court_speed_b": {
                **copy.deepcopy(weak), "eligible_for_index": True,
            },
            "serve_return_stats_a": service_a,
            "serve_return_stats_b": service_b,
            "serve_return_recent_a": copy.deepcopy(service_a),
            "serve_return_recent_b": copy.deepcopy(service_b),
            "h2h": {
                "overall": {
                    "a_wins": 3, "b_wins": 1, "total_matches": 4,
                    "weighted_a_wins": 3.0, "weighted_b_wins": 1.0,
                    "weighted_total_matches": 4.0,
                    "competition_evidence": copy.deepcopy(
                        strong["competition_evidence"]
                    ),
                },
                "on_surface": {
                    "a_wins": 2, "b_wins": 1, "total_matches": 3,
                    "weighted_a_wins": 2.0, "weighted_b_wins": 1.0,
                    "weighted_total_matches": 3.0,
                    "competition_evidence": copy.deepcopy(
                        strong["competition_evidence"]
                    ),
                },
            },
            "rich_stats_a": {"scenarios": {
                "deciding_set_win_pct": high, "deciding_set_count": 30,
                "first_set_lose_then_win_pct": high,
                "first_set_lose_count": 20,
            }},
            "rich_stats_b": {"scenarios": {
                "deciding_set_win_pct": low, "deciding_set_count": 30,
                "first_set_lose_then_win_pct": low,
                "first_set_lose_count": 20,
            }},
            "competition_evidence_policy": policy,
        }

    @staticmethod
    def _pricing() -> dict:
        return {
            "available": True,
            "players": {
                "a": {
                    "market_odd": 2.05, "fair_odd": 1.80,
                    "sharp_estimate_pct": 55.6, "expected_edge_pct": 13.9,
                },
                "b": {
                    "market_odd": 1.80, "fair_odd": 2.25,
                    "sharp_estimate_pct": 44.4, "expected_edge_pct": -20.0,
                },
            },
        }

    def test_active_atp_reaches_report_and_paper_gates_with_real_consumers(self):
        payload = self._payload()
        payload["features"] = main._compute_features(payload)
        divergence = report_html.calcular_divergencia_publico(payload)
        assessment = prelive_decision.assess_report(payload, divergence)
        decision = prelive_decision.build_decision(
            payload, divergence, self._pricing(), assessment
        )
        payload.update({
            "divergencia": divergence,
            "report_assessment": assessment,
            "prelive_decision": decision,
            "pricing": self._pricing(),
        })

        self.assertFalse(assessment["report_null"])
        self.assertGreaterEqual(assessment["coverage"]["weighted_ratio"], 0.60)
        self.assertTrue(assessment["essential_blocks"]["service_return_bilateral"])
        self.assertTrue(assessment["essential_blocks"]["action_map"])
        self.assertTrue(decision["paper_eligible"])

        html = report_html.build_report_html(payload, {"flag": "🟢"})
        self.assertIn("Mapa de Ações", html)
        self.assertNotIn("Recupera e ganha o jogo", html)
        self.assertNotIn("se chegar ao set decisivo", html)

    def test_blocked_action_sources_cannot_change_decision_or_action_html(self):
        payloads = [self._payload(False), self._payload(True)]
        outputs = []
        for payload in payloads:
            payload["features"] = main._compute_features(payload)
            divergence = report_html.calcular_divergencia_publico(payload)
            assessment = prelive_decision.assess_report(payload, divergence)
            decision = prelive_decision.build_decision(
                payload, divergence, self._pricing(), assessment
            )
            payload.update({
                "divergencia": divergence,
                "report_assessment": assessment,
                "prelive_decision": decision,
                "pricing": self._pricing(),
            })
            outputs.append((
                divergence["indice_evidencia_a"],
                decision,
                report_html._mod_action_map(payload, divergence, {"flag": "🟢"}),
            ))
        self.assertEqual(outputs[0], outputs[1])
        self.assertNotIn("Recupera e ganha o jogo", outputs[0][2])
        self.assertNotIn("se chegar ao set decisivo", outputs[0][2])


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


    def test_partial_first_delivery_recovers_only_from_frozen_snapshot(self):
        builder = ActiveRuntimeIntegrationTests()
        payload = builder._payload()
        payload.update({
            "identity_schema_version": match_identity_v2.SCHEMA_VERSION,
            "identity_status": match_identity_v2.CANONICAL_STRONG,
            "identity_persisted": True,
            "canonical_match_instance_id": "cmiv2:recover",
            "match_id": 501,
            "tournament_id": 77,
            "tournament": "Vienna Open",
            "tier": "ATP 500",
            "commence_time_utc": "2026-10-20T12:00:00+00:00",
        })
        payload["features"] = main._compute_features(payload)
        divergence = report_html.calcular_divergencia_publico(payload)
        assessment = prelive_decision.assess_report(payload, divergence)
        decision = prelive_decision.build_decision(
            payload, divergence, builder._pricing(), assessment
        )
        payload.update({
            "divergencia": divergence,
            "report_assessment": assessment,
            "prelive_decision": decision,
            "pricing": builder._pricing(),
        })
        snapshot = calibration_store.build_snapshot(
            payload, {"flag": "🟢"},
            analyzed_at_utc="2026-10-10T12:00:00+00:00",
        )
        payload.update({
            "snapshot_key": snapshot["key"],
            "report_id": snapshot["report_id"],
            "analyzed_at_utc": snapshot["analyzed_at_utc"],
        })
        main._freeze_competition_delivery(snapshot, payload, {"flag": "🟢"})
        self.assertIn("delivery_recovery", snapshot)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot_path = root / "snapshots.json"
            paper_path = root / "paper.json"
            report_path = root / "report.html"
            self.assertEqual(
                calibration_store.upsert_snapshots(
                    [snapshot], path=snapshot_path, max_entries=None
                ),
                1,
            )
            persisted = calibration_store.read_snapshots_by_key(
                ["cmiv2:recover"], path=snapshot_path
            )["cmiv2:recover"]
            gate = competition_evidence.canonical_cutover_gate(
                {
                    "canonical_match_instance_id": "cmiv2:recover",
                    "identity_persisted": True,
                },
                activation=ACTIVE,
                tour="atp",
                tournament_id=77,
                player_ids=(20, 10),
                persisted_snapshot=persisted,
            )
            self.assertTrue(gate["recover_frozen_delivery"])

            # A second runner has only the durable snapshot. Changed schedule
            # and odds never enter the recovered delivery.
            carrier = {
                "_competition_delivery_recovery": copy.deepcopy(
                    persisted["delivery_recovery"]
                ),
                "competition_evidence_cutover": gate,
                "commence_time_utc": "2026-10-20T15:00:00+00:00",
                "market_odds_decimal": {"Alpha": 1.40, "Beta": 3.20},
            }
            recovered = main._recover_competition_delivery(carrier)
            self.assertIsNotNone(recovered)
            recovered_payload, recovered_result = recovered
            self.assertEqual(
                recovered_payload["market_odds_decimal"],
                payload["market_odds_decimal"],
            )
            self.assertEqual(
                recovered_payload["commence_time_utc"],
                payload["commence_time_utc"],
            )
            calibration_store.apply_persisted_validation(
                recovered_payload, persisted
            )
            with patch.object(
                paper_trading.tournament_policy,
                "paper_block_reason",
                return_value=None,
            ), patch.object(
                paper_trading.market_integrity,
                "is_operational_pricing_payload",
                return_value=True,
            ):
                entries = paper_trading.build_entries(recovered_payload)
            self.assertEqual(len(entries), 1)
            self.assertEqual(
                paper_trading.append_entries(entries, path=paper_path), 1
            )
            html = report_html.build_report_html(
                recovered_payload, recovered_result
            )
            report_path.write_text(html, encoding="utf-8")

            # Idempotent retry: no new PAPER and identical real HTML.
            second_payload, second_result = main._recover_competition_delivery(
                carrier
            )
            calibration_store.apply_persisted_validation(
                second_payload, persisted
            )
            with patch.object(
                paper_trading.tournament_policy,
                "paper_block_reason",
                return_value=None,
            ), patch.object(
                paper_trading.market_integrity,
                "is_operational_pricing_payload",
                return_value=True,
            ):
                second_entries = paper_trading.build_entries(second_payload)
            self.assertEqual(
                paper_trading.append_entries(second_entries, path=paper_path), 0
            )
            self.assertEqual(
                report_html.build_report_html(second_payload, second_result),
                report_path.read_text(encoding="utf-8"),
            )

            # First-write-wins also preserves an already settled outcome.
            settled = copy.deepcopy(persisted)
            settled["outcome"] = {"winner": "Alpha"}
            snapshot_path.write_text(
                json.dumps({
                    "schema_version": calibration_store.SCHEMA_VERSION,
                    "snapshots": [settled],
                }),
                encoding="utf-8",
            )
            self.assertEqual(
                calibration_store.upsert_snapshots(
                    [snapshot], path=snapshot_path, max_entries=None
                ),
                0,
            )
            self.assertEqual(
                calibration_store.read_snapshots_by_key(
                    ["cmiv2:recover"], path=snapshot_path
                )["cmiv2:recover"]["outcome"],
                {"winner": "Alpha"},
            )

    def test_identity_unavailable_disables_policy_and_never_recovers(self):
        gate = competition_evidence.canonical_cutover_gate(
            {
                "canonical_match_instance_id": None,
                "identity_persisted": False,
            },
            activation=ACTIVE,
            tour="atp",
            tournament_id=77,
            player_ids=(10, 20),
            persisted_snapshot=None,
        )
        self.assertFalse(gate["apply_policy"])
        self.assertFalse(gate.get("recover_frozen_delivery", False))
        self.assertEqual(gate["status"], "CANONICAL_IDENTITY_UNAVAILABLE")

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
