"""Testes do Mapa de Forças visual."""

from __future__ import annotations

import unittest

from src.report_html import PESOS, _fd_bar, _mod_fatores_detalhados, _mod_transparencia_pesos, _pagina


class ForceMapTests(unittest.TestCase):
    def test_report_page_has_semantic_structure_and_back_link(self) -> None:
        html = _pagina("Jogador A", "Jogador B", '<div class="wrap">conteúdo</div>')
        self.assertIn("<main>", html)
        self.assertIn('<h1 class="sr-only">Jogador A vs Jogador B</h1>', html)
        self.assertIn('aria-label="Navegação do relatório"', html)
        self.assertIn("← Todos os relatórios", html)

    def test_percentages_are_rendered_inside_comparison_bar(self) -> None:
        html = _fd_bar("servico_carreira", {
            "valor_a": 66, "valor_b": 69,
            "amostra_a": 24, "amostra_b": 18,
        })
        self.assertIn('fd-bar-val a">66%</span>', html)
        self.assertIn('fd-bar-val b">69%</span>', html)
        self.assertIn('class="fd-bar"', html)

    def test_small_sample_reduces_visual_confidence(self) -> None:
        html = _fd_bar("piso", {
            "valor_a": 70, "valor_b": 55,
            "amostra_a": 5, "amostra_b": 20,
        })
        self.assertIn('class="fd-bar samp-low"', html)

    def test_module_uses_force_map_title_and_leader(self) -> None:
        html = _mod_fatores_detalhados({}, {
            "fatores_status": {
                "servico_carreira": {
                    "disponivel": True, "lider": "Jogador B",
                    "valor_a": 66, "valor_b": 69,
                    "amostra_a": 24, "amostra_b": 18,
                },
            },
        })
        self.assertIn("Mapa de Forças (1)", html)
        self.assertIn('class="more report-map mais-forcas"', html)
        self.assertNotIn('class="more report-map mais-forcas" open', html)
        self.assertIn("Jogador B", html)
        self.assertIn("66%", html)
        self.assertIn("69%", html)

    def test_force_and_action_maps_share_collapsed_height(self) -> None:
        html = _pagina("A", "B", '<details class="more report-map mais-forcas"></details>')
        self.assertIn("details.report-map>summary", html)
        self.assertIn("min-height:78px", html)

    def test_weight_transparency_lists_every_factor_and_effective_weight(self) -> None:
        html = _mod_transparencia_pesos(
            {"player_a": "Jogador A", "player_b": "Jogador B"},
            {"fatores_status": {
                "ranking": {
                    "disponivel": True, "lider": "Jogador A",
                    "peso_base_configurado": 5, "peso_efetivo": 3.5,
                    "direcao_impacto": "a",
                },
                "h2h": {"disponivel": False, "peso_base_configurado": 6},
            }},
        )
        self.assertIn("Transparência dos Pesos", html)
        self.assertEqual(html.count('data-weight-factor="'), len(PESOS))
        self.assertIn("→ Jogador A", html)
        self.assertIn("3.5", html)
        self.assertIn("sem dados", html)
        self.assertIn("peso aplicado = peso-base", html)


if __name__ == "__main__":
    unittest.main()
