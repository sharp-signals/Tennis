import unittest

from openpyxl import Workbook

from scripts.build_system_history_workbook import _write_guerra_audit_sheets


class GuerraAuditWorkbookTests(unittest.TestCase):
    def test_writes_aggregate_tabs_without_individual_rows(self):
        workbook = Workbook()
        payload = {
            "by_strategy": {
                "GUERRA_SELECTION_V1": {
                    "audit_v1": {
                        "status": "AVAILABLE",
                        "privacy_contract": "AGGREGATES_ONLY_NO_INDIVIDUAL_SELECTIONS",
                        "quality": {"linked_entries": 12, "canonical_entries": 8},
                        "factors": [{
                            "scope": "ATP", "factor": "forma_recente",
                            "relation": "Alinha com seleção", "total_entries": 8,
                            "settled": 6, "wins": 4, "losses": 2,
                            "win_rate_pct": 66.7, "roi_pct": 12.5,
                            "sample_status": "Informativo",
                        }],
                        "segments": [{
                            "dimension": "Mercado", "group": "Moneyline",
                            "total_entries": 5, "settled": 4, "wins": 3,
                            "losses": 1, "win_rate_pct": 75.0,
                            "sample_status": "Informativo",
                        }],
                    },
                },
            },
        }
        _write_guerra_audit_sheets(workbook, payload)
        self.assertIn("GUERRA — fatores", workbook.sheetnames)
        self.assertIn("GUERRA — segmentos", workbook.sheetnames)
        self.assertIn("GUERRA — qualidade", workbook.sheetnames)
        self.assertEqual(workbook["GUERRA — fatores"]["A6"].value, "ATP")
        self.assertEqual(workbook["GUERRA — fatores"]["I6"].value, 0.667)
        self.assertEqual(workbook["GUERRA — qualidade"]["B8"].value, 12)


if __name__ == "__main__":
    unittest.main()
