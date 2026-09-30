import unittest

from src import main


class DeterministicFeatureTests(unittest.TestCase):
    def test_feature_computation_normalizes_sources_and_keeps_samples(self):
        payload = {
            "player_a": "A",
            "player_b": "B",
            "tour": "atp",
            "tier": "ATP 500",
            "surface": "Outdoor Hard",
            "ranking_a": {"rank": 5, "points": 5000},
            "ranking_b": {"rank": 20, "points": 2000},
            "ranking_evolution_a": {"change_6m_pct": 10, "change_12m_pct": 20},
            "ranking_evolution_b": {"change_6m_pct": -5, "change_12m_pct": 5},
            "recent_form_a": {"wins": 8, "matches": 10},
            "recent_form_b": {"wins": 5, "matches": 10},
            "recent_quality_a": {"matches": 10, "score": 8, "top10_wins": 1},
            "recent_quality_b": {"matches": 10, "score": 3},
            "indoor_outdoor_a": {"outdoor": {"wins": 14, "matches": 20}},
            "indoor_outdoor_b": {"outdoor": {"wins": 10, "matches": 20}},
            "court_speed_a": {"wins": 6, "matches": 10},
            "court_speed_b": {"wins": 4, "matches": 10},
            "tiebreak_a": {"wins": 7, "matches": 10},
            "tiebreak_b": {"wins": 5, "matches": 10},
            "set1_comeback_stats_a": {"bo3": {"comeback_rate_pct": 40, "matches_lost_set1": 10}},
            "set1_comeback_stats_b": {"bo3": {"comeback_rate_pct": 30, "matches_lost_set1": 20}},
            "sazonal_a": {"wins": 9, "matches": 12},
            "sazonal_b": {"wins": 6, "matches": 12},
            "surface_stats_a": {"Hard": {"wins": 30, "matches": 50}},
            "surface_stats_b": {"Hard": {"wins": 20, "matches": 50}},
            "serve_return_stats_a": {"avg_first_serve_won_pct": 0.72, "matches_used": 10},
            "serve_return_stats_b": {"avg_first_serve_won_pct": 65, "matches_used": 8},
            "serve_return_recent_a": {"avg_first_serve_won_pct": 68, "matches_used": 2},
            "serve_return_recent_b": {"avg_first_serve_won_pct": 0.70, "matches_used": 2},
            "fatigue_signal_a": {"matches_last_7d": 1, "sets_last_7d": 2},
            "fatigue_signal_b": {"matches_last_7d": 3, "sets_last_7d": 8},
            "h2h": {
                "overall": {"a_wins": 3, "b_wins": 1, "total_matches": 4},
                "on_surface": {"a_wins": 1, "b_wins": 2, "total_matches": 3},
            },
        }

        features = main._compute_features(payload)

        self.assertEqual(features["ranking"]["lider"], "A")
        self.assertEqual(features["forma_recente"]["diff"], 30.0)
        self.assertEqual(features["forma_recente"]["amostra_a"], 10)
        self.assertEqual(features["piso"]["valor_a"], 60.0)
        self.assertEqual(features["servico_carreira"]["valor_a"], 72.0)
        self.assertEqual(features["servico_carreira"]["amostra_b"], 8)
        self.assertEqual(features["servico_recente"]["lider"], "B")
        self.assertEqual(features["frescura"]["mais_fresco"], "A")
        self.assertEqual(features["h2h_piso"]["lider"], "B")
        self.assertEqual(features["comeback_set1"]["amostra_b"], 20)

    def test_feature_computation_with_no_comparable_data_returns_none(self):
        self.assertIsNone(main._compute_features({"player_a": "A", "player_b": "B"}))

    def test_bo5_comeback_feature_rejects_generic_rich_scenarios(self):
        payload = {
            "player_a": "A", "player_b": "B", "tour": "atp", "tier": "Grand Slam",
            "rich_stats_a": {"scenarios": {
                "first_set_lose_then_win_pct": 28, "first_set_lose_count": 271,
            }},
            "rich_stats_b": {"scenarios": {
                "first_set_lose_then_win_pct": 55, "first_set_lose_count": 300,
            }},
            "set1_comeback_stats_a": {"bo5": {"comeback_rate_pct": 40, "matches_lost_set1": 10}},
            "set1_comeback_stats_b": {"bo5": {"comeback_rate_pct": 30, "matches_lost_set1": 10}},
        }

        features = main._compute_features(payload)

        self.assertEqual(features["comeback_set1"]["valor_a"], 40)
        self.assertEqual(features["comeback_set1"]["valor_b"], 30)
        self.assertEqual(features["comeback_set1"]["amostra_a"], 10)

    def test_zero_sample_service_is_not_compared_with_real_data(self):
        features = main._compute_features({
            "player_a": "A", "player_b": "B",
            "serve_return_stats_a": {"avg_first_serve_won_pct": 63, "matches_used": 3},
            "serve_return_stats_b": {"avg_first_serve_won_pct": 0, "matches_used": 0},
        })
        self.assertIsNone(features)

    def test_source_divergence_handles_fraction_percent_and_missing_data(self):
        self.assertTrue(
            main._fontes_divergem(
                {"wins": 8, "matches": 10},
                {"wins": 5, "matches": 10},
            )
        )
        self.assertFalse(main._fontes_divergem(None, {"wins": 5, "matches": 10}))
        self.assertFalse(
            main._fontes_divergem_serve(
                {"avg_first_serve_won_pct": 0.70},
                {"avg_first_serve_won_pct": 65},
            )
        )
        self.assertTrue(
            main._fontes_divergem_serve(
                {"avg_first_serve_won_pct": 0.80},
                {"avg_first_serve_won_pct": 60},
            )
        )


