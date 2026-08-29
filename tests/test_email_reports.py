import os
import unittest
from unittest.mock import MagicMock, patch

from src import email_reports


class EmailReportsTests(unittest.TestCase):
    def test_missing_credentials_does_not_open_smtp_connection(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(email_reports.smtplib, "SMTP_SSL") as smtp, \
             patch("builtins.print") as output:
            sent = email_reports.send_run_report_email("2026-08-29", [])

        self.assertFalse(sent)
        smtp.assert_not_called()
        self.assertIn("não configurado", str(output.call_args))

    def test_email_contains_links_and_uses_gmail_ssl(self):
        client = MagicMock()
        smtp = MagicMock()
        smtp.return_value.__enter__.return_value = client
        reports = [
            ({"player_a": "Alpha", "player_b": "Beta"}, {}, "https://example.test/report.html"),
        ]
        environment = {
            "REPORT_EMAIL_TO": "fenzobot@gmail.com",
            "REPORT_EMAIL_FROM": "fenzobot@gmail.com",
            "REPORT_EMAIL_APP_PASSWORD": "app-password",
        }

        with patch.dict(os.environ, environment, clear=True), \
             patch.object(email_reports.smtplib, "SMTP_SSL", smtp), \
             patch.object(email_reports.ssl, "create_default_context", return_value=MagicMock()):
            sent = email_reports.send_run_report_email("2026-08-29", reports)

        self.assertTrue(sent)
        smtp.assert_called_once()
        self.assertEqual(smtp.call_args.args[:2], ("smtp.gmail.com", 465))
        client.login.assert_called_once_with("fenzobot@gmail.com", "app-password")
        message = client.send_message.call_args.args[0]
        self.assertEqual(message["To"], "fenzobot@gmail.com")
        self.assertIn("https://example.test/report.html", message.get_body(preferencelist=("plain",)).get_content())
        html_body = message.get_body(preferencelist=("html",)).get_content()
        self.assertIn("https://sharp-signals.github.io/Tennis/assets/fenzo-logo.png", html_body)
        self.assertIn("Fenzo Tennis Intelligence", html_body)

    def test_smtp_failure_does_not_expose_app_password(self):
        password = "secret-app-password"
        environment = {
            "REPORT_EMAIL_TO": "fenzobot@gmail.com",
            "REPORT_EMAIL_FROM": "fenzobot@gmail.com",
            "REPORT_EMAIL_APP_PASSWORD": password,
        }
        with patch.dict(os.environ, environment, clear=True), \
             patch.object(email_reports.smtplib, "SMTP_SSL", side_effect=OSError(password)), \
             patch.object(email_reports.ssl, "create_default_context", return_value=MagicMock()):
            with self.assertRaises(RuntimeError) as raised:
                email_reports.send_run_report_email("2026-08-29", [])

        self.assertNotIn(password, str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)


if __name__ == "__main__":
    unittest.main()
