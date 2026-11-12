from scripts.run_contextual_shadow_v2 import (
    _model_player_id,
    _player,
    _provider_h2h_override,
    run_shadow_only,
)
from datetime import datetime, timezone
from unittest.mock import patch


def test_player_reads_nested_fixture_identity():
    assert _player({"player1": {"id": 7, "name": "Alpha"}}, 1) == (
        "Alpha", 7,
    )


def test_model_player_id_preserves_alphabetical_orientation():
    common = {
        "original_a": "Zed Player",
        "original_b": "Alpha Player",
        "resolved_a": "Zed P.",
        "resolved_b": "Alpha P.",
        "id_a": 10,
        "id_b": 20,
    }
    assert _model_player_id("Alpha P.", **common) == 20
    assert _model_player_id("Zed P.", **common) == 10


def test_provider_h2h_override_preserves_factual_matches_for_report():
    matches = [{
        "date": "2026-10-01T12:00:00+00:00",
        "player1Id": 10,
        "player2Id": 20,
        "match_winner": 10,
        "tournamentId": 99,
        "result": "6-4 6-3",
        "roundName": "QF",
    }]
    with (
        patch(
            "scripts.run_contextual_shadow_v2.fetch_data."
            "fetch_h2h_matches_with_coverage",
            return_value=(matches, {"source": "test_h2h"}),
        ),
        patch(
            "scripts.run_contextual_shadow_v2.fetch_data.get_tournament_info",
            return_value={"name": "Indoor Open", "surface": "I.hard"},
        ),
    ):
        result = _provider_h2h_override(
            tour="atp", player_a_id=10, player_b_id=20,
            current_surface="I.hard",
            cutoff=datetime(2026, 11, 1, tzinfo=timezone.utc),
        )
    assert result["eligible_matches"] == 1
    assert result["matches"] == [{
        "event_date": "2026-10-01",
        "tournament": "Indoor Open",
        "surface": "I.hard",
        "winner_side": "a",
        "score": "6-4 6-3",
        "round": "QF",
    }]


def test_shadow_only_runner_fails_closed_without_explicit_activation():
    import os

    previous = os.environ.pop("CONTEXTUAL_SHADOW_V2_MODE", None)
    try:
        try:
            run_shadow_only(max_matches=1)
        except RuntimeError as exc:
            assert "CONTEXTUAL_SHADOW_V2_DISABLED" in str(exc)
        else:
            raise AssertionError("runner unexpectedly activated")
    finally:
        if previous is not None:
            os.environ["CONTEXTUAL_SHADOW_V2_MODE"] = previous


def test_shadow_only_empty_run_has_no_operational_side_effects():
    fake_contract = {
        "model_version": "contextual-family-shadow-v2",
        "configuration_fingerprint": "frozen-test-fingerprint",
    }
    with (
        patch(
            "scripts.run_contextual_shadow_v2.activation_state",
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
        patch(
            "scripts.run_contextual_shadow_v2.fetch_data.flush_tournament_cache",
        ),
        patch(
            "scripts.run_contextual_shadow_v2.fetch_data.flush_fixtures_cache",
        ),
        patch(
            "scripts.run_contextual_shadow_v2.fetch_data.persist_rapidapi_usage",
        ),
        patch("scripts.run_contextual_shadow_v2.load_contract", return_value=fake_contract),
        patch("scripts.run_contextual_shadow_v2.append_observations", return_value=0),
        patch(
            "scripts.run_contextual_shadow_v2.existing_observation_ids",
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
        patch("scripts.run_contextual_shadow_v2._write_json_atomic") as write_summary,
    ):
        summary = run_shadow_only(max_matches=1)
    assert summary["eligible_main_tour"] == 0
    assert summary["observations_added"] == 0
    assert summary["handicap_evidence_added"] == 0
    assert summary["isolation"] == {
        "market_used": False,
        "reports_published": False,
        "notifications_sent": False,
        "paper_created": False,
        "green_created": False,
    }
    write_summary.assert_called_once()


def test_shadow_workflow_is_manual_and_does_not_publish_reports():
    from pathlib import Path

    workflow = Path(".github/workflows/contextual-shadow-v2.yml").read_text(
        encoding="utf-8",
    )
    assert "workflow_dispatch:" in workflow
    assert "schedule:" not in workflow
    assert "python scripts/run_contextual_shadow_v2.py" in workflow
    assert "python scripts/settle_contextual_shadow_v2.py" in workflow
    assert "src.report_notifications" not in workflow
    assert "TELEGRAM_BOT_TOKEN" not in workflow
