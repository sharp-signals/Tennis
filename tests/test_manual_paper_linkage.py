import tempfile
import unittest
from pathlib import Path

from src import manual_paper_linkage


class ManualPaperLinkageIndexTests(unittest.TestCase):
    def test_builds_canonical_and_legacy_records_without_manual_data(self):
        dashboard = {
            "days": [{
                "date": "2026-10-11",
                "reports": [
                    {"title": "A vs B", "url": "../relatorios/a-vs-b.html", "linkage": "EXACT_REPORT_ID", "report_id": "r1"},
                    {"title": "C vs D", "url": "../relatorios/c-vs-d.html", "linkage": "SELF_DESCRIBED_REPORT"},
                ],
                "matchups": [
                    {"title": "A vs B", "match_key": "canonical:1", "match_key_source": "SNAPSHOT_KEY", "version_indexes": [0]},
                    {"title": "C vs D", "match_key": "fallback:2", "match_key_source": "DATE_NORMALIZED_TITLE", "version_indexes": [1]},
                ],
            }],
        }
        snapshots = [{"report_id": "r1", "key": "snapshot:1", "commence_time_utc": "2026-10-12T10:00:00Z"}]
        result = manual_paper_linkage.build_index(dashboard, snapshots)
        self.assertEqual(result["record_count"], 2)
        self.assertEqual(result["records"][0]["snapshot_key"], "snapshot:1")
        self.assertIsNone(result["records"][1]["snapshot_key"])
        rendered = str(result["records"])
        self.assertNotIn("stake", rendered.lower())
        self.assertNotIn("selection", rendered.lower())

    def test_write_index_creates_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data" / "index.json"
            manual_paper_linkage.write_index({"records": []}, path)
            self.assertTrue(path.exists())

    def test_factor_index_contains_public_snapshot_facts_without_outcomes(self):
        snapshots = [{
            "key": "snapshot:1",
            "analyzed_at_utc": "2026-10-12T08:00:00Z",
            "tour": "atp",
            "tier": "500",
            "surface": "Hard",
            "player_a": {"name": "A"},
            "player_b": {"name": "B"},
            "outcome": {"winner_side": "a"},
            "metrics": {"divergencia": {
                "indice_favorece": "A",
                "indice_evidencia_a": 72,
                "indice_evidencia_b": 28,
                "fatores_status": {
                    "forma_recente": {
                        "disponivel": True,
                        "direcao_impacto": "a",
                        "peso_efetivo": 4.1254,
                    },
                    "h2h": {"disponivel": False},
                },
            }},
            "pricing": {"sharp_estimate_a": 0.58, "sharp_estimate_b": 0.42},
        }]
        market_memory = {"events": [{
            "snapshot_key": "snapshot:1",
            "entry_market_probabilities": {"a": 0.55, "b": 0.45},
            "last_valid_prestart_market_probabilities": {"a": 0.60, "b": 0.40},
        }]}
        result = manual_paper_linkage.build_factor_index(snapshots, market_memory)
        self.assertEqual(result["record_count"], 1)
        self.assertEqual(result["records"]["snapshot:1"]["f"], [["forma_recente", "a", 4.125]])
        self.assertEqual(result["records"]["snapshot:1"]["m"], "a")
        self.assertEqual(result["records"]["snapshot:1"]["p"], [0.58, 0.42])
        self.assertEqual(result["records"]["snapshot:1"]["me"], [0.55, 0.45])
        self.assertEqual(result["records"]["snapshot:1"]["mc"], [0.60, 0.40])
        self.assertNotIn("outcome", str(result).lower())
        self.assertNotIn("winner", str(result).lower())


if __name__ == "__main__":
    unittest.main()
