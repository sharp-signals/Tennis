"""Testes offline da política seletiva de utilização do LLM."""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src import analyze


class FakeProvider:
    name = "fake"
    persist_cache = False

    def __init__(self) -> None:
        self.calls = 0

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        metadata: dict | None = None,
    ):
        self.calls += 1

        result = {
            "flag": analyze.FLAG_ROUTINE,
            "signal_strength": 50,
            "executive_summary": "A vs B — resposta simulada.",
            "verdict": "Resposta simulada.",
        }

        return SimpleNamespace(
            text=json.dumps(result, ensure_ascii=False),
            stop_reason=None,
            usage={},
        )


class SelectiveLLMPolicyTests(unittest.TestCase):
    def test_selective_skips_when_material_signals_are_aligned(self) -> None:
        provider = FakeProvider()
        payload = {
            "player_a": "A",
            "player_b": "B",
            "features": {
                "ranking": {
                    "lider": "A",
                    "diff": 40,
                    "valor_a": 10,
                    "valor_b": 50,
                },
                "forma_recente": {
                    "lider": "A",
                    "diff": 20,
                    "amostra_a": 10,
                    "amostra_b": 10,
                },
                "epoca_atual": {
                    "lider": "A",
                    "diff": 15,
                    "amostra_a": 25,
                    "amostra_b": 25,
                },
            },
        }

        with (
            patch.object(analyze, "LLM_POLICY", "selective"),
            patch.object(analyze, "get_llm_provider", return_value=provider),
        ):
            result = analyze.analyze_match(payload)

        self.assertEqual(provider.calls, 0)
        self.assertEqual(result["flag"], analyze.FLAG_ROUTINE)
        self.assertIn("A", result["summary_line"])

    def test_selective_calls_provider_for_level_three_market_divergence(self) -> None:
        provider = FakeProvider()
        payload = {
            "player_a": "A",
            "player_b": "B",
            "features": {
                "ranking": {
                    "lider": "A",
                    "diff": 45,
                    "valor_a": 12,
                    "valor_b": 57,
                },
                "forma_recente": {
                    "lider": "B",
                    "diff": 25,
                    "amostra_a": 10,
                    "amostra_b": 10,
                },
                "piso": {
                    "lider": "B",
                    "diff": 14,
                    "amostra_a": 30,
                    "amostra_b": 30,
                },
            },
            "divergencia": {
                "prob_mercado_a": 62.0,
                "prob_mercado_b": 38.0,
                "favorecido": "B",
                "mercado_favorece": "A",
                "tipo": "direcao",
                "classificacao": {
                    "nivel": 3,
                    "texto": "Divergência forte",
                },
            },
        }

        with (
            patch.object(analyze, "LLM_POLICY", "selective"),
            patch.object(analyze, "get_llm_provider", return_value=provider),
        ):
            result = analyze.analyze_match(payload)

        self.assertEqual(provider.calls, 1)
        self.assertIn("Divergência forte a favor de B", result["verdict"])
        self.assertIn("fallback_determinístico", result["_validacao"])

    def test_all_synthesis_still_calls_provider_for_aligned_game(self) -> None:
        provider = FakeProvider()
        payload = {
            "player_a": "A",
            "player_b": "B",
            "features": {
                "ranking": {
                    "lider": "A",
                    "diff": 50,
                    "valor_a": 5,
                    "valor_b": 55,
                }
            },
        }

        with (
            patch.object(analyze, "LLM_POLICY", "all_synthesis"),
            patch.object(analyze, "get_llm_provider", return_value=provider),
        ):
            result = analyze.analyze_match(payload)

        self.assertEqual(provider.calls, 1)
        self.assertEqual(result["verdict"], "Resposta simulada.")


if __name__ == "__main__":
    unittest.main()
