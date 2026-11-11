import json
import copy
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.export_fenzobot_contextual_release import (
    GLOBAL_RELEASE_ID,
    build_release,
)
from src.fenzobot_contextual_runtime import (
    _coverage_grade,
    _dependency_grade,
    _family_lead_authority,
    load_contract,
    predict_fenzobot_contextual,
)
from src.fenzobot_contextual_store import append_observations, build_observation
from scripts.generated_output_contract import is_allowed
from scripts.audit_contextual_shadow_v2 import audit_ledger


MODEL = Path("data/models/fenzobot-contextual-2026-11.json")


def test_family_coverage_distinguishes_neutral_partial_and_unavailable():
    assert _coverage_grade("OBSERVED", 0.6) == "SOLID"
    assert _coverage_grade("INSUFFICIENT_SAMPLE", 0.6) == "PARTIAL"
    assert _coverage_grade("OBSERVED_NONE", None) == "OBSERVED_NEUTRAL"
    assert _coverage_grade("OBSERVED", None) == "UNAVAILABLE"


def test_leave_one_family_out_dependency_is_graded_not_binary():
    assert _dependency_grade(
        full_probability=0.51, without_probability=0.49, central_side="a",
    ) == "BALANCED_SENSITIVE"
    assert _dependency_grade(
        full_probability=0.56, without_probability=0.48, central_side="a",
    ) == "MATERIAL_DEPENDENCE"
    assert _dependency_grade(
        full_probability=0.65, without_probability=0.48, central_side="a",
    ) == "CRITICAL_DEPENDENCE"


def test_only_solid_coherent_primary_family_may_legitimately_lead():
    primary = {
        "key": "structural_strength",
        "coverage_grade": "SOLID",
        "internal_trace": {"features": [
            {"missing": False, "logit_contribution": -0.8},
            {"missing": False, "logit_contribution": -0.4},
            {"missing": False, "logit_contribution": 0.1},
        ]},
    }
    assert _family_lead_authority(primary, contribution=-1.0)["authorised"]
    secondary = {**primary, "key": "serve_return"}
    assert not _family_lead_authority(
        secondary, contribution=-1.0,
    )["authorised"]
    partial = {**primary, "coverage_grade": "PARTIAL"}
    assert not _family_lead_authority(partial, contribution=-1.0)["authorised"]


