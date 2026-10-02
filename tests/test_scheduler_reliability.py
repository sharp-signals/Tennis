"""Contratos estáticos CHANGE-055 entre Apps Script, workflow e Python."""

import unittest
from pathlib import Path


class SchedulerReliabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.workflow = (root / ".github/workflows/tennis-bot.yml").read_text(
            encoding="utf-8"
        )
        cls.scheduler = (
            root / "scripts/google_apps_script/prelive_scheduler.gs"
        ).read_text(encoding="utf-8")

    def test_workflow_dispatch_accepts_optional_slot_and_source(self):
        self.assertIn("trigger_slot:", self.workflow)
        self.assertIn("trigger_source:", self.workflow)
        self.assertIn("trigger_local_date:", self.workflow)
        self.assertIn("dispatch_attempt_id:", self.workflow)
        self.assertGreaterEqual(self.workflow.count("required: false"), 4)

    def test_manual_dispatch_defaults_are_explicit(self):
        self.assertIn(
            "FENZOBOT_TRIGGER_SLOT: ${{ inputs.trigger_slot || 'manual' }}",
            self.workflow,
        )
        self.assertIn(
            "FENZOBOT_TRIGGER_SOURCE: ${{ inputs.trigger_source || 'manual' }}",
            self.workflow,
        )

    def test_scheduler_payload_propagates_slot_and_source(self):
        self.assertIn("trigger_slot: logicalSlot", self.scheduler)
        self.assertIn("trigger_source: 'google_apps_script'", self.scheduler)
        self.assertIn("trigger_local_date: localDate", self.scheduler)
        self.assertIn("dispatch_attempt_id: attemptId", self.scheduler)

    def test_four_slots_are_documented_without_github_cron(self):
        for slot in ("06:30", "11:30", "15:30", "18:30"):
            self.assertIn(f"slot: '{slot}'", self.scheduler)
        self.assertNotIn("schedule:", self.workflow)

    def test_writer_queue_does_not_replace_third_pending_run(self):
        root = Path(__file__).resolve().parents[1]
        writer_workflows = (
            "tennis-bot.yml", "odds-monitor.yml", "pending-market-retry.yml",
            "refresh-observability.yml", "warm-up-hands.yml", "backtest.yml",
            "sync-player-images.yml",
        )
        for name in writer_workflows:
            text = (root / ".github/workflows" / name).read_text(encoding="utf-8")
            self.assertIn("group: tennis-data-writers", text, name)
            self.assertIn("queue: max", text, name)
            self.assertNotIn("cancel-in-progress: true", text, name)


if __name__ == "__main__":
    unittest.main()
