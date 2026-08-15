import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import analyze


class StaticProvider:
    name = "static"
    persist_cache = False

    def __init__(self, text=None, error=None, stop_reason=None):
        self.text = text
        self.error = error
        self.stop_reason = stop_reason
        self.calls = 0

    def generate(self, **_kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return SimpleNamespace(text=self.text, stop_reason=self.stop_reason, usage={})


class PartialRecoveryTests(unittest.TestCase):
    def test_partial_extraction_uses_only_complete_model_fields(self):
        raw = (
            '{"flag":"🟡","signal_strength":44,'
            '"summary_line":"Resumo completo",'
            '"key_points":["Primeiro ponto","Segundo ponto"],'
            '"discrepancies":[{"weight":"alta","text":"Diferença real"}],'
            '"verdict":"texto cortado'
        )

        actual = analyze._extract_partial_fields(raw, {"player_a": "A", "player_b": "B"})

        self.assertEqual(actual["signal_strength"], 44)
        self.assertEqual(actual["key_points"], ["Primeiro ponto", "Segundo ponto"])
        self.assertEqual(actual["discrepancies"], [{"weight": "alta", "text": "Diferença real"}])
        self.assertIn("não disponível", actual["verdict"])

    def test_partial_extraction_rejects_non_analytical_fragments(self):
        self.assertIsNone(analyze._extract_partial_fields('{"flag":"🟡"', {}))
        self.assertIsNone(analyze._extract_partial_fields("", {}))

    def test_partial_extraction_replaces_out_of_contract_values(self):
        raw = '{"flag":"unexpected","signal_strength":999,"verdict":"Texto útil"'

        actual = analyze._extract_partial_fields(raw, {"player_a": "A", "player_b": "B"})

        self.assertEqual(actual["flag"], analyze.FLAG_UNCERTAIN)
        self.assertEqual(actual["signal_strength"], 30)

    def test_payload_hash_is_order_independent_and_provider_specific(self):
        first = analyze._payload_hash({"b": 2, "a": 1}, "provider-a")
        reordered = analyze._payload_hash({"a": 1, "b": 2}, "provider-a")
        other_provider = analyze._payload_hash({"a": 1, "b": 2}, "provider-b")

        self.assertEqual(first, reordered)
        self.assertNotEqual(first, other_provider)


class ProviderFailureTests(unittest.TestCase):
    def _run(self, provider):
        payload = {
            "player_a": "A",
            "player_b": "B",
            "features": {"ranking": {"lider": "A", "diff": 30, "valor_a": 5, "valor_b": 35}},
        }
        with patch.object(analyze, "LLM_POLICY", "all_synthesis"), \
             patch.object(analyze, "get_llm_provider", return_value=provider):
            return analyze.analyze_match(payload)

    def test_provider_exception_returns_deterministic_fallback(self):
        provider = StaticProvider(error=RuntimeError("temporary outage"))

        result = self._run(provider)

        self.assertEqual(provider.calls, 1)
        self.assertEqual(result["flag"], analyze.FLAG_UNCERTAIN)
        self.assertGreater(result["signal_strength"], 0)
        self.assertIn("A vs B", result["summary_line"])
        self.assertTrue(result["verdict"])

    def test_valid_json_array_is_rejected_without_losing_match(self):
        provider = StaticProvider(text=json.dumps([{"flag": "🟢"}]))
        with patch.object(analyze, "repair_json", side_effect=ValueError("cannot repair")):
            result = self._run(provider)

        self.assertEqual(result["flag"], analyze.FLAG_UNCERTAIN)
        self.assertEqual(result["signal_strength"], 0)
        self.assertIn("erro ao gerar análise", result["summary_line"])

    def test_null_provider_text_is_handled_as_invalid_response(self):
        provider = StaticProvider(text=None)
        with patch.object(analyze, "repair_json", side_effect=ValueError("cannot repair")):
            result = self._run(provider)

        self.assertEqual(result["flag"], analyze.FLAG_UNCERTAIN)
        self.assertIn("indisponível", result["verdict"])

    def test_markdown_fence_is_removed_before_json_parse(self):
        body = {
            "flag": analyze.FLAG_ROUTINE,
            "signal_strength": 10,
            "executive_summary": "Mercado eficiente.",
            "verdict": "Sem divergência relevante.",
        }
        provider = StaticProvider(text=f"```json\n{json.dumps(body)}\n```")

        result = self._run(provider)

        self.assertEqual(result["executive_summary"], "Mercado eficiente.")

    def test_invalid_field_types_use_safe_fallback(self):
        body = {
            "flag": analyze.FLAG_ROUTINE,
            "signal_strength": "high",
            "executive_summary": ["not", "text"],
            "verdict": "Conclusão",
        }
        provider = StaticProvider(text=json.dumps(body))
        with patch.object(analyze, "repair_json", side_effect=ValueError("cannot repair")):
            result = self._run(provider)

        self.assertEqual(result["flag"], analyze.FLAG_UNCERTAIN)
        self.assertEqual(result["signal_strength"], 30)
        self.assertIn("parcialmente", result["confidence_reason"])


class SchemaValidationTests(unittest.TestCase):
    def test_accepts_exact_response_contract(self):
        response = {
            "flag": analyze.FLAG_HIGH_SIGNAL,
            "signal_strength": 80,
            "executive_summary": "Resumo",
            "verdict": "Conclusão",
        }

        self.assertIs(analyze._validate_llm_response(response), response)

    def test_rejects_invalid_flag_strength_and_required_text(self):
        base = {
            "flag": analyze.FLAG_ROUTINE,
            "signal_strength": 10,
            "executive_summary": "Resumo",
            "verdict": "Conclusão",
        }
        invalid_changes = (
            {"flag": "unknown"},
            {"signal_strength": True},
            {"signal_strength": 101},
            {"executive_summary": ""},
            {"verdict": None},
        )

        for changes in invalid_changes:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                analyze._validate_llm_response({**base, **changes})


class AnalysisCacheTests(unittest.TestCase):
    def test_atomic_json_write_replaces_existing_document(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "analysis.json"
            path.write_text('{"old":true}', encoding="utf-8")

            analyze._atomic_write_json(path, {"new": "válido"})

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"new": "válido"})
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_invalid_cache_is_ignored_and_replaced(self):
        provider = StaticProvider(text=json.dumps({
            "flag": analyze.FLAG_ROUTINE,
            "signal_strength": 10,
            "executive_summary": "Resumo válido",
            "verdict": "Conclusão válida",
        }))
        provider.persist_cache = True
        payload = {
            "player_a": "A",
            "player_b": "B",
            "features": {"ranking": {"lider": "A", "diff": 30}},
        }

        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "fixed.json"
            cache_path.write_text('{"flag":"unknown"}', encoding="utf-8")
            with patch.object(analyze, "_ANALYSIS_CACHE_DIR", directory), \
                 patch.object(analyze, "_payload_hash", return_value="fixed"), \
                 patch.object(analyze, "LLM_POLICY", "all_synthesis"), \
                 patch.object(analyze, "get_llm_provider", return_value=provider):
                result = analyze.analyze_match(payload)

            self.assertEqual(provider.calls, 1)
            self.assertEqual(result["executive_summary"], "Resumo válido")
            self.assertEqual(json.loads(cache_path.read_text(encoding="utf-8")), result)

    def test_cache_contract_accepts_compact_and_recovered_results(self):
        compact = {
            "flag": analyze.FLAG_ROUTINE,
            "signal_strength": 10,
            "executive_summary": "Resumo",
            "verdict": "Conclusão",
        }
        recovered = {
            "flag": analyze.FLAG_UNCERTAIN,
            "signal_strength": 30,
            "summary_line": "Resumo recuperado",
            "verdict": "Conclusão recuperada",
        }

        self.assertIs(analyze._validate_cached_analysis(compact), compact)
        self.assertIs(analyze._validate_cached_analysis(recovered), recovered)


if __name__ == "__main__":
    unittest.main()
