import os
from unittest.mock import patch

from scripts.run_fenzobot_contextual_2026_11 import run_release_only


def test_global_release_runner_fails_closed_without_explicit_activation():
    previous = os.environ.pop("FENZOBOT_CONTEXTUAL_2026_11_MODE", None)
    try:
        try:
            run_release_only(max_matches=1)
        except RuntimeError as exc:
            assert "FENZOBOT_CONTEXTUAL_2026_11_DISABLED" in str(exc)
        else:
            raise AssertionError("runner unexpectedly activated")
    finally:
        if previous is not None:
            os.environ["FENZOBOT_CONTEXTUAL_2026_11_MODE"] = previous


def test_global_release_empty_run_remains_isolated():
    fake_contract = {
        "global_release_id": "FENZOBOT_CONTEXTUAL_2026_11",
        "configuration_fingerprint": "global-test-fingerprint",
        "components": {
            "ranking_model": "contextual-ranking-v7.1",
            "family_combination": "contextual-family-combination-v8-tier-context",
            "probability_calibration": "contextual-probability-uncertainty-v8",
            "runtime_generation": 9,
        },
    }
    with (
        patch(
            "scripts.run_fenzobot_contextual_2026_11.activation_state",
            return_value={"active": True},
        ),
        patch(
            "scripts.run_contextual_shadow_v2.fetch_data."
            "fetch_resilient_discovery_fixtures",
            return_value=[],
        ),
        patch(
            "scripts.run_contextual_shadow_v2.fetch_data.discovery_unavailable",
            return_value=False,
        ),
        patch(
            "scripts.run_contextual_shadow_v2.fetch_data.fetch_official_ranking",
            return_value=[],
        ),
        patch(
            "scripts.run_contextual_shadow_v2.fetch_data.get_rapidapi_call_count",
            return_value=0,
        ),
        patch("scripts.run_contextual_shadow_v2.fetch_data.flush_tournament_cache"),
        patch("scripts.run_contextual_shadow_v2.fetch_data.flush_fixtures_cache"),
        patch("scripts.run_contextual_shadow_v2.fetch_data.persist_rapidapi_usage"),
        patch(
            "scripts.run_fenzobot_contextual_2026_11.load_contract",
            return_value=fake_contract,
        ),
        patch(
            "scripts.run_fenzobot_contextual_2026_11.append_observations",
            return_value=0,
        ),
        patch(
            "scripts.run_fenzobot_contextual_2026_11.existing_observation_ids",
            return_value=set(),
        ),
        patch(
            "scripts.run_contextual_shadow_v2.append_frozen_handicap_evidence",
            return_value=0,
        ),
        patch(
            "scripts.run_contextual_shadow_v2.audit_ledger",
            return_value={"status": "WAITING_FOR_DATA", "rows": 0},
        ),
        patch("scripts.run_contextual_shadow_v2._write_json_atomic"),
    ):
        summary = run_release_only(max_matches=1)
    assert summary["model_version"] == "FENZOBOT_CONTEXTUAL_2026_11"
    assert summary["eligible_main_tour"] == 0
    assert summary["observations_added"] == 0
    assert summary["isolation"] == {
        "market_used": False,
        "reports_published": False,
        "notifications_sent": False,
        "paper_created": False,
        "green_created": False,
    }


def test_global_release_workflow_is_dispatched_and_publishes_without_auto_bets():
    from pathlib import Path

    workflow = Path(
        ".github/workflows/fenzobot-contextual-2026-11.yml"
    ).read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "schedule:" not in workflow
    assert "python scripts/run_fenzobot_contextual_2026_11.py" in workflow
    assert "python scripts/build_fenzobot_contextual_publication.py" in workflow
    assert "python -m src.report_notifications wait" in workflow
    assert "python -m src.report_notifications send" in workflow
    assert "TELEGRAM_BOT_TOKEN" in workflow
    assert "PAPER" not in workflow
    assert "GREEN" not in workflow
