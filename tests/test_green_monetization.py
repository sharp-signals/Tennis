from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src import green_monetization


NOW = "2026-09-21T12:00:00+00:00"


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def leg(
    key: str,
    *,
    snapshot: str,
    market: str = "Moneyline",
    line=None,
    selection: str = "a",
    odd=2.0,
    result: str | None = None,
) -> dict:
    return {
        "key": key,
        "mode": "PAPER",
        "pregame": {
            "snapshot_key": snapshot,
            "analyzed_at_utc": NOW,
            "market_type": market,
            "market": f"{market} Alpha",
            "line": line,
            "selected_side": selection,
            "selected_player": "Alpha",
            "odd": odd,
        },
        "settlement": None if result is None else {"result": result},
    }


class GreenMonetizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.paper = self.root / "paper.json"
        self.legacy = self.root / "legacy.json"
        self.market = self.root / "market.json"
        write_json(self.legacy, {"schema_version": 1, "exclusions": []})
        write_json(self.market, {"schema_version": 1, "exclusions": []})

    def tearDown(self) -> None:
        self.temp.cleanup()

    def build(self, entries: list[dict]) -> dict:
        write_json(self.paper, {"schema_version": 1, "entries": entries})
        return green_monetization.build_report(
            paper_path=self.paper,
            legacy_exclusions_path=self.legacy,
            market_exclusions_path=self.market,
            generated_at_utc=NOW,
        )

    def test_win_loss_void_pending_and_multiple_legs_same_match(self):
        report = self.build([
            leg("ml-win", snapshot="atp:1", odd=2.1, result="WIN"),
            leg("ml-loss", snapshot="atp:2", odd=1.7, result="LOSS"),
            leg(
                "hcp-void", snapshot="atp:1", market="Handicap", line=2.5,
                odd=1.9, result="VOID",
            ),
            leg(
                "hcp-pending", snapshot="atp:1", market="Handicap", line=4.5,
                odd=1.8,
            ),
        ])
        self.assertEqual(report["status"], "AVAILABLE")
        self.assertEqual(report["eligible_entries"], 4)
        self.assertEqual(report["resolved_entries"], 3)
        self.assertEqual(report["pending_entries"], 1)
        self.assertEqual((report["wins"], report["losses"], report["void_entries"]), (1, 1, 1))
        self.assertEqual(report["resolved_stake_eur"], 30.0)
        self.assertEqual(report["pending_exposure_eur"], 10.0)
        self.assertEqual(report["net_profit_eur"], 1.0)
        self.assertEqual(report["roi_pct"], 3.33)
        self.assertEqual(report["by_market"]["Moneyline"]["eligible_entries"], 2)
        self.assertEqual(report["by_market"]["Handicap"]["eligible_entries"], 2)

    def test_deduplicates_by_snapshot_market_line_and_selection(self):
        report = self.build([
            leg("one", snapshot="wta:9", market="Handicap", line="+3.50", odd=1.9),
            leg("two", snapshot="wta:9", market="Handicap", line=3.5, odd=2.0),
            leg("other-side", snapshot="wta:9", market="Handicap", line=3.5, selection="b", odd=2.0),
        ])
        self.assertEqual(report["eligible_entries"], 2)
        self.assertEqual(report["excluded_entries"], 1)
        self.assertEqual(report["exclusion_reasons"], {"DUPLICATE_GREEN_LEG": 1})
        self.assertEqual(report["status"], "DEGRADED")

    def test_applies_both_exclusion_manifests_with_typed_reasons(self):
        entries = [
            leg("legacy-bad", snapshot="atp:1"),
            leg("market-bad", snapshot="atp:2"),
            leg("valid", snapshot="atp:3", result="WIN"),
        ]
        write_json(self.legacy, {"exclusions": [{
            "paper_key": "legacy-bad", "disposition": "VOID_DATA_INTEGRITY",
        }]})
        write_json(self.market, {"exclusions": [{
            "paper_key": "market-bad", "reason_code": "MARKET_BOUNDARY_SENTINEL",
        }]})
        report = self.build(entries)
        self.assertEqual(report["source"]["physical_entries"], 3)
        self.assertEqual(report["eligible_entries"], 1)
        self.assertEqual(report["excluded_entries"], 2)
        self.assertEqual(report["exclusion_reasons"], {
            "MARKET_BOUNDARY_SENTINEL": 1,
            "VOID_DATA_INTEGRITY": 1,
        })

    def test_missing_or_invalid_odd_is_excluded_not_zero(self):
        report = self.build([
            leg("missing", snapshot="atp:1", odd=None, result="WIN"),
            leg("invalid", snapshot="atp:2", odd=1.0, result="LOSS"),
        ])
        self.assertEqual(report["status"], "UNAVAILABLE")
        self.assertEqual(report["eligible_entries"], 0)
        self.assertEqual(report["excluded_entries"], 2)
        self.assertEqual(report["exclusion_reasons"], {
            "INVALID_OR_MISSING_FACTUAL_ODD": 2,
        })
        self.assertEqual(report["resolved_stake_eur"], 0.0)
        self.assertIsNone(report["roi_pct"])

    def test_non_moneyline_without_line_and_unknown_result_are_excluded(self):
        report = self.build([
            leg("no-line", snapshot="atp:1", market="Handicap", odd=1.9),
            leg("bad-result", snapshot="atp:2", odd=1.9, result="ABANDONED"),
        ])
        self.assertEqual(report["eligible_entries"], 0)
        self.assertEqual(report["exclusion_reasons"], {
            "MISSING_MARKET_LINE": 1,
            "UNVERIFIED_OUTCOME": 1,
        })

    def test_writes_canonical_aggregate_without_row_level_keys(self):
        write_json(self.paper, {
            "schema_version": 1,
            "entries": [leg("private-paper-key", snapshot="atp:private", result="WIN")],
        })
        output = self.root / "green.json"
        report = green_monetization.build_and_write(
            paper_path=self.paper,
            legacy_exclusions_path=self.legacy,
            market_exclusions_path=self.market,
            output_path=output,
            generated_at_utc=NOW,
        )
        saved = output.read_text(encoding="utf-8")
        self.assertEqual(json.loads(saved), report)
        self.assertNotIn("private-paper-key", saved)
        self.assertNotIn("atp:private", saved)
        self.assertEqual(report["universes"]["guerra_selection_v1"], "SUPERSEDED_NOT_INCLUDED")
        self.assertEqual(report["universes"]["real"], "NOT_INCLUDED")


if __name__ == "__main__":
    unittest.main()
