"""Testes offline do isolamento de providers LLM."""

from __future__ import annotations

import json
import unittest

from src.llm_provider import PaidLLMDisabledError, get_llm_provider


class LLMProviderTests(unittest.TestCase):
    def test_mock_returns_production_schema_without_external_call(self) -> None:
        provider = get_llm_provider("mock", allow_paid=False)
        response = provider.generate(
            system_prompt="não usado pelo mock",
            user_prompt="não usado pelo mock",
            max_tokens=10,
            metadata={"player_a": "A", "player_b": "B"},
        )
        result = json.loads(response.text)

        self.assertEqual(provider.name, "mock")
        self.assertFalse(provider.persist_cache)
        self.assertIn("signal_strength", result)
        self.assertNotIn("confidence_score", result)
        self.assertEqual(result["discrepancies"], [])

    def test_anthropic_is_blocked_without_explicit_paid_authorization(self) -> None:
        provider = get_llm_provider("anthropic", allow_paid=False)

        with self.assertRaises(PaidLLMDisabledError):
            provider.generate(
                system_prompt="x",
                user_prompt="y",
                max_tokens=10,
                metadata={},
            )

    def test_invalid_mode_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            get_llm_provider("unknown", allow_paid=False)


if __name__ == "__main__":
    unittest.main()
