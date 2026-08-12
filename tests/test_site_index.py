"""Testes do índice navegável de relatórios."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import main


class SiteIndexTests(unittest.TestCase):
    def test_index_contains_search_priority_and_safe_content(self) -> None:
        reports = [(
            {
                "player_a": "A <script>", "player_b": "B",
                "tournament": "Open", "_tour": "atp",
                "divergencia": {"classificacao": {"nivel": 3}},
            },
            {"flag": "🔴", "summary_line": "Sinal forte"},
            "https://example.test/report.html",
        )]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reports_dir = root / "relatorios"
            reports_dir.mkdir()
            with patch.object(main, "SITE_OUTPUT_DIR", str(root)):
                main._write_site_index(reports, "2026-08-12", str(reports_dir))
            generated = (root / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="search"', generated)
        self.assertIn('id="priority"', generated)
        self.assertIn('data-level="3"', generated)
        self.assertIn("A &lt;script&gt;", generated)
        self.assertNotIn("A <script>", generated)


if __name__ == "__main__":
    unittest.main()
