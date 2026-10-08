"""Manual sync skip-ci and recursion regression, no external calls."""
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.manual_refresh_trigger import needs_refresh


class ManualRefreshTriggerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.git('init', '-q')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'user.name', 'test')
        self.commit('README.md', 'base')

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.root, text=True,
                                       stderr=subprocess.DEVNULL).strip()

    def commit(self, path, text):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        self.git('add', path)
        self.git('commit', '-qm', 'sync [skip ci]')
        return self.git('rev-parse', 'HEAD')

    def test_skip_ci_manual_commit_is_detected(self):
        sha = self.commit('data/manual_paper_22bet.json', '{}')
        self.assertTrue(needs_refresh('workflow_run', sha, self.root))

    def test_derived_commit_does_not_trigger_a_loop(self):
        self.commit('data/manual_paper_22bet.json', '{}')
        sha = self.commit('data/dashboard/example.json', '{}')
        self.assertFalse(needs_refresh('workflow_run', sha, self.root))

    def test_unknown_event_or_invalid_sha_fails_closed(self):
        self.assertFalse(needs_refresh('workflow_run', '--all', self.root))
        self.assertFalse(needs_refresh('pull_request', self.git('rev-parse', 'HEAD'), self.root))

    def test_untrusted_nonancestor_fails_closed(self):
        self.git('checkout', '-qb', 'other')
        sha = self.commit('data/manual_paper_22bet.json', '{}')
        self.git('checkout', '--detach', 'HEAD^')
        self.assertFalse(needs_refresh('workflow_run', sha, self.root))

    def test_explicit_dispatch_is_supported(self):
        self.assertTrue(needs_refresh('workflow_dispatch', '', self.root))

    def test_schedule_recovers_valid_newer_sheet_aggregate(self):
        current = {
            'schema_version': 2,
            'source': {'synced_at_utc': '2026-10-08T10:00:00Z', 'operational_columns': {
                'market': 6, 'side': 8, 'odd': 11, 'stake': 12, 'result': 14, 'profit': 15,
            }},
            'summary': {'total_entries': 2, 'settled': 1, 'pending': 1, 'wins': 1,
                        'losses': 0, 'pushes': 0, 'units': 1, 'settled_stake_units': 1,
                        'pending_stake_units': 1},
        }
        incoming = dict(current)
        incoming['source'] = dict(current['source'], synced_at_utc='2026-10-08T10:30:00Z')
        (self.root / 'data').mkdir()
        (self.root / 'data/manual_paper_22bet_authoritative.json').write_text(__import__('json').dumps(current), encoding='utf-8')
        (self.root / 'data/manual_paper_22bet.json').write_text(__import__('json').dumps(incoming), encoding='utf-8')
        self.assertTrue(needs_refresh('schedule', '', self.root))

    def test_schedule_rejects_incomplete_sheet_aggregate_without_rebuilding_dashboard(self):
        (self.root / 'data').mkdir()
        (self.root / 'data/manual_paper_22bet.json').write_text(__import__('json').dumps({
            'schema_version': 2,
            'source': {'synced_at_utc': '2026-10-08T10:30:00Z'},
            'summary': {'total_entries': 108, 'settled': 0, 'pending': 108, 'wins': 0,
                        'losses': 0, 'pushes': 0, 'units': 0, 'settled_stake_units': 0,
                        'pending_stake_units': 108},
        }), encoding='utf-8')
        self.assertFalse(needs_refresh('schedule', '', self.root))