class DeterministicFallbackTests(unittest.TestCase):
    def test_minimum_flag_only_changes_routine_when_both_core_sources_missing(self):
        result = {"flag": main.FLAG_ROUTINE, "summary_line": "Resumo"}
        actual = main._enforce_minimum_flag(
            {"market_odds_decimal": None, "h2h": None},
            result,
        )
        self.assertEqual(actual["flag"], main.FLAG_UNCERTAIN)
        self.assertIn("sem odds nem H2H", actual["summary_line"])

        already_severe = {"flag": "🔴", "summary_line": "Problema"}
        self.assertEqual(
            main._enforce_minimum_flag({"market_odds_decimal": None, "h2h": None}, already_severe)["flag"],
            "🔴",
        )
        with_h2h = {"flag": main.FLAG_ROUTINE, "summary_line": "Ok"}
        self.assertEqual(
            main._enforce_minimum_flag({"market_odds_decimal": None, "h2h": {}}, with_h2h)["flag"],
            main.FLAG_ROUTINE,
        )

    def test_factual_result_contains_deterministic_evidence_and_marks_no_llm(self):
        payload = {
            "player_a": "A",
            "player_b": "B",
            "features": {
                "ranking": {"lider": "A", "valor_a": 5, "valor_b": 20},
                "forma_recente": {"lider": "A"},
                "piso": {"lider": "A"},
                "servico_carreira": {"lider": "B"},
                "h2h": {"lider": "A", "a_wins": 3, "b_wins": 1, "total": 4},
                "frescura": {"mais_fresco": "B", "jogos_7d_a": 3, "jogos_7d_b": 1},
            },
            "rich_stats_a": {"scenarios": {"first_set_win_then_win_pct": 82}},
            "rich_stats_b": {"scenarios": {"first_set_lose_then_win_pct": 31}},
        }

        result = main._factual_only_result(payload)

        self.assertTrue(result["_no_llm"])
        self.assertEqual(result["flag"], main.FLAG_ROUTINE)
        self.assertEqual(result["signal_strength"], 0)
        self.assertLessEqual(len(result["key_points"]), 6)
        joined = " ".join(result["key_points"])
        self.assertIn("ranking", joined)
        self.assertIn("confronto direto", joined)
        self.assertIn("mais fresco", joined)


if __name__ == "__main__":
    unittest.main()
