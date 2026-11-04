import json
from pathlib import Path
from tempfile import TemporaryDirectory

from src.contextual_shadow_runtime import load_contract, predict_contextual_shadow
from src.contextual_shadow_store import append_observations, build_observation
from src.contextual_shadow_visual import render_contextual_shadow_panel


MODEL = Path("data/models/contextual-family-shadow-v1.json")


def _row(primary_ready=True):
    state = "OBSERVED" if primary_ready else "INSUFFICIENT_SAMPLE"
    return {
        "player_a": "alpha", "player_b": "beta", "target_a_win": False,
        "features": {
            "recent_result_balance_90d": 0.2,
            "recent_game_margin_balance_90d": 0.4,
            "recent_win_opponent_strength_90d": 0.1,
            "recent_loss_opponent_strength_90d": 0.05,
            "current_rank_log_ratio": 0.7,
            "rank_change_from_last_observation": None,
            "same_surface_result_balance_90d": 0.2,
            "career_surface_win_rate_margin": 0.1,
            "h2h_win_share_margin": None,
            "same_surface_h2h_win_share_margin": None,
            "service_points_won_surface_margin": 0.04,
            "return_points_won_surface_margin": 0.02,
            "hold_surface_margin": 0.03,
            "break_surface_margin": 0.01,
            "service_points_won_recent_margin": 0.02,
            "return_points_won_recent_margin": 0.01,
        },
        "samples": {"recent_a": 10, "recent_b": 10, "h2h": 0},
        "family_states": {
            "recent_form": {"data_state": state},
            "structural_strength": {"data_state": "OBSERVED"},
            "surface_conditions": {"data_state": "OBSERVED"},
            "matchup_h2h": {"data_state": "OBSERVED_NONE"},
            "serve_return": {"data_state": "OBSERVED"},
        },
        "orientation": {"model_a_input_side": "a", "model_b_input_side": "b"},
    }


def test_frozen_contract_is_market_free_and_shadow_only():
    contract = load_contract(MODEL)
    assert contract["market_used"] is False
    assert contract["edge_calculated"] is False
    assert contract["production_effect"] is False
    assert contract["paper_eligible"] is False
    assert contract["green_eligible"] is False
    assert set(contract["universes"]) == {"atp", "wta", "challenger"}


def test_prediction_has_five_families_interval_and_no_edge():
    result = predict_contextual_shadow(_row(), load_contract(MODEL), universe="atp")
    assert 0 < result["probability_model_a"] < 1
    assert len(result["probability_interval_90_model_a"]) == 2
    assert len(result["families"]) == 5
    assert result["market_used"] is False
    assert result["edge_calculated"] is False
    assert "edge" not in result
    assert result["paper_eligible"] is False


def test_missing_primary_family_cannot_be_ready():
    result = predict_contextual_shadow(
        _row(primary_ready=False), load_contract(MODEL), universe="wta",
    )
    assert result["quality_group"] == "PRIMARY_DEGRADED"
    assert result["status"] == "NOT_OPERATIONALLY_READY"


def test_append_only_store_deduplicates_match_and_model():
    shadow = predict_contextual_shadow(_row(), load_contract(MODEL), universe="atp")
    payload = {
        "canonical_match_instance_id": "atp:test:1", "event_key": "atp:test:1",
        "tour": "atp", "tier": "ATP 250", "commence_time_utc": "2026-11-03T10:00:00+00:00",
        "analyzed_at_utc": "2026-11-02T10:00:00+00:00",
        "player_a_id": 1, "player_b_id": 2, "player_a": "Alpha", "player_b": "Beta",
        "contextual_shadow_v1": shadow,
    }
    row = build_observation(payload)
    with TemporaryDirectory(dir=Path.cwd()) as tmp:
        path = Path(tmp) / "shadow.jsonl"
        assert append_observations([row, row], path) == 1
        assert append_observations([row], path) == 0
        saved = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        assert saved["paper_eligible"] is False
        assert saved["green_eligible"] is False


def test_isolated_visual_has_five_rows_and_no_operational_claim():
    shadow = predict_contextual_shadow(_row(), load_contract(MODEL), universe="atp")
    html = render_contextual_shadow_panel(shadow)
    assert html.count('class="ctx-family"') == 5
    assert "SHADOW · não altera decisões" in html
    assert "Sem mercado, edge, PAPER ou GREEN" in html
