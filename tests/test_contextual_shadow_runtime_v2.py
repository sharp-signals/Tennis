import json
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.export_contextual_shadow_model_v2 import build_contract
from scripts.generated_output_contract import is_allowed
from src.contextual_shadow_runtime_v2 import (
    load_contract,
    predict_contextual_shadow_v2,
)
from src.contextual_shadow_store_v2 import append_observations, build_observation


MODEL = Path("data/models/contextual-family-shadow-v2.json")


def _row(primary_ready=True, *, context="hard_outdoor"):
    recent = "OBSERVED" if primary_ready else "INSUFFICIENT_SAMPLE"
    return {
        "player_a": "alpha",
        "player_b": "beta",
        "features": {
            "contextual_recent_result_core_v1": 0.2 if primary_ready else None,
            "contextual_recent_competitiveness_v1": 0.15 if primary_ready else None,
            "contextual_recent_win_quality_v1": 0.1 if primary_ready else None,
            "current_rank_log_ratio": 0.5,
            "exact_surface_career_margin_shrunk": 0.1,
            "exact_surface_previous_margin_shrunk": 0.05,
            "exact_surface_current_margin_shrunk": 0.08,
            "contextual_h2h_global_shrunk_v1": None,
            "service_points_won_surface_margin_shrunk_v1": 0.02,
            "return_points_won_surface_margin_shrunk_v1": 0.01,
            "service_points_won_recent_deviation_v1": 0.01,
            "return_points_won_recent_deviation_v1": 0.0,
        },
        "family_states": {
            "recent_form": {"data_state": recent},
            "structural_strength": {"data_state": "OBSERVED"},
            "surface_conditions": {"data_state": "OBSERVED"},
            "matchup_h2h": {"data_state": "OBSERVED_NONE"},
            "serve_return": {"data_state": "OBSERVED"},
        },
        "diagnostics": {"surface_context": context},
        "orientation": {
            "model_a_input_side": "a",
            "model_b_input_side": "b",
        },
    }


def test_exported_contract_is_market_free_and_atp_wta_only():
    contract = load_contract(MODEL)
    assert contract["market_used"] is False
    assert contract["edge_calculated"] is False
    assert contract["production_effect"] is False
    assert set(contract["universes"]) == {"atp", "wta"}


def test_exporter_reproduces_frozen_contract():
    built = build_contract(
        Path("data/models/contextual-family-combination-v2.json"),
        Path("data/models/contextual-probability-uncertainty-v2.json"),
    )
    assert built == load_contract(MODEL)


def test_prediction_contains_probability_interval_fair_odds_and_no_edge():
    result = predict_contextual_shadow_v2(
        _row(), load_contract(MODEL), universe="atp",
    )
    assert 0.0 < result["probability_model_a"] < 1.0
    assert len(result["probability_interval_90_model_a"]) == 2
    assert result["fair_odd_model_a"]["central"] > 1.0
    assert len(result["families"]) == 5
    assert result["market_used"] is False
    assert result["edge_calculated"] is False
    assert result["paper_eligible"] is False
    assert "edge" not in result


def test_missing_primary_family_is_recorded_but_not_ready():
    result = predict_contextual_shadow_v2(
        _row(primary_ready=False), load_contract(MODEL), universe="atp",
    )
    assert result["quality_group"] == "PRIMARY_DEGRADED"
    assert result["status"] == "NOT_OPERATIONALLY_READY"
    assert "PRIMARY_FAMILY_UNAVAILABLE" in result["reason_codes"]


def test_wta_indoor_is_diagnostic_secondary_gap_not_primary_failure():
    result = predict_contextual_shadow_v2(
        _row(context="hard_indoor"), load_contract(MODEL), universe="wta",
    )
    assert result["quality_group"] == "PRIMARY_READY_SECONDARY_GAPS"
    surface = next(
        family for family in result["families"]
        if family["key"] == "surface_conditions"
    )
    assert surface["probability_model_a"] is None


def test_append_only_v2_store_deduplicates_canonical_model_pair():
    shadow = predict_contextual_shadow_v2(
        _row(), load_contract(MODEL), universe="atp",
    )
    payload = {
        "canonical_match_instance_id": "atp:test:shadow-v2",
        "event_key": "atp:test:shadow-v2",
        "tour": "atp",
        "tier": "ATP 250",
        "commence_time_utc": "2026-11-05T10:00:00+00:00",
        "analyzed_at_utc": "2026-11-04T10:00:00+00:00",
        "player_a_id": 1,
        "player_b_id": 2,
        "player_a": "Alpha",
        "player_b": "Beta",
        "contextual_shadow_v2": shadow,
    }
    row = build_observation(payload)
    with TemporaryDirectory(dir=Path.cwd()) as tmp:
        path = Path(tmp) / "shadow-v2.jsonl"
        assert append_observations([row, row], path) == 1
        assert append_observations([row], path) == 0
        saved = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        assert saved["schema_version"] == 2
        assert saved["paper_eligible"] is False
        assert saved["green_eligible"] is False


def test_v2_store_is_allowed_for_bot_generated_publication():
    assert is_allowed("data/contextual_shadow_observations-v2.jsonl", "bot")
    assert is_allowed("data/contextual_shadow_outcomes-v2.jsonl", "bot")
    assert is_allowed("data/contextual_shadow_market-v2.jsonl", "bot")
