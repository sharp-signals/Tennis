import unittest
from pathlib import Path


class MatchIdentityWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.workflow = (
            cls.root / ".github/workflows/tennis-bot.yml"
        ).read_text(encoding="utf-8")

    def _step(self, name: str, next_name: str) -> str:
        start = self.workflow.index(f"- name: {name}")
        end = self.workflow.index(f"- name: {next_name}", start)
        return self.workflow[start:end]

    def test_identity_state_is_published_on_success_and_failure(self):
        failure = self._step(
            "Preservar telemetria se o bot falhar",
            "Gravar caches + relatórios do site, se mudaram",
        )
        success = self._step(
            "Gravar caches + relatórios do site, se mudaram",
            "Alertar no Telegram se alguma coisa falhou",
        )
        self.assertIn("data/match_identity/", failure)
        self.assertIn("data/match_identity/", success)

    def test_publish_helper_pushes_the_existing_commit_without_path_filter(self):
        helper = (
            self.root / "scripts/publish-generated-changes.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("git push origin HEAD:main", helper)
        self.assertNotIn("git add ", helper)
        self.assertNotIn("git restore ", helper)
        self.assertNotIn("git reset ", helper)


if __name__ == "__main__":
    unittest.main()
