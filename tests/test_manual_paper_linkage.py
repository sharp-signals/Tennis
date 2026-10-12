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


if __name__ == "__main__":
    unittest.main()
