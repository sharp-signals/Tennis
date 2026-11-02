from src.contextual_family_methodology import (
    audit_combination_model,
    build_methodology_contract,
    family_methodology,
)


def test_hierarchy_is_contextual_and_human_governed():
    contract = build_methodology_contract()
    assert contract["hierarchy_type"] == "CONTEXTUAL_ORDINAL_NOT_FIXED_WEIGHTS"
    assert contract["governance"]["history_cannot_silently_reorder_roles"] is True
    assert contract["governance"]["fixed_global_family_weights_are_prohibited"] is True


def test_recent_form_contains_quality_of_wins_and_losses():
    recent = family_methodology("recent_form")
    assert "qualidade_vitorias" in recent["components"]
    assert "qualidade_derrotas" in recent["components"]
    assert "transferencia_circuito" in recent["components"]


def test_surface_is_broader_than_service_and_contains_conditions():
    surface = family_methodology("surface_conditions")
    assert {"superficie", "indoor_outdoor", "velocidade_hard"} <= set(surface["components"])
    assert {"vitorias", "hold_break", "resposta", "recuperacao"} <= set(surface["components"])
    assert surface["contribution_mode"] == "CONTEXT_AMPLIFIER"


def test_service_and_h2h_cannot_lead_or_signal_alone():
    for key in ("serve_return", "matchup_h2h"):
        family = family_methodology(key)
        assert family["can_lead"] is False
        assert family["standalone_signal"] is False


def test_fixed_stack_with_secondary_above_form_fails_methodology_audit():
    result = audit_combination_model({
        "mode": "OUT_OF_SAMPLE_FAMILY_STACK",
        "family_coefficients": {
            "recent_form": 0.23,
            "structural_strength": 0.64,
            "surface_conditions": 0.14,
            "matchup_h2h": 0.20,
            "serve_return": 0.39,
        },
        "market_used": False,
    })
    assert result["status"] == "NON_COMPLIANT"
    assert "FIXED_GLOBAL_FAMILY_COEFFICIENTS" in result["violations"]
    assert "CONTEXT_GATES_NOT_IMPLEMENTED" in result["violations"]
    assert "SECONDARY_SERVICE_EXCEEDS_RECENT_FORM" in result["violations"]
    assert result["shadow_benchmark_allowed"] is True


def test_market_contamination_always_blocks_eligibility():
    result = audit_combination_model({
        "mode": "CONTEXT_GATED",
        "contextual_activation_rules": {"enabled": True},
        "family_coefficients": {"recent_form": 1.0, "serve_return": 0.1},
        "market_used": True,
    })
    assert "MARKET_CONTAMINATION" in result["violations"]
    assert result["production_eligible"] is False
    assert result["shadow_benchmark_allowed"] is False


def test_frozen_runtime_coefficients_are_recognised_as_global_stack():
    result = audit_combination_model({
        "coefficients": {
            "recent_form__logit": 0.2,
            "structural_strength__logit": 0.6,
            "surface_conditions__logit": 0.1,
            "matchup_h2h__logit": 0.05,
            "serve_return__logit": 0.4,
        },
        "market_used": False,
    })
    assert result["audited_mode"] == "FROZEN_GLOBAL_FAMILY_STACK"
    assert "FIXED_GLOBAL_FAMILY_COEFFICIENTS" in result["violations"]
    assert "SECONDARY_SERVICE_EXCEEDS_RECENT_FORM" in result["violations"]