def _row(primary_ready=True, *, context="hard_outdoor"):
    recent = "OBSERVED" if primary_ready else "INSUFFICIENT_SAMPLE"
    return {
        "player_a": "alpha",
        "player_b": "beta",
        "target_a_win": False,
        "features": {
            "contextual_recent_result_core_v1": 0.2 if primary_ready else None,
            "contextual_recent_competitiveness_v1": 0.15 if primary_ready else None,
            "contextual_recent_win_quality_v1": 0.1 if primary_ready else None,
            "contextual_structural_material_rank_core_v6": 0.5,
            "contextual_structural_representative_rank_core_v6": 0.2,
            "contextual_structural_points_log_ratio_v6": 0.3,
            "contextual_structural_return_rank_contraction_v7": 0.0,
            "contextual_structural_return_points_contraction_v7": 0.0,
            "contextual_structural_return_friction_margin_v7": 0.0,
            "contextual_structural_trajectory_margin_v3": 0.1,
            "contextual_structural_inactivity_margin_v3": 0.0,
            "contextual_structural_recovery_margin_v3": 0.0,
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


def test_manifest_names_every_internal_component_without_global_version_ambiguity():
    manifest, runtime = build_release(
        Path("data/models/contextual-family-combination-v4.json"),
        Path("data/models/contextual-probability-uncertainty-v4.json"),
    )
    assert manifest["global_release_id"] == GLOBAL_RELEASE_ID
    assert manifest["components"] == {
        "ranking_model": "contextual-ranking-v7.1",
        "family_combination": "contextual-family-combination-v4-ranking-v7",
        "probability_calibration": "contextual-probability-uncertainty-v4",
        "runtime_generation": 6,
    }
    assert manifest["promotion_authorized"] is False
    assert [item["runtime_generation"] for item in manifest[
        "accepted_historical_releases"
    ]] == [3, 4, 5]
    assert runtime["configuration_fingerprint"] == manifest["configuration_fingerprint"]


def test_runtime_contract_reproduces_export_and_is_market_free():
    manifest, built = build_release(
        Path("data/models/contextual-family-combination-v4.json"),
        Path("data/models/contextual-probability-uncertainty-v4.json"),
    )
    contract = load_contract(MODEL)
    assert built == contract
    assert contract["global_release_id"] == manifest["global_release_id"]
    assert contract["market_used_for_prediction"] is False
    assert contract["production_effect"] is False


def test_prediction_exposes_release_components_probability_and_fair_odds():
    result = predict_fenzobot_contextual(
        _row(), load_contract(MODEL), universe="atp",
    )
    assert result["global_release_id"] == GLOBAL_RELEASE_ID
    assert result["component_versions"]["ranking_model"] == "contextual-ranking-v7.1"
    assert 0.0 < result["probability_model_a"] < 1.0
    assert len(result["probability_interval_90_model_a"]) == 2
    assert result["fair_odd_model_a"]["central"] > 1.0
    assert len(result["families"]) == 5
    assert result["runtime_generation"] == 6
    assert result["family_sensitivity"]["method"] == "LEAVE_ONE_FAMILY_OUT"
    assert all(
        "internal_trace" in family and family["internal_trace"]["status"] == "READY"
        for family in result["families"]
    )
    lower, upper = result["probability_interval_90_model_a"]
    assert lower <= result["probability_model_a"] <= upper
    assert all(
        lower <= scenario["probability_model_a_without_family"] <= upper
        for scenario in result["family_sensitivity"]["scenarios"]
    )
    assert result["market_used"] is False
    assert result["edge_calculated"] is False
    assert result["paper_eligible"] is False
    assert "edge" not in result


def test_missing_primary_family_fails_closed_for_operational_readiness():
    result = predict_fenzobot_contextual(
        _row(primary_ready=False), load_contract(MODEL), universe="atp",
    )
    assert result["quality_group"] == "PRIMARY_DEGRADED"
    assert result["status"] == "NOT_OPERATIONALLY_READY"
    assert "PRIMARY_FAMILY_UNAVAILABLE" in result["reason_codes"]


def test_release_store_is_new_append_only_ledger():
    shadow = predict_fenzobot_contextual(
        _row(), load_contract(MODEL), universe="atp",
    )
    payload = {
        "canonical_match_instance_id": "atp:test:global-release",
        "tour": "atp",
        "tier": "ATP 250",
        "commence_time_utc": "2026-11-11T10:00:00+00:00",
        "analyzed_at_utc": "2026-11-10T10:00:00+00:00",
        "player_a_id": 1,
        "player_b_id": 2,
        "player_a": "Alpha",
        "player_b": "Beta",
        "competition": {"tournament_name": "Test Open"},
        "fenzobot_contextual_2026_11": shadow,
    }
    row = build_observation(payload)
    assert row is not None
    with TemporaryDirectory(dir=Path.cwd()) as tmp:
        path = Path(tmp) / "release.jsonl"
        assert append_observations([row, row], path) == 1
        assert append_observations([row], path) == 0
        saved = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        assert saved["schema_version"] == 3
        assert saved["contextual_shadow"]["global_release_id"] == GLOBAL_RELEASE_ID
        assert saved["paper_eligible"] is False
        assert saved["green_eligible"] is False


def test_audit_accepts_declared_generation_three_but_rejects_unknown_history():
    shadow = predict_fenzobot_contextual(
        _row(), load_contract(MODEL), universe="atp",
    )
    historical = copy.deepcopy(shadow)
    historical["runtime_generation"] = 3
    historical["component_versions"]["runtime_generation"] = 3
    historical["configuration_fingerprint"] = (
        "05a0303b93ca8a5abc5edb3adcec235749737c54597a47333bb5bad67e2c707a"
    )
    payload = {
        "canonical_match_instance_id": "atp:test:historical-release",
        "tour": "atp", "tier": "ATP 250",
        "commence_time_utc": "2026-11-11T10:00:00+00:00",
        "analyzed_at_utc": "2026-11-10T10:00:00+00:00",
        "player_a": "Alpha", "player_b": "Beta",
        "fenzobot_contextual_2026_11": historical,
    }
    row = build_observation(payload)
    with TemporaryDirectory(dir=Path.cwd()) as tmp:
        ledger = Path(tmp) / "release.jsonl"
        ledger.write_text(json.dumps(row) + "\n", encoding="utf-8")
        result = audit_ledger(ledger, MODEL)
        assert result["status"] == "HEALTHY"
        assert result["counts"]["release:historical"] == 1

        unknown = copy.deepcopy(row)
        unknown["contextual_shadow"]["configuration_fingerprint"] = "unknown"
        ledger.write_text(json.dumps(unknown) + "\n", encoding="utf-8")
        result = audit_ledger(ledger, MODEL)
        assert result["status"] == "CONTRACT_VIOLATION"
        assert any(
            item["code"] == "FINGERPRINT_MISMATCH"
            for item in result["violations"]
        )


def test_release_generated_ledgers_are_allowed_without_expanding_to_code():
    assert is_allowed(
        "data/contextual_shadow_observations-fenzobot-contextual-2026-11.jsonl",
        "bot",
    )
    assert is_allowed(
        "data/contextual_shadow_handicap_evidence-fenzobot-contextual-2026-11.jsonl",
        "bot",
    )
    assert is_allowed(
        "data/contextual_shadow_moneyline_evidence-fenzobot-contextual-2026-11.jsonl",
        "bot",
    )
