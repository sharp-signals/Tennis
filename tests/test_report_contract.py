import unittest

from src import report_html


class ReportStateTests(unittest.TestCase):
    def test_handicap_reference_header_is_explicitly_internal(self):
        html = report_html._mod_handicap_reference_header({
            "player_a": "A", "player_b": "B", "match_format": "bo5",
            "market_odds_decimal": {"A": 1.24, "B": 4.2},
        })
        self.assertIn("Moneyline pré-live capturada", html)
        self.assertIn("tabela analítica interna", html)
        self.assertIn("BO5", html)

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

        efficient = {"market": {"a": 55, "b": 45}, "classificacao": {"nivel": 0}, "tipo": "alinhamento",
                     "intensidade_nivel": 1, "intensidade_indicadores": "ligeira"}
        inconclusive = {"market": {"a": 55, "b": 45}, "classificacao": {"nivel": 0}, "tipo": "inconclusivo",
                        "intensidade_nivel": 0, "intensidade_indicadores": "neutra"}
        aligned_strong = {"market": {"a": 55, "b": 45}, "classificacao": {"nivel": 0}, "tipo": "alinhamento",
                          "intensidade_nivel": 3, "intensidade_indicadores": "forte"}
        moderate = {"market": {"a": 55, "b": 45}, "classificacao": {"nivel": 2}, "tipo": "direcao"}
        strong = {
            "market": {"a": 55, "b": 45},
            "classificacao": {"nivel": 3},
            "tipo": "direcao",
        }
        self.assertEqual(report_html.detetar_estado({}, {}, efficient)[0], "alinhado")
        self.assertEqual(report_html.detetar_estado({}, {}, inconclusive)[0], "inconclusivo")
        self.assertEqual(report_html.detetar_estado({}, {}, aligned_strong)[0], "alinhado_forte")
        self.assertEqual(report_html.detetar_estado({}, {}, moderate)[0], "acompanhar")
        self.assertEqual(report_html.detetar_estado({}, {}, strong)[0], "oportunidade")
        self.assertIn("Divergência", report_html.detetar_estado({}, {}, strong)[2])

        legacy_conviction = {**strong, "tipo": "conviccao"}
        self.assertEqual(report_html.detetar_estado({}, {}, legacy_conviction)[0], "alinhado")

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
        self.assertIn("RELATÓRIO NULO", html)
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

    def test_strong_alignment_is_observed_without_claiming_fair_odds_or_handicap(self):
        payload = {
            "player_a": "A", "player_b": "B",
            "market_odds_decimal": {"A": 1.80, "B": 2.05},
            "features": {
                "h2h": {"lider": "A", "diff": 4, "a_wins": 4, "b_wins": 0},
                "piso": {"lider": "A", "diff": 20, "amostra_a": 100, "amostra_b": 100},
                "forma_recente": {"lider": "A", "diff": 30},
                "ranking": {"lider": "A", "diff": 40},
            },
        }
        html = report_html.build_report_html_v2(payload, {}, report_html._calcular_divergencia)

        self.assertIn("EDGE POSITIVO", html)
        self.assertIn("Moneyline A", html)
        self.assertNotIn("Handicap Games", html)
        self.assertNotIn("Total Games", html)

    def test_superfavorito_foca_handicap_nao_moneyline(self):
        # PROBLEMA 4: odd muito abaixo da faixa de perfil (1.75) não deve
        # destacar Moneyline; o foco vai para o handicap negativo.
        payload = {
            "player_a": "A", "player_b": "B",
            "market_odds_decimal": {"A": 1.36, "B": 3.1},
            "features": {
                "h2h": {"lider": "A", "diff": 4, "a_wins": 4, "b_wins": 0},
                "piso": {"lider": "A", "diff": 20, "amostra_a": 100, "amostra_b": 100},
                "forma_recente": {"lider": "A", "diff": 30},
                "ranking": {"lider": "A", "diff": 40},
            },
        }
        html = report_html.build_report_html_v2(payload, {}, report_html._calcular_divergencia)
        self.assertIn("favorito claro", html)
        self.assertIn("Handicap de A", html)

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

    def test_calibrated_odds_range_is_demoted_behind_primary_pricing(self):
        payload = {
            "player_a": "A", "player_b": "B",
            "market_odds_decimal": {"A": 2.1, "B": 1.8},
            "features": {"ranking": {"lider": "A", "diff": 10}},
            "indicative_odds": {
                "available": True, "sample_size": 48, "minimum_sample": 30,
                "confidence_level_pct": 95, "evidence_bucket": [70, 79],
                "players": {
                    "a": {"odds_low": 1.65, "odds_high": 1.95},
                    "b": {"odds_low": 2.05, "odds_high": 2.55},
                },
            },
        }
        html = report_html.build_report_html_v2(payload, {}, report_html._calcular_divergencia)
        self.assertIn("SHARP PRICING — MARKET RESIDUAL", html)
        self.assertIn("Expected edge", html)
        self.assertNotIn("Faixa indicativa calibrada", html)
        self.assertNotIn("Veredicto de mercado", html)

    def test_uncalibrated_odds_range_does_not_define_visible_edge(self):
        payload = {
            "player_a": "A", "player_b": "B",
            "market_odds_decimal": {"A": 2.1, "B": 1.8},
            "features": {"ranking": {"lider": "A", "diff": 10}},
            "indicative_odds": {
                "available": True, "calibrated": False, "provisional": True,
                "basis": "historical", "sample_size": 12, "minimum_sample": 30,
                "confidence_level_pct": 95, "evidence_bucket": [70, 79],
                "players": {
                    "a": {"odds_low": 1.3, "odds_high": 2.4},
                    "b": {"odds_low": 1.7, "odds_high": 4.3},
                },
            },
        }
        html = report_html.build_report_html_v2(payload, {}, report_html._calcular_divergencia)
        self.assertIn("SHARP PRICING — MARKET RESIDUAL", html)
        self.assertIn("EXPERIMENTAL — EM VALIDAÇÃO", html)
        self.assertNotIn("Faixa indicativa em calibração", html)
        self.assertNotIn("Veredicto de mercado", html)

    def test_data_quality_uses_one_root_cause_notice(self):
        payload = {
            "player_a": "Daniel Merida Aguilar", "player_b": "B",
            "features": {"ranking": {"lider": "B", "diff": 10}},
            "data_quality": {"history_rows": 20000, "issues": [{
                "type": "name_resolution", "severity": "warning",
                "players": [{"side": "a", "player": "Daniel Merida Aguilar"}],
            }]},
        }
        html = report_html.build_report_html_v2(payload, {}, report_html._calcular_divergencia)
        self.assertEqual(html.count("Cobertura histórica limitada"), 1)
        self.assertIn("Daniel Merida Aguilar", html)
        self.assertIn("fatores que dependem desse histórico", html)

    def test_header_renders_local_portraits_fallback_and_credits(self):
        payload = {
            "player_a": "Xinyu Wang", "player_b": "Unknown Player",
            "market_odds_decimal": {"Xinyu Wang": 1.8, "Unknown Player": 2.1},
            "features": {"ranking": {"lider": "Xinyu Wang", "diff": 10}},
            "player_image_a": {
                "path": "../assets/players/xinyu-wang.jpg", "author": "Hameltion",
                "license": "CC BY-SA 4.0", "license_url": "https://license.test",
                "source_url": "https://source.test", "modified": True,
            },
        }
        html = report_html.build_report_html_v2(payload, {}, report_html._calcular_divergencia)

        self.assertIn('src="../assets/players/xinyu-wang.jpg"', html)
        self.assertIn("Fotografia de Xinyu Wang", html)
        self.assertIn("Sem fotografia de Unknown Player", html)
        self.assertIn(">UP</div>", html)
        self.assertIn("Créditos das fotografias", html)
        self.assertIn("Hameltion", html)
        self.assertIn("miniatura/enquadramento adaptado", html)
        self.assertIn('grid-template-areas:"player-a . player-b" "center center center"', html)
        self.assertIn(".mh-player,.mh-player.b{flex-direction:column;gap:8px}", html)
        self.assertIn(".mh-player-photo{width:60px;height:60px;flex-basis:60px}", html)

    def test_header_keeps_odds_and_divergence_before_sport_detail(self):
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

        self.assertIn("O jogo num relance", html)
        self.assertIn("Chaves do confronto", html)
        self.assertIn("▲ Belinda Bencic", html)
        self.assertIn('style="color:var(--b)">▲ Belinda Bencic', html)
        self.assertNotIn("**Eala**", html)
        self.assertIn('class="mh-odds"', html)
        self.assertIn("2.1", html)
        self.assertIn("1.8", html)
        self.assertLess(html.index('class="mh-odds"'), html.index('class="decision-box'))
        self.assertLess(html.index('class="decision-box'), html.index("Leitura do mercado"))
        self.assertLess(html.index("Leitura do mercado"), html.index("O jogo num relance"))
        self.assertLess(html.index("Mercado e indicadores"), html.index("O jogo num relance"))
        hero = html[html.index('<div class="mh">'):html.index('class="decision-box')]
        self.assertIn("2.1", hero)
        self.assertIn("1.8", hero)
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

        self.assertNotIn("<h3>Forma</h3>", html)
        self.assertIn("Forma Recente | &#218;ltimos 10", html)
        self.assertGreater(html.index("Forma Recente | &#218;ltimos 10"), html.index("Mapa de Forças"))

    def test_market_adjusted_form_is_explained_inside_force_map(self):
        payload = {
            "player_a": "A", "player_b": "B",
            "market_odds_decimal": {"A": 1.8, "B": 2.1},
            "features": {"forma_recente": {"lider": "A", "diff": 10}},
            "market_adjusted_form_a": {
                "matches": 8, "actual_wins": 6, "expected_wins": 4.7,
                "performance_vs_market": 1.3, "sample_status": "robusto",
                "total_recent_matches": 10, "overall_wins": 8,
                "excluded_missing_odds": 2, "excluded_missing_odds_wins": 2,
                "coverage_pct": 80.0,
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
        self.assertIn("Desempenho face ao esperado", html)
        self.assertIn("Compara apenas os jogos que têm odds históricas", html)
        self.assertIn("<b>6</b> vitórias em 8 jogos com odds históricas", html)
        self.assertIn("esperado: <b>4.7</b> · diferença +1.3", html)
        self.assertIn("2 de 10 jogos excluídos por falta de odds (2 vitórias)", html)
        self.assertIn("Acima do esperado", html)
        self.assertIn("Adversários: ranking médio #42.5 (24 jogos)", html)
        self.assertIn("Neste piso: 70% recente vs 60% carreira (melhorou 10 p.p.)", html)
        self.assertIn('class="expect-marker"', html)

    def test_action_map_is_always_open_and_builds_conditional_market_ideas(self):
        payload = {
            "player_a": "A", "player_b": "B", "tour": "wta", "tier": "WTA 1000",
            "market_odds_decimal": {"A": 2.2, "B": 1.7},
            "indicative_odds": {
                "available": True, "calibrated": False, "sample_size": 12,
                "players": {
                    "a": {"odds_low": 1.9, "odds_high": 2.8},
                    "b": {"odds_low": 1.4, "odds_high": 2.1},
                },
            },
            "rich_stats_a": {"scenarios": {
                "first_set_lose_then_win_pct": 38, "first_set_lose_count": 20,
                "deciding_set_win_pct": 42, "deciding_set_count": 20,
            }},
            "rich_stats_b": {"scenarios": {
                "first_set_lose_then_win_pct": 45, "first_set_lose_count": 22,
                "deciding_set_win_pct": 61, "deciding_set_count": 21,
            }},
            "fatigue_signal_a": {"sets_last_7d": 2},
            "fatigue_signal_b": {"sets_last_7d": 7},
        }
        div = {
            "market": {"a": 44, "b": 56}, "tipo": "direcao",
            "favorecido": "A", "indice_favorece": "A",
            "classificacao": {"nivel": 3},
        }
        html = report_html._mod_action_map(
            payload, div, {"verdict": "Síntese do confronto."},
        )

        self.assertIn('class="action-map-static"', html)
        self.assertNotIn('<details class="more report-map action-map"', html)
        self.assertNotIn("<summary>Mapa de Ações", html)
        self.assertIn('class="action-map-body"', html)
        self.assertIn("Mapa de Ações (6)", html)
        self.assertIn("Moneyline A", html)
        self.assertIn("A perde o 1.º set", html)
        self.assertIn("se chegar ao set decisivo", html)
        self.assertIn("Handicap ou total de jogos", html)
        self.assertIn("ainda não calcula linha nem odd justa", html)
        self.assertIn("Síntese do confronto.", html)

    def test_static_reading_card_is_replaced_by_action_map(self):
        payload = {
            "player_a": "A", "player_b": "B",
            "market_odds_decimal": {"A": 1.8, "B": 2.1},
            "features": {"ranking": {"lider": "A", "diff": 10}},
        }
        html = report_html.build_report_html_v2(
            payload, {"verdict": "Leitura antiga."}, report_html._calcular_divergencia,
        )
        self.assertIn("Mapa de Ações", html)
        self.assertNotIn('<div class="veredicto"><h3>Leitura</h3>', html)

    def test_service_and_return_use_plain_labels_and_visual_comparisons(self):
        payload = {
            "player_a": "Adam Walton", "player_b": "Ignacio Buse",
            "market_odds_decimal": {"Adam Walton": 1.8, "Ignacio Buse": 2.1},
            "features": {"servico": {"lider": "Ignacio Buse", "diff": 2}},
            "serve_return_stats_a": {
                "avg_first_serve_won_pct": 65, "avg_break_points_saved_pct": 58,
                "avg_break_points_converted_pct": 23,
            },
            "serve_return_stats_b": {
                "avg_first_serve_won_pct": 67, "avg_break_points_saved_pct": 53,
                "avg_break_points_converted_pct": 33,
            },
        }
        html = report_html.build_report_html_v2(payload, {}, report_html._calcular_divergencia)
        self.assertIn("Serviço e resposta · quem leva vantagem", html)
        self.assertIn("Pontos ganhos no 1.º serviço", html)
        self.assertIn("Break points salvos sob pressão", html)
        self.assertIn("Break points convertidos na resposta", html)
        self.assertIn("Vantagem Buse · +2.0 p.p.", html)
        self.assertIn('class="service-fill" style="width:65.0%;background:var(--a)"', html)
        self.assertNotIn(">BP salvos<", html)

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
        self.assertIn("Serviço e resposta · quem leva vantagem", html)
        self.assertIn("Momento recente sob pressão", html)
        self.assertIn("Pontos ganhos no 1.º serviço", html)
        self.assertEqual(html.count("Serviço e resposta · quem leva vantagem"), 1)
        self.assertNotIn("Pressão de serviço e resposta", html)
        self.assertNotIn("Serve Pressure Index", html)

    def test_load_combines_recovery_density_volume_and_tournament(self):
        payload = {
            "player_a": "A", "player_b": "B",
            "market_odds_decimal": {"A": 1.8, "B": 2.1},
            "features": {"ranking": {"lider": "A", "diff": 5}},
            "fatigue_signal_a": {
                "days_since_last_match": 3, "matches_last_3d": 0,
                "matches_last_7d": 1, "matches_last_14d": 3,
                "matches_this_tournament": 1, "sets_last_7d": 2, "last_match_sets": 2,
            },
            "fatigue_signal_b": {
                "days_since_last_match": 1, "matches_last_3d": 2,
                "matches_last_7d": 3, "matches_last_14d": 5,
                "matches_this_tournament": 3, "sets_last_7d": 8, "last_match_sets": 3,
            },
        }
        html = report_html.build_report_html_v2(payload, {}, report_html._calcular_divergencia)
        self.assertIn("Carga e recuperação", html)
        self.assertIn("descanso, densidade competitiva e volume acumulado", html)
        self.assertIn("Carga elevada", html)
        self.assertIn("jogos em 3 dias", html)
        self.assertIn("sets em 7 dias", html)
        self.assertIn("jogos no torneio", html)
        self.assertIn("sets no último jogo", html)
        self.assertIn("B tem +6 sets nos últimos 7 dias", html)
        self.assertNotIn("Carga (7 dias)", html)

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

        self.assertIn("Moneyline", html)
        self.assertNotIn("Moneyline · único mercado analisado", html)
        self.assertIn("Indicadores · peso relativo", html)
        self.assertNotIn("Total Games", html)
        self.assertNotIn("Handicap Games", html)
        self.assertNotIn("p.p. entre o índice", html)
        self.assertNotIn("índice representa apenas", html)
        self.assertNotIn("Ponto de observação", html)


    def test_force_map_orders_h2h_recent_pulse_before_analytical_metrics(self):
        payload = {
            "player_a": "A", "player_b": "B", "surface": "Hard",
            "market_odds_decimal": {"A": 1.8, "B": 2.1},
            "features": {"ranking": {"lider": "A", "diff": 10}},
            "h2h_history": [{
                "date": "2025-03-18T10:00:00Z", "tournament": "Miami",
                "surface": "Hard", "winner_name": "A", "result": "6-4 6-3",
            }],
            "recent_history_a": [{"won": True}, {"won": False}, {"won": True}],
            "recent_history_b": [{"won": False}, {"won": False}, {"won": True}],
            "pressure_profile_a": {"matches": 10, "first_serve_won_pct": 60},
            "pressure_profile_b": {"matches": 10, "first_serve_won_pct": 58},
            "fatigue_signal_a": {"matches_last_7d": 2, "sets_last_7d": 5},
            "fatigue_signal_b": {"matches_last_7d": 3, "sets_last_7d": 8},
        }
        html = report_html.build_report_html_v2(payload, {}, report_html._calcular_divergencia)
        self.assertIn("Confronto Direto", html)
        self.assertNotIn("Duelo Direto", html)
        self.assertIn('class="history-score"', html)
        self.assertIn('class="fd-bar', html)
        self.assertIn("Miami", html)
        self.assertIn("6-4 6-3", html)
        self.assertIn("Forma Recente | &#218;ltimos 10", html)
        self.assertNotIn("Pulso Recente", html)
        self.assertIn("pulse-win", html)
        self.assertIn("pulse-loss", html)
        self.assertIn(".pulse-seq{display:flex;justify-content:flex-end;gap:5px;flex-wrap:nowrap", html)
        self.assertIn(".pulse-player{grid-template-columns:1fr;gap:7px}", html)
        self.assertLess(html.index("Confronto Direto"), html.index("Forma Recente | &#218;ltimos 10"))
        self.assertLess(html.index('class="history-score"'), html.index("Miami"))
        self.assertLess(html.index("Forma Recente | &#218;ltimos 10"), html.index("Raio-X Anal&#237;tico"))
        self.assertIn('class="card factor-bars-card"', html)
        self.assertIn('.factor-bars-card{border-color:var(--line);background:', html)
        self.assertIn('.factor-bars-head h3{color:var(--a)', html)
        self.assertIn('class="impact-switch"', html)
        self.assertIn("Impacto no matchup", html)
        self.assertIn('data-impact-side="a"', html)
        self.assertIn('style="color:var(--a)"', html)
        self.assertIn('[data-impact-side="a"] .fd-val{color:#78cfff!important}', html)
        self.assertIn('[data-impact-side="b"] .fd-val{color:#ffb47f!important}', html)
        self.assertIn('class="impact-trace"', html)
        self.assertIn("drawTrace", html)
        factor_card = html[html.index('class="card factor-bars-card"'):html.index('class="force-map-tail"')]
        self.assertEqual(factor_card.count("Raio-X Anal&#237;tico"), 1)
        self.assertGreater(html.index('class="force-map-tail"'), html.rindex('class="fd-linha"'))
        self.assertLess(html.index("Momento recente sob pressão"), html.index("Raio-X Anal&#237;tico"))
        tail = html[html.index('class="force-map-tail"'):]
        self.assertIn('class="load-tail"', tail)
        self.assertNotIn('class="pressure-tail"', tail)

    def test_h2h_uses_player_colours_for_bar_and_match_winners(self):
        payload = {
            "player_a": "Xinyu Wang", "player_b": "Donna Vekic",
            "market_odds_decimal": {"Xinyu Wang": 2.1, "Donna Vekic": 1.7},
            "h2h": {"total_matches": 2, "a_wins": 0, "b_wins": 2},
            "h2h_history": [
                {"date": "2024-06-01", "tournament": "Bad Homburg Open",
                 "winner_name": "Donna Vekic", "result": "6-2 6-4"},
                {"date": "2021-03-01", "tournament": "Courmayeur Open",
                 "winner_name": "Donna Vekic", "result": "6-4 6-4"},
            ],
            "features": {"h2h": {"lider": "Donna Vekic", "diff": 2,
                                     "a_wins": 0, "b_wins": 2}},
        }
        html = report_html.build_report_html_v2(payload, {}, report_html._calcular_divergencia)
        h2h = html[html.index("Confronto Direto"):html.index("Raio-X Anal&#237;tico")]

        self.assertIn('class="fd-bar-b" style="width:100%"', h2h)
        self.assertNotIn('class="fd-bar samp-low"', h2h)
        self.assertEqual(h2h.count('class="history-winner b"'), 2)
        self.assertIn("Bad Homburg Open", h2h)
        self.assertNotIn("Torneio 15213", h2h)

    def test_match_keys_colour_each_leader_by_player_side(self):
        payload = {
            "player_a": "Xinyu Wang", "player_b": "Donna Vekic",
            "market_odds_decimal": {"Xinyu Wang": 2.15, "Donna Vekic": 1.68},
            "features": {
                "ranking": {"lider": "Xinyu Wang", "diff": 18},
                "h2h": {"lider": "Donna Vekic", "diff": 2,
                         "a_wins": 0, "b_wins": 2},
            },
        }
        html = report_html.build_report_html_v2(payload, {}, report_html._calcular_divergencia)
        self.assertIn('style="color:var(--a)">▲ Xinyu Wang', html)
        self.assertIn('style="color:var(--b)">▲ Donna Vekic', html)

    def test_analytical_xray_places_insufficient_data_factors_last(self):
        payload = {"player_a": "A", "player_b": "B"}
        div = {"fatores_status": {
            "h2h": {"disponivel": True, "lider": "A",
                    "motivo_exclusao": "amostra insuficiente (1 jogo)",
                    "valor_a": 1, "valor_b": 0},
            "piso": {"disponivel": True, "lider": "B", "motivo_exclusao": None,
                     "valor_a": 45, "valor_b": 55},
            "ranking": {"disponivel": False, "lider": None,
                        "motivo_exclusao": None},
            "forma_recente": {"disponivel": True, "lider": "igual",
                               "motivo_exclusao": "diferença irrelevante",
                               "valor_a": 50, "valor_b": 50},
        }}

        html = report_html._mod_fatores_detalhados(payload, div)

        self.assertLess(html.index("forma recente"), html.index("superfície"))
        self.assertLess(html.index("superfície"), html.index("confronto direto"))
        self.assertLess(html.index("superfície"), html.index("ranking"))


if __name__ == "__main__":
    unittest.main()
