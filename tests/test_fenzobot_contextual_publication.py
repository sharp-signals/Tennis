from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import build_fenzobot_contextual_publication as publication


def test_publication_notifies_only_unsettled_future_reports(tmp_path, monkeypatch):
    observations = tmp_path / "observations.jsonl"
    outcomes = tmp_path / "outcomes.jsonl"
    output = tmp_path / "reports"
    manifest = tmp_path / "manifest.json"
    rows = [
        {
            "observation_id": "future",
            "commence_time_utc": "2026-11-13T20:00:00+00:00",
            "players": {"a": {"name": "Player A"}, "b": {"name": "Player B"}},
        },
        {
            "observation_id": "past",
            "commence_time_utc": "2026-11-11T20:00:00+00:00",
            "players": {"a": {"name": "Past A"}, "b": {"name": "Past B"}},
        },
    ]
    observations.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8",
    )
    outcomes.write_text("", encoding="utf-8")

    def fake_build(*, output_dir, max_observations):
        output_dir.mkdir(parents=True)
        for row in rows:
            (output_dir / f"report-{row['observation_id']}.html").write_text(
                row["observation_id"], encoding="utf-8",
            )
        return {
            "status": "COMPLETED", "reports_built": 2, "isolation": {},
            "notification_rows": [{
                "observation_id": "future", "status": "NO_POSITIVE_EDGE",
            }],
        }

    monkeypatch.setattr(publication, "DEFAULT_PATH", observations)
    monkeypatch.setattr(publication, "OUTCOMES_PATH", outcomes)
    monkeypatch.setattr(publication, "build_release_previews", fake_build)
    monkeypatch.setenv("FENZOBOT_REPORT_NOTIFICATION_MANIFEST", str(manifest))
    metrics = tmp_path / "run_metrics.json"
    monkeypatch.setenv("FENZOBOT_RUN_METRICS_PATH", str(metrics))
    monkeypatch.setenv("GITHUB_RUN_ID", "run-contextual-1")

    result = publication.build_publication(
        output_dir=output,
        max_observations=50,
        now=datetime(2026, 11, 12, 12, tzinfo=timezone.utc),
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert result["operational_reports_published"] == 1
    assert len(payload["reports"]) == 1
    assert payload["reports"][0]["url"].endswith("report-future.html")
    assert "Player A vs Player B" in payload["telegram_chunks"][0]
    assert "🔴 SEM EDGE POSITIVO" in payload["telegram_chunks"][0]
    assert payload["email"]["today"] == "2026-11-12"
    assert payload["email"]["groups"][0]["name"] == "🔴 SEM EDGE POSITIVO"
    assert payload["email"]["groups"][0]["reports"][0]["title"] == (
        "Player A vs Player B"
    )
    metric_rows = json.loads(metrics.read_text(encoding="utf-8"))
    assert metric_rows[-1]["github_run_id"] == "run-contextual-1"
    assert metric_rows[-1]["reports_ok"] == 1


class ContextualPublicationDeduplicationTests(unittest.TestCase):
    def test_repeated_snapshots_notify_only_latest_report_per_match(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            observations = root / "observations.jsonl"
            outcomes = root / "outcomes.jsonl"
            output = root / "reports"
            manifest = root / "manifest.json"
            rows = [
                {
                    "observation_id": "newest",
                    "canonical_match_instance_id": "canonical-match-1",
                    "analyzed_at_utc": "2026-11-12T12:00:00+00:00",
                    "commence_time_utc": "2026-11-13T20:00:00+00:00",
                    "tour": "atp",
                    "players": {
                        "a": {"name": "Lorenzo Musetti"},
                        "b": {"name": "Ugo Humbert"},
                    },
                },
                {
                    "observation_id": "older",
                    "canonical_match_instance_id": "canonical-match-1",
                    "analyzed_at_utc": "2026-11-12T06:00:00+00:00",
                    "commence_time_utc": "2026-11-13T20:00:00+00:00",
                    "tour": "atp",
                    "players": {
                        "a": {"name": "Lorenzo Musetti"},
                        "b": {"name": "Ugo Humbert"},
                    },
                },
            ]
            observations.write_text(
                "\n".join(json.dumps(row) for row in rows) + "\n",
                encoding="utf-8",
            )
            outcomes.write_text("", encoding="utf-8")

            def fake_build(*, output_dir, max_observations):
                output_dir.mkdir(parents=True)
                for row in rows:
                    (output_dir / f"report-{row['observation_id']}.html").write_text(
                        row["observation_id"], encoding="utf-8",
                    )
                return {
                    "status": "COMPLETED",
                    "reports_built": 2,
                    "isolation": {},
                    "notification_rows": [
                        {
                            "observation_id": row["observation_id"],
                            "status": "CONSERVATIVE_POSITIVE",
                        }
                        for row in rows
                    ],
                }

            with (
                patch.object(publication, "DEFAULT_PATH", observations),
                patch.object(publication, "OUTCOMES_PATH", outcomes),
                patch.object(publication, "build_release_previews", fake_build),
                patch.dict("os.environ", {
                    "FENZOBOT_REPORT_NOTIFICATION_MANIFEST": str(manifest),
                    "FENZOBOT_RUN_METRICS_PATH": str(root / "metrics.json"),
                }, clear=False),
            ):
                result = publication.build_publication(
                    output_dir=output,
                    max_observations=50,
                    now=datetime(2026, 11, 12, 12, tzinfo=timezone.utc),
                )

            payload = json.loads(manifest.read_text(encoding="utf-8"))
            telegram = "\n".join(payload["telegram_chunks"])
            self.assertEqual(result["operational_reports_published"], 1)
            self.assertEqual(len(payload["reports"]), 1)
            self.assertTrue(payload["reports"][0]["url"].endswith(
                "report-newest.html"
            ))
            self.assertEqual(telegram.count("Lorenzo Musetti vs Ugo Humbert"), 1)
            email_reports = payload["email"]["groups"][0]["reports"]
            self.assertEqual(len(email_reports), 1)
