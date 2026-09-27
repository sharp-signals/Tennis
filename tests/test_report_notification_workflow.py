import unittest
from pathlib import Path


class ReportNotificationWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = (
            Path(__file__).resolve().parents[1] / ".github/workflows/tennis-bot.yml"
        ).read_text(encoding="utf-8")

    def test_publish_readiness_notification_calibration_order(self):
        names = [
            "Correr o bot",
            "Publicar relatórios do site imediatamente",
            "Confirmar publicação dos relatórios",
            "Enviar notificações dos relatórios",
            "Atualizar resultados para calibracao",
        ]
        positions = [self.workflow.index(f"- name: {name}") for name in names]
        self.assertEqual(positions, sorted(positions))

    def test_main_and_sender_share_ephemeral_manifest_path(self):
        self.assertIn(
            "FENZOBOT_REPORT_NOTIFICATION_MANIFEST: ${{ runner.temp }}/fenzobot-report-notifications.json",
            self.workflow,
        )
        self.assertIn("python -m src.report_notifications wait", self.workflow)
        self.assertIn("python -m src.report_notifications send", self.workflow)

    def test_rerun_checks_out_current_main_for_durable_delivery_state(self):
        checkout = self.workflow.index("uses: actions/checkout@")
        setup = self.workflow.index("uses: actions/setup-python@", checkout)
        checkout_step = self.workflow[checkout:setup]
        self.assertIn("ref: main", checkout_step)
        self.assertIn("fetch-depth: 0", checkout_step)

    def test_push_failure_prevents_readiness_and_notifications(self):
        self.assertIn("steps.publish_reports.outcome == 'success'", self.workflow)
        send_start = self.workflow.index("- name: Enviar notificações dos relatórios")
        calibration_start = self.workflow.index("- name: Atualizar resultados para calibracao")
        send_step = self.workflow[send_start:calibration_start]
        self.assertIn("steps.report_readiness.outcome == 'success'", send_step)
        self.assertIn(
            "withhold --reason REPORT_PUBLICATION_PUSH_FAILED", self.workflow,
        )

    def test_timeout_preserves_generated_state_before_job_is_failed(self):
        persist = self.workflow.index("- name: Gravar caches + relatórios do site, se mudaram")
        fail = self.workflow.index("- name: Falhar após preservar dados se publicação ou notificação falhou")
        self.assertLess(persist, fail)
        self.assertIn("REPORT_PUBLICATION_TIMEOUT", self.workflow[fail:])
        self.assertIn("if: always() && steps.run_bot.outcome == 'success'", self.workflow[persist:fail])
        self.assertIn("data/run_metrics_log.json", self.workflow[persist:fail])

    def test_pr_167_immediate_publish_contract_is_preserved(self):
        bot = self.workflow.index("- name: Correr o bot")
        publish = self.workflow.index("- name: Publicar relatórios do site imediatamente")
        calibration = self.workflow.index("- name: Atualizar resultados para calibracao")
        self.assertLess(bot, publish)
        self.assertLess(publish, calibration)
        self.assertIn("bash scripts/publish-generated-changes.sh", self.workflow[publish:calibration])


if __name__ == "__main__":
    unittest.main()
