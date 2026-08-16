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

        efficient = {"market": {"a": 55, "b": 45}, "classificacao": {"nivel": 0}, "tipo": "eficiente"}
        moderate = {"market": {"a": 55, "b": 45}, "classificacao": {"nivel": 2}, "tipo": "direcao"}
        strong = {
            "market": {"a": 55, "b": 45},
            "classificacao": {"nivel": 3},
            "tipo": "direcao",
        }
        self.assertEqual(report_html.detetar_estado({}, {}, efficient)[0], "eficiente")
        self.assertEqual(report_html.detetar_estado({}, {}, moderate)[0], "acompanhar")
        self.assertEqual(report_html.detetar_estado({}, {}, strong)[0], "oportunidade")
        self.assertIn("Divergência", report_html.detetar_estado({}, {}, strong)[2])

        legacy_conviction = {**strong, "tipo": "conviccao"}
        self.assertEqual(report_html.detetar_estado({}, {}, legacy_conviction)[0], "eficiente")

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

    def test_aligned_report_does_not_claim_value_or_render_unsupported_markets(self):
        payload = {
            "player_a": "A",
            "player_b": "B",
            "market_odds_decimal": {"A": 1.5, "B": 2.8},
            "features": {"ranking": {"lider": "A", "diff": 20}},
        }
        html = report_html.build_report_html_v2(payload, {}, report_html._calcular_divergencia)

        self.assertIn("Mercado e indicadores", html)
        self.assertNotIn("subvalorizado", html.lower())
        self.assertNotIn("p.p. entre o índice", html)
        self.assertNotIn("Total Games", html)
        self.assertNotIn("Handicap Games", html)
        self.assertNotIn("Mercado observado", html)

    def test_header_displays_odds_provenance_when_available(self):
        payload = {
            "player_a": "A",
            "player_b": "B",
            "market_odds_decimal": {"A": 1.8, "B": 2.1},
            "odds_source": "RapidAPI Moneyline",
            "odds_captured_at_utc": "2026-08-16T09:30:00+00:00",
            "features": {"ranking": {"lider": "A", "diff": 10}},
        }
        html = report_html.build_report_html_v2(payload, {}, report_html._calcular_divergencia)

        self.assertIn("Fonte: RapidAPI Moneyline", html)
        self.assertIn("captadas em 2026-08-16T09:30:00+00:00", html)

    def test_editorial_hierarchy_puts_matchup_and_sport_before_market(self):
        payload = {
            "player_a": "Alexandra Eala", "player_b": "Belinda Bencic",
            "player_a_country": "PHI", "player_b_country": "SUI",
            "tournament": "Toronto", "tier": "WTA 1000", "surface": "Hard",
            "commence_time_utc": "2026-08-17T20:30:00+00:00",
            "ranking_a": {"rank": 20}, "ranking_b": {"rank": 14},
            "recent_form_a": {"wins": 9, "losses": 1, "matches": 10},
            "recent_form_b": {"wins": 8, "losses": 2, "matches": 10},
            "surface_stats_a": {"Hard": {"wins": 20, "losses": 10, "matches": 30}},
            "surface_stats_b": {"Hard": {"wins": 22, "losses": 8, "matches": 30}},
            "fatigue_signal_a": {"sets_last_7d": 9},
            "fatigue_signal_b": {"sets_last_7d": 5},
            "pressure_profile_a": {"first_serve_won_pct": 58},
            "pressure_profile_b": {"first_serve_won_pct": 60},
            "h2h": {"total_matches": 2, "a_wins": 1, "b_wins": 1},
            "market_odds_decimal": {"Alexandra Eala": 2.1, "Belinda Bencic": 1.8},
            "features": {"ranking": {"lider": "Belinda Bencic", "diff": 6}},
        }
        result = {"key_points": ["**Eala** chega em melhor forma.", "**Bencic** chega mais fresca."]}

        html = report_html.build_report_html_v2(payload, result, report_html._calcular_divergencia)

        self.assertIn("Match Preview", html)
        self.assertIn("O jogo num relance", html)
        self.assertIn("Chaves do confronto", html)
        self.assertIn("PHI", html)
        self.assertNotIn("**Eala**", html)
        self.assertLess(html.index("O jogo num relance"), html.index("Leitura do mercado"))
        self.assertLess(html.index("Chaves do confronto"), html.index("Mercado e indicadores"))
        hero = html[html.index('<div class="mh">'):html.index('<div class="match-intro">')]
        self.assertNotIn("2.1", hero)
        self.assertNotIn("1.8", hero)
        self.assertNotIn("Â", hero)

    def test_form_details_live_only_inside_force_map(self):
        payload = {
            "player_a": "A",
            "player_b": "B",
            "market_odds_decimal": {"A": 1.8, "B": 2.1},
            "recent_form_a": {"wins": 7, "losses": 3, "matches": 10},
            "recent_form_b": {"wins": 4, "losses": 6, "matches": 10},
            "current_season_a": {"wins": 20, "losses": 10},
            "current_season_b": {"wins": 14, "losses": 16},
            "features": {"forma_recente": {"lider": "A", "diff": 30}},
        }
        html = report_html.build_report_html_v2(payload, {}, report_html._calcular_divergencia)

        self.assertEqual(html.count("<h3>Forma</h3>"), 1)
        self.assertGreater(html.index("<h3>Forma</h3>"), html.index("Mapa de Forças"))

    def test_market_adjusted_form_is_explained_inside_force_map(self):
        payload = {
            "player_a": "A", "player_b": "B",
            "market_odds_decimal": {"A": 1.8, "B": 2.1},
            "features": {"forma_recente": {"lider": "A", "diff": 10}},
            "market_adjusted_form_a": {
                "matches": 8, "actual_wins": 6, "expected_wins": 4.7,
                "performance_vs_market": 1.3, "sample_status": "robusto",
            },
            "opposition_quality_a": {
                "avg_opponent_rank": 42.5, "matches": 24, "sample_status": "robusto",
            },
            "surface_momentum_a": {
                "career_win_pct": 60.0, "career_matches": 100,
                "recent_win_pct": 70.0, "recent_matches": 20,
                "delta_pp": 10.0, "years": [2025, 2026],
            },
        }
        html = report_html.build_report_html_v2(payload, {}, report_html._calcular_divergencia)
        self.assertIn("Forma ajustada ao mercado", html)
        self.assertIn("6 vitórias reais vs 4.7 esperadas (+1.3)", html)
        self.assertIn("ranking médio dos adversários #42.5", html)
        self.assertIn("piso: 70.0% recente vs 60.0% carreira (+10.0 p.p.; n=20)", html)

    def test_pressure_profile_shows_components_not_composite_score(self):
        payload = {
            "player_a": "A", "player_b": "B",
            "market_odds_decimal": {"A": 1.8, "B": 2.1},
            "features": {"servico": {"lider": "A", "diff": 5}},
            "pressure_profile_a": {
                "matches": 12, "first_serve_won_pct": 72,
                "opponent_first_serve_won_pct": 64,
            },
            "pressure_profile_b": {
                "matches": 10, "first_serve_won_pct": 68,
                "opponent_first_serve_won_pct": 69,
            },
        }
        html = report_html.build_report_html_v2(payload, {}, report_html._calcular_divergencia)
        self.assertIn("Pressão de serviço e resposta", html)
        self.assertIn("1.º serviço ganho", html)
        self.assertNotIn("Serve Pressure Index", html)

    def test_directional_disagreement_renders_only_moneyline_observation(self):
        payload = {
            "player_a": "A",
            "player_b": "B",
            "market_odds_decimal": {"A": 2.8, "B": 1.5},
            "features": {
                "h2h": {"lider": "A", "diff": 3, "a_wins": 3, "b_wins": 0},
                "piso": {"lider": "A", "diff": 18, "amostra_a": 100, "amostra_b": 100},
                "forma_recente": {"lider": "A", "diff": 20},
            },
        }
        html = report_html.build_report_html_v2(payload, {}, report_html._calcular_divergencia)

        self.assertIn("Mercado observado", html)
        self.assertIn("Moneyline", html)
        self.assertNotIn("Moneyline · único mercado analisado", html)
        self.assertIn("Indicadores · peso relativo", html)
        self.assertNotIn("Total Games", html)
        self.assertNotIn("Handicap Games", html)
        self.assertNotIn("p.p. entre o índice", html)
        self.assertNotIn("índice representa apenas", html)
        self.assertNotIn("Ponto de observação", html)


if __name__ == "__main__":
    unittest.main()
