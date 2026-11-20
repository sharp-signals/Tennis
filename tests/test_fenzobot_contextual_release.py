import json
import copy
import math
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.export_fenzobot_contextual_release import (
    GLOBAL_RELEASE_ID,
    build_release,
)
from src.fenzobot_contextual_runtime import (
    _centred_empirical_intervals,
    _coverage_grade,
    _dependency_grade,
    _family_lead_authority,
    _h2h_evidence_intensity,
    _impact_intensity,
    _minimum_degraded_interval_width,
    load_contract,
    predict_fenzobot_contextual,
)
from src.contextual_family_combination_v17 import mirror_contextual_row
from src.fenzobot_contextual_store import append_observations, build_observation
from scripts.generated_output_contract import is_allowed
from scripts.audit_contextual_shadow_v2 import audit_ledger


MODEL = Path("data/models/fenzobot-contextual-2026-11.json")


def test_impact_intensity_distinguishes_residual_very_slight_and_slight():
    assert _impact_intensity(0.49) == "MINIMAL"
    assert _impact_intensity(0.97) == "VERY_SLIGHT"
    assert _impact_intensity(2.07) == "SLIGHT"


def test_h2h_evidence_strength_is_separate_from_calibrated_price_impact():
    assert _h2h_evidence_intensity({
        "samples": {"h2h": 10},
        "features": {"h2h_win_share_margin": 0.4},
    }) == "STRONG"
    assert _h2h_evidence_intensity({
        "samples": {"h2h": 1},
        "features": {"h2h_win_share_margin": 1.0},
    }) == "VERY_SLIGHT"


def test_calibrated_interval_is_separate_from_family_removal_stress():
    calibrated, stress = _centred_empirical_intervals(
        0.62,
        {"wilson_lower": 0.55, "wilson_upper": 0.65},
        {"wilson_lower": 0.50, "wilson_upper": 0.70},
        quality_group="PRIMARY_READY_COMPLETE",
        sensitivity_probabilities=[0.49, 0.72],
    )
    assert all(
        abs(actual - expected) < 1e-12
        for actual, expected in zip(calibrated, (0.57, 0.67), strict=True)
    )
    assert stress == (0.49, 0.72)


def test_degraded_interval_cannot_be_narrower_than_ready_calibration_floor():
    calibration_model = {
        "groups": {
            "PRIMARY_READY_COMPLETE": {"bins": [
                {"wilson_lower": 0.54, "wilson_upper": 0.64},
            ]},
            "PRIMARY_READY_SECONDARY_GAPS": {"bins": [
                {"wilson_lower": 0.52, "wilson_upper": 0.64},
            ]},
            "PRIMARY_DEGRADED": {"bins": [
                {"wilson_lower": 0.30, "wilson_upper": 0.70},
            ]},
        },
        "global": {"bins": []},
    }
    floor = _minimum_degraded_interval_width(calibration_model)
    assert abs(floor - 0.12) < 1e-12
    calibrated, _ = _centred_empirical_intervals(
        0.60,
        {"wilson_lower": 0.57, "wilson_upper": 0.63},
        {"wilson_lower": 0.56, "wilson_upper": 0.64},
        quality_group="PRIMARY_DEGRADED",
        sensitivity_probabilities=[],
        degraded_min_width=floor,
    )
    assert all(
        abs(actual - expected) < 1e-12
        for actual, expected in zip(calibrated, (0.54, 0.66), strict=True)
    )


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
            "contextual_recent_result_main_v7": 0.2 if primary_ready else None,
            "contextual_recent_competitiveness_main_v7": 0.15 if primary_ready else None,
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
        Path("data/models/contextual-family-combination-v18.json"),
        Path("data/models/contextual-probability-uncertainty-v18.json"),
    )
    assert manifest["global_release_id"] == GLOBAL_RELEASE_ID
    assert manifest["components"] == {
        "ranking_model": "contextual-ranking-v7.1",
        "family_combination": "contextual-family-combination-v18-unanimous-consensus",
        "probability_calibration": "contextual-probability-uncertainty-v18",
        "runtime_generation": 21,
    }
    assert manifest["promotion_authorized"] is False
    assert [item["runtime_generation"] for item in manifest[
        "accepted_historical_releases"
    ]] == [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]
    assert runtime["configuration_fingerprint"] == manifest["configuration_fingerprint"]


