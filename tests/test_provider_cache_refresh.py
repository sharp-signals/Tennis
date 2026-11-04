import unittest
from unittest.mock import patch
from pathlib import Path

import pandas as pd

from scripts import refresh_tennismylife_cache


def _frame(*, remote=0, cached=0):
    frame = pd.DataFrame([{"winner_name": "A", "loser_name": "B"}])
    frame.attrs.update({
        "history_provider_remote_files": remote,
        "history_provider_cached_files": cached,
        "history_scope": "TEST",
    })
    return frame


class ProviderCacheRefreshTests(unittest.TestCase):
    def test_refresh_is_fresh_only_when_all_universes_reached_remote(self):
        with patch.object(
            refresh_tennismylife_cache.fetch_data,
            "_load_tennismylife",
            side_effect=[_frame(remote=10), _frame(remote=10), _frame(remote=20)],
        ):
            report = refresh_tennismylife_cache.refresh()

        self.assertEqual(report["status"], "FRESH")
        self.assertEqual(report["paid_api_calls"], 0)
        self.assertFalse(report["bot_executed"])

    def test_valid_last_known_good_is_degraded_but_not_destroyed(self):
        with patch.object(
            refresh_tennismylife_cache.fetch_data,
            "_load_tennismylife",
            side_effect=[_frame(cached=10), _frame(cached=10), _frame(cached=20)],
        ):
            report = refresh_tennismylife_cache.refresh()

        self.assertEqual(report["status"], "DEGRADED_LAST_KNOWN_GOOD")
        self.assertFalse(report["unavailable"])

    def test_missing_universe_fails_closed(self):
        with patch.object(
            refresh_tennismylife_cache.fetch_data,
            "_load_tennismylife",
            side_effect=[_frame(remote=10), None, _frame(remote=20)],
        ):
            report = refresh_tennismylife_cache.refresh()

        self.assertEqual(report["status"], "FAILED")
        self.assertEqual(report["unavailable"], ["wta"])

    def test_workflow_never_runs_bot_or_receives_paid_api_secrets(self):
        text = Path(
            ".github/workflows/refresh-historical-provider-cache.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("scripts.refresh_tennismylife_cache", text)
        self.assertNotIn("python -m src.main", text)
        self.assertNotIn("RAPIDAPI_KEY", text)
        self.assertNotIn("ODDS_API_KEY", text)


if __name__ == "__main__":
    unittest.main()
