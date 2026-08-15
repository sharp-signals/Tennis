import unittest

from src import report_html


class ReportStateTests(unittest.TestCase):
    def test_percentage_normalization_accepts_fraction_percent_and_invalid(self):
        self.assertEqual(report_html._pct(0.68), 68.0)
        self.assertEqual(report_html._pct(68), 68.0)
        self.assertEqual(report_html._pct_str(0.684, 1), "68.4%")
        self.assertIsNone(report_html._pct("invalid"))
        self.assertEqual(report_html._pct_str(None), "—")

    def test_report_states_cover_error_no_odds_and_divergence_levels(self):
        self.assertEqual(
            report_html.detetar_estado({}, {"analysis_error": "timeout"}, None)[0],
            "erro",
        )
        self.assertEqual(report_html.detetar_estado({}, {}, None)[0], "sem_odds")

        efficient = {"market": {"a": 55, "b": 45}, "classificacao": {"nivel": 0}}
        moderate = {"market": {"a": 55, "b": 45}, "classificacao": {"nivel": 2}}
        strong = {
            "market": {"a": 55, "b": 45},
            "classificacao": {"nivel": 3},
            "tipo": "conviccao",
        }
        self.assertEqual(report_html.detetar_estado({}, {}, efficient)[0], "eficiente")
        self.assertEqual(report_html.detetar_estado({}, {}, moderate)[0], "acompanhar")
        self.assertEqual(report_html.detetar_estado({}, {}, strong)[0], "oportunidade")
        self.assertIn("Convicção", report_html.detetar_estado({}, {}, strong)[2])

    def test_divergence_normalization_preserves_diagnostic_fields(self):
        raw = {
            "prob_mercado_a": 60,
            "prob_mercado_b": 40,
            "indice_evidencia_a": 45,
            "indice_evidencia_b": 55,
            "classificacao": {"nivel": 2},
            "favorecido": "B",
            "tipo": "direcao",
            "n_fatores": 4,
            "fatores_status": "robusto",
            "gap_pp": 15,
        }

        actual = report_html._normalizar_div(raw)

        self.assertEqual(actual["market"], {"a": 60, "b": 40})
        self.assertEqual(actual["indice_evidencia"], {"a": 45, "b": 55})
        self.assertEqual(actual["n_fatores"], 4)
        self.assertEqual(actual["gap_pp"], 15)


class ReportRenderingTests(unittest.TestCase):
    def test_no_odds_report_is_semantic_safe_and_has_no_market_section(self):
        payload = {
            "player_a": '<script>alert("a")</script>',
            "player_b": "Jogador B",
            "tournament": "Lisboa",
            "surface": "Clay",
            "ranking_a": {"rank": '<img src=x onerror="alert(1)">'},
            "market_odds_decimal": {
                '<script>alert("a")</script>': '<svg onload="alert(2)">',
            },
            "features": {},
        }

        html = report_html.build_report_html_v2(payload, {}, lambda _payload: None)

        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("<main>", html)
        self.assertIn("Todos os relatórios", html)
        self.assertIn("Sem odds", html)
        self.assertNotIn('<script>alert("a")</script>', html)
        self.assertNotIn('<img src=x onerror="alert(1)">', html)
        self.assertNotIn('<svg onload="alert(2)">', html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("Mercado vs Sinal", html)

    def test_failed_analysis_without_odds_uses_reduced_partial_layout(self):
        payload = {
            "player_a": "A",
            "player_b": "B",
            "features": {},
            "recent_form_a": {"wins": 3, "losses": 2},
            "recent_form_b": {"wins": 2, "losses": 3},
        }

        html = report_html.build_report_html_v2(
            payload,
            {"analysis_error": "provider unavailable"},
            lambda _payload: None,
        )

        self.assertIn("Análise parcial", html)
        self.assertIn("sem sinal nem veredicto", html)
        self.assertNotIn("Mercados a acompanhar", html)

    def test_market_overview_marks_underdog_when_indicators_disagree(self):
        payload = {
            "player_a": "A",
            "player_b": "B",
            "features": {"servico": {"diff": 2}},
        }
        model_vs_market = {
            "market": {"a": 65, "b": 35},
            "model": {"a": 40, "b": 60},
            "indice_evidencia": {"a": 40, "b": 60},
            "divergencia": {"favorecido": "B"},
        }

        overview = report_html._compute_market_overview(payload, model_vs_market)
        by_name = {name: (level, text) for name, level, text in overview}

        self.assertEqual(by_name["Moneyline Favorito"][0], 0)
        self.assertEqual(by_name["Moneyline Underdog"][0], 3)
        self.assertEqual(by_name["Tie-break"][0], 2)

    def test_interest_dots_always_render_exactly_three_points(self):
        for level in range(4):
            with self.subTest(level=level):
                self.assertEqual(report_html._render_interesse_dots(level).count("mo-dot"), 3)


if __name__ == "__main__":
    unittest.main()
