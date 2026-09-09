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
