from datetime import datetime, timezone
import json

from scripts import build_fenzobot_contextual_report_preview as preview


def _row(
    observation_id, canonical, analyzed, commence,
    *, status="READY_FOR_PROSPECTIVE_SHADOW",
):
    return {
        "observation_id": observation_id,
        "canonical_match_instance_id": canonical,
        "analyzed_at_utc": analyzed,
        "commence_time_utc": commence,
        "contextual_shadow": {"status": status},
    }


def test_imminent_prestart_fixture_is_carried_from_previous_run(tmp_path, monkeypatch):
    ledger = tmp_path / "observations.jsonl"
    rows = [
        _row(
            "current", "current-match", "2026-11-13T19:25:00+00:00",
            "2026-11-14T20:00:00+00:00",
        ),
        _row(
            "imminent-old", "imminent-match", "2026-11-12T18:25:00+00:00",
            "2026-11-13T20:00:00+00:00",
        ),
        _row(
            "imminent-new", "imminent-match", "2026-11-13T06:30:00+00:00",
            "2026-11-13T20:00:00+00:00",
        ),
        _row(
            "distant", "distant-match", "2026-11-13T18:25:00+00:00",
            "2026-11-14T20:00:00+00:00",
        ),
        _row(
            "past", "past-match", "2026-11-13T06:30:00+00:00",
            "2026-11-13T18:00:00+00:00",
        ),
    ]
    ledger.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8",
    )
    monkeypatch.setattr(preview, "DEFAULT_PATH", ledger)

    selected = preview._active_release_observation_ids(
        {"current"},
        now=datetime(2026, 11, 13, 19, 25, tzinfo=timezone.utc),
    )

    assert selected == {"current", "imminent-new"}