def test_runtime_contract_reproduces_export_and_is_market_free():
    manifest, built = build_release(
        Path("data/models/contextual-family-combination-v18.json"),
        Path("data/models/contextual-probability-uncertainty-v18.json"),
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
    assert result["runtime_generation"] == 21
    assert result["family_sensitivity"]["method"] == "LEAVE_ONE_FAMILY_OUT"
    assert all(
        "internal_trace" in family and family["internal_trace"]["status"] == "READY"
        for family in result["families"]
    )
    lower, upper = result["probability_interval_90_model_a"]
    assert lower <= result["probability_model_a"] <= upper
    stress_lower, stress_upper = result["probability_stress_interval_model_a"]
    assert stress_lower <= lower <= upper <= stress_upper
    assert all(
        stress_lower
        <= scenario["probability_model_a_without_family"]
        <= stress_upper
        for scenario in result["family_sensitivity"]["scenarios"]
    )
    assert result["market_used"] is False
    assert result["edge_calculated"] is False
    assert result["paper_eligible"] is False
    assert "edge" not in result


def test_runtime_carries_recent_tier_credit_ledger_into_family_audit():
    row = _row()
    row["candidate_equation_audit"] = {
        "recent_form_tier_reliable_v5": {"tier_win_credit": {
            "a_sample": 1,
            "b_sample": 1,
            "a_credit": 0.5,
            "b_credit": 0.0,
            "a_ledger": [{
                "event_date": "2026-11-01", "tournament": "Test Masters",
                "round": "QF", "opponent": "beta", "won": True,
                "competition_level": "M", "category_points": 1000,
                "recency_weight": 1.0, "weighted_credit": 0.5,
            }],
            "b_ledger": [],
        }},
    }
    result = predict_fenzobot_contextual(
        row, load_contract(MODEL), universe="atp",
    )
    recent = next(
        family for family in result["families"]
        if family["key"] == "recent_form"
    )
    audit = recent["context_audit"]["tier_win_credit"]
    assert audit["a_credit"] == 0.5
    assert audit["a_ledger"][0]["tournament"] == "Test Masters"


def test_final_runtime_probability_is_invariant_to_player_order():
    contract = load_contract(MODEL)
    for universe in ("atp", "wta"):
        direct = predict_fenzobot_contextual(_row(), contract, universe=universe)
        mirrored = predict_fenzobot_contextual(
            mirror_contextual_row(_row()), contract, universe=universe,
        )
        assert math.isclose(
            direct["probability_model_a"],
            1.0 - mirrored["probability_model_a"],
            abs_tol=2e-6,
        )


def test_runtime_enforces_v18_realised_hierarchy_contract_by_universe():
    result = predict_fenzobot_contextual(
        _row(), load_contract(MODEL), universe="atp",
    )
    contributions = {
        item["key"]: abs(float(item["logit_contribution"]))
        for item in result["families"]
    }
    assert all(math.isfinite(value) for value in contributions.values())
    hierarchy = load_contract(MODEL)["universes"]["atp"][
        "combination"
    ]["realized_hierarchy"]
    assert hierarchy["orientation_policy"] == "PAIRED_DIRECTIONAL_ANTISYMMETRY"
    assert hierarchy["family_coefficients_preserve_primary_priority"] is True
    assert hierarchy["unanimous_policy"] == (
        "FITTED_WEIGHTED_REINFORCEMENT_IF_BOTH_PRIMARIES_ALIGN"
    )
    assert hierarchy["conflicting_evidence_keeps_strict_ordered_caps"] is True
    assert hierarchy["secondary_only_prediction_forbidden"] is True
    wta_hierarchy = load_contract(MODEL)["universes"]["wta"][
        "combination"
    ]["realized_hierarchy"]
    assert wta_hierarchy["unanimous_policy"] == (
        "STRONGEST_PRIMARY_INDIVIDUAL_CAP"
    )
    assert wta_hierarchy["promotion_gate"] == "REJECTED_FALLBACK_TO_V17"


def test_missing_primary_family_fails_closed_for_operational_readiness():
    contract = load_contract(MODEL)
    result = predict_fenzobot_contextual(
        _row(primary_ready=False), contract, universe="atp",
    )
    assert result["quality_group"] == "PRIMARY_DEGRADED"
    assert result["status"] == "NOT_OPERATIONALLY_READY"
    assert "PRIMARY_FAMILY_UNAVAILABLE" in result["reason_codes"]
    wta = predict_fenzobot_contextual(
        _row(primary_ready=False), contract, universe="wta",
    )
    lower, upper = wta["probability_interval_90_model_a"]
    expected_floor = _minimum_degraded_interval_width(
        contract["universes"]["wta"]["calibration"]["calibration_model"],
    )
    assert upper - lower >= expected_floor - 2e-6


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
