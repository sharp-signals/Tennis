import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from src import report_notifications


class Response:
    def __init__(self, status_code, content=b""):
        self.status_code = status_code
        self.content = content


class ReportNotificationsTests(unittest.TestCase):
    def _manifest(self, root: Path, count: int = 2) -> Path:
        reports = []
        for index in range(count):
            html_path = root / f"report-{index}.html"
            html_path.write_bytes(f"<html>report {index}</html>".encode())
            reports.append({
                "url": f"https://example.test/report-{index}.html",
                "local_path": str(html_path),
            })
        target = root / "manifest.json"
        result = report_notifications.write_manifest(
            run_date="2026-09-27",
            reports=reports,
            telegram_chunks=["chunk 1", "chunk 2"],
            email={"today": "2026-09-27", "groups": []},
            github_run_id="run-123",
            path=target,
        )
        self.assertEqual(result, target)
        return target

    def test_manifest_contains_all_reports_hashes_and_no_environment_secrets(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"RAPIDAPI_KEY": "provider-secret", "REPORT_EMAIL_APP_PASSWORD": "mail-secret"},
        ):
            target = self._manifest(Path(directory))
            raw = target.read_text(encoding="utf-8")
            payload = json.loads(raw)

        self.assertEqual(len(payload["reports"]), 2)
        self.assertEqual(len(payload["report_urls"]), 2)
        self.assertTrue(all(len(item["sha256"]) == 64 for item in payload["reports"]))
        self.assertEqual(payload["report_publication"]["status"], "PENDING")
        self.assertEqual(payload["report_notification_status"], "REPORTS_DEFERRED")
        self.assertNotIn("provider-secret", raw)
        self.assertNotIn("mail-secret", raw)

    def test_no_reports_creates_no_manifest_and_readiness_is_not_applicable(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "manifest.json"
            result = report_notifications.write_manifest(
                run_date="2026-09-27", reports=[], telegram_chunks=[],
                email={}, path=target,
            )
            readiness = report_notifications.wait_for_publication(path=target)
        self.assertIsNone(result)
        self.assertFalse(target.exists())
        self.assertEqual(readiness, {"status": "NOT_APPLICABLE", "expected": 0, "ready": 0})

    def test_404_times_out_and_withholds_notifications(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            report_notifications, "_persist_telemetry",
        ):
            target = self._manifest(Path(directory), count=1)
            with self.assertRaisesRegex(
                report_notifications.PublicationTimeoutError,
                "REPORT_PUBLICATION_TIMEOUT",
            ):
                report_notifications.wait_for_publication(
                    path=target, timeout_seconds=0, interval_seconds=0,
                    get=lambda *_args, **_kwargs: Response(404),
                )
            payload = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(payload["report_publication"]["status"], "TIMEOUT")
        self.assertEqual(payload["report_publication"]["reason_code"], "REPORT_PUBLICATION_TIMEOUT")
        self.assertEqual(payload["report_notification_status"], "REPORTS_WITHHELD")

    def test_404_then_matching_200_becomes_ready(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            report_notifications, "_persist_telemetry",
        ):
            root = Path(directory)
            target = self._manifest(root, count=1)
            body = (root / "report-0.html").read_bytes()
            responses = iter((Response(404), Response(200, body)))
            getter = MagicMock(side_effect=lambda *_args, **_kwargs: next(responses))
            result = report_notifications.wait_for_publication(
                path=target, timeout_seconds=20, interval_seconds=0,
                get=getter, sleep=lambda _seconds: None,
            )
        self.assertEqual(result, {"status": "READY", "expected": 1, "ready": 1})
        self.assertEqual(getter.call_count, 2)
        self.assertIn("fenzobot_run=run-123", getter.call_args_list[0].args[0])

    def test_200_with_stale_content_is_not_ready(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            report_notifications, "_persist_telemetry",
        ):
            target = self._manifest(Path(directory), count=1)
            with self.assertRaises(report_notifications.PublicationTimeoutError):
                report_notifications.wait_for_publication(
                    path=target, timeout_seconds=0, interval_seconds=0,
                    get=lambda *_args, **_kwargs: Response(200, b"stale"),
                )

    def test_ready_sends_telegram_and_email_once_across_retries(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            report_notifications, "_persist_telemetry",
        ):
            root = Path(directory)
            target = self._manifest(root, count=1)
            body = (root / "report-0.html").read_bytes()
            report_notifications.wait_for_publication(
                path=target, get=lambda *_args, **_kwargs: Response(200, body),
            )
            telegram = MagicMock()
            email = MagicMock(return_value={"status": "SENT", "kind": "REPORTS"})
            first = report_notifications.send_ready_notifications(
                path=target, telegram_sender=telegram, email_sender=email,
            )
            second = report_notifications.send_ready_notifications(
                path=target, telegram_sender=telegram, email_sender=email,
            )
        self.assertEqual(first["status"], "REPORTS_SENT")
        self.assertEqual(second["status"], "REPORTS_SENT")
        self.assertEqual(telegram.call_args_list, [call("chunk 1"), call("chunk 2")])
        email.assert_called_once()

    def test_not_ready_sends_nothing(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            report_notifications, "_persist_telemetry",
        ):
            target = self._manifest(Path(directory), count=1)
            telegram = MagicMock()
            email = MagicMock()
            result = report_notifications.send_ready_notifications(
                path=target, telegram_sender=telegram, email_sender=email,
            )
        self.assertEqual(result["status"], "REPORTS_WITHHELD")
        telegram.assert_not_called()
        email.assert_not_called()

    def test_push_failure_withholds_without_sending(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            report_notifications, "_persist_telemetry",
        ):
            target = self._manifest(Path(directory), count=1)
            result = report_notifications.withhold_notifications(
                "REPORT_PUBLICATION_PUSH_FAILED", path=target,
            )
            payload = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(result, {
            "status": "REPORTS_WITHHELD",
            "reason_code": "REPORT_PUBLICATION_PUSH_FAILED",
        })
        self.assertEqual(payload["report_notification_status"], "REPORTS_WITHHELD")
        self.assertEqual(payload["notification_reason_code"], "REPORT_PUBLICATION_PUSH_FAILED")

    def test_retry_after_partial_telegram_failure_resumes_without_duplicates(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            report_notifications, "_persist_telemetry",
        ):
            root = Path(directory)
            target = self._manifest(root, count=1)
            body = (root / "report-0.html").read_bytes()
            report_notifications.wait_for_publication(
                path=target, get=lambda *_args, **_kwargs: Response(200, body),
            )
            first_sender = MagicMock(side_effect=[None, RuntimeError("network")])
            with self.assertRaisesRegex(RuntimeError, "network"):
                report_notifications.send_ready_notifications(
                    path=target, telegram_sender=first_sender,
                    email_sender=MagicMock(),
                )
            retry_sender = MagicMock()
            email = MagicMock(return_value={"status": "SENT", "kind": "REPORTS"})
            report_notifications.send_ready_notifications(
                path=target, telegram_sender=retry_sender, email_sender=email,
            )
        retry_sender.assert_called_once_with("chunk 2")
        email.assert_called_once()

    def test_publication_telemetry_updates_same_github_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metrics = root / "metrics.json"
            metrics.write_text(
                json.dumps([{"github_run_id": "run-123", "status": "success"}]),
                encoding="utf-8",
            )
            target = self._manifest(root, count=1)
            body = (root / "report-0.html").read_bytes()
            with patch.dict(os.environ, {"FENZOBOT_RUN_METRICS_PATH": str(metrics)}):
                report_notifications.wait_for_publication(
                    path=target, get=lambda *_args, **_kwargs: Response(200, body),
                )
            persisted = json.loads(metrics.read_text(encoding="utf-8"))[0]
        self.assertEqual(persisted["status"], "success")
        self.assertEqual(persisted["report_publication"]["status"], "READY")
        self.assertEqual(persisted["report_notification_status"], "REPORTS_DEFERRED")


if __name__ == "__main__":
    unittest.main()
