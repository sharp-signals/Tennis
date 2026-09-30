import unittest
from pathlib import Path


class GeneratedPublicationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.helper = (cls.root / "scripts/publish-generated-changes.sh").read_text(
            encoding="utf-8"
        )
        cls.publisher = (cls.root / "scripts/publish_generated_changes.py").read_text(
            encoding="utf-8"
        )
        cls.recovery = (cls.root / "scripts/recover_generated_outputs.py").read_text(
            encoding="utf-8"
        )

    def test_publication_never_uses_implicit_autostash_or_force(self):
        self.assertNotIn("--autostash", self.helper)
        self.assertNotIn("git pull", self.helper)
        self.assertNotIn("push --force", self.helper)
        self.assertNotIn("git add ", self.helper)
        self.assertIn("publish_generated_changes.py", self.helper)
        self.assertIn('"fetch"', self.publisher)
        self.assertIn('"rebase"', self.publisher)

    def test_failure_preserves_recovery_bundle_and_hash_manifest(self):
        self.assertIn("local-commits.bundle", self.recovery)
        self.assertIn("recovery-manifest.json", self.recovery)
        self.assertIn('"status": "NOT_PUBLISHED"', self.recovery)
        self.assertIn("sha256", self.recovery)
        self.assertIn("WORKTREE_NOT_CLEAN_AFTER_EXPLICIT_COMMIT", self.publisher)
        self.assertIn("REBASE_CONFLICT", self.publisher)
        self.assertIn("PUSH_REJECTED_AFTER_RETRIES", self.publisher)

    def test_history_guard_runs_before_remote_integration(self):
        validation = self.publisher.index("scripts/validate_forward_only.py")
        rebase = self.publisher.index('"rebase"')
        self.assertLess(validation, rebase)
        self.assertGreater(self.publisher.rindex("_run(validation"), rebase)

    def test_all_generated_data_writers_upload_recovery_artifacts(self):
        names = (
            "tennis-bot.yml", "odds-monitor.yml", "pending-market-retry.yml",
            "refresh-observability.yml", "warm-up-hands.yml", "backtest.yml",
            "sync-player-images.yml",
        )
        for name in names:
            text = (self.root / ".github/workflows" / name).read_text(encoding="utf-8")
            self.assertIn("actions/upload-artifact@v7", text, name)
            self.assertIn("fenzobot-data-recovery", text, name)


if __name__ == "__main__":
    unittest.main()
