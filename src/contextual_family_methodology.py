"""Human-governed methodology for the contextual family model.

The historical replay may refine curves inside this contract.  It may not
silently invent the tennis hierarchy, promote a secondary family above a
primary one, or turn missing evidence into a vote.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


SCHEMA_VERSION = 1
METHODOLOGY_VERSION = "contextual-family-methodology-v1"

# This is a default tennis hierarchy, not five fixed numerical weights.  The
# contextual gates decide whether a family is material in the match at hand.
FAMILY_METHODOLOGY: tuple[dict[str, Any], ...] = (
    {
        "key": "recent_form",
        "label": "Forma recente ajustada",
        "priority_tier": 1,
        "role": "PRIMARY",
        "role_label": "Família principal",
        "can_lead": True,
        "standalone_signal": True,
        "contribution_mode": "PRIMARY_DYNAMIC",
        "components": (
            "resultados_90d", "competitividade", "qualidade_vitorias",
            "qualidade_derrotas", "recencia", "transferencia_circuito",
        ),
        "context_gates": (
            "amostra_bilateral", "recencia", "forca_adversarios",
            "circuito_origem_destino", "concentracao_da_amostra",
        ),
    },
    {
        "key": "structural_strength",
        "label": "Força estrutural",
        "priority_tier": 1,
        "role": "PRIMARY_CONTEXT",
        "role_label": "Contexto estrutural principal",
        "can_lead": True,
        "standalone_signal": True,
        "contribution_mode": "NONLINEAR_CONTEXTUAL",
        "components": (
            "ranking_atual", "pontos", "patamar_competitivo",
            "trajetoria_6m_12m", "nivel_historico_recente", "inatividade",
        ),
        "context_gates": (
            "diferenca_material_entre_patamares", "representatividade_ranking",
            "trajetoria", "regresso_ou_inatividade",
        ),
    },
    {
        "key": "surface_conditions",
        "label": "Superfície e condições",
        "priority_tier": 2,
        "role": "CONTEXTUAL",
        "role_label": "Amplificador contextual",
        "can_lead": True,
        "standalone_signal": False,
        "contribution_mode": "CONTEXT_AMPLIFIER",
        "components": (
            "superficie", "indoor_outdoor", "velocidade_hard",
            "transicao_piso", "vitorias", "hold_break", "resposta",
            "recuperacao",
        ),
        "context_gates": (
            "contexto_factual", "amostra_no_contexto", "qualidade_adversarios",
            "especificidade_do_perfil", "transferencia_recente",
        ),
    },
    {
        "key": "matchup_h2h",
        "label": "Matchup e confronto direto",
        "priority_tier": 3,
        "role": "MATCHUP_OPTIONAL",
        "role_label": "Modificador de matchup",
        "can_lead": False,
        "standalone_signal": False,
        "contribution_mode": "OPTIONAL_CAPPED_MODIFIER",
        "components": (
            "h2h", "recencia_h2h", "mesmo_piso", "mesmas_condicoes",
            "evolucao_desde_h2h", "interacao_estilos", "lateralidade",
        ),
        "context_gates": (
            "amostra", "recencia", "coincidencia_contextual",
            "consistencia_direcao", "evolucao_jogadores",
        ),
    },
    {
        "key": "serve_return",
        "label": "Serviço e resposta",
        "priority_tier": 4,
        "role": "SECONDARY",
        "role_label": "Contexto secundário",
        "can_lead": False,
        "standalone_signal": False,
        "contribution_mode": "SECONDARY_CAPPED_MODIFIER",
        "components": (
            "hold", "break", "pontos_servico", "pontos_resposta",
            "baseline_carreira", "desvio_recente", "interacao_matchup",
        ),
        "context_gates": (
            "amostra_bilateral", "piso_condicoes", "forca_adversarios",
            "interacao_estilos_material",
        ),
    },
)

_BY_KEY = {row["key"]: row for row in FAMILY_METHODOLOGY}


def family_methodology(key: str) -> dict[str, Any]:
    """Return a defensive copy of one human-approved family contract."""
    definition = _BY_KEY[str(key)]
    return {
        **definition,
        "components": tuple(definition["components"]),
        "context_gates": tuple(definition["context_gates"]),
    }


def build_methodology_contract() -> dict[str, Any]:
    """Expose the complete governance contract for audits and reports."""
    return {
        "schema_version": SCHEMA_VERSION,
        "methodology_version": METHODOLOGY_VERSION,
        "hierarchy_type": "CONTEXTUAL_ORDINAL_NOT_FIXED_WEIGHTS",
        "families": [family_methodology(row["key"]) for row in FAMILY_METHODOLOGY],
        "governance": {
            "human_tennis_logic_defines_roles_and_order": True,
            "history_refines_curves_inside_contract": True,
            "history_cannot_silently_reorder_roles": True,
            "fixed_global_family_weights_are_prohibited": True,
            "market_excluded_until_probability_is_frozen": True,
            "missing_data_widens_uncertainty_without_voting": True,
            "observed_none_is_coverage_without_impact": True,
            "maximum_certainty_from_active_factors_is_prohibited": True,
            "atp_wta_challenger_require_separate_validation": True,
        },
        "pricing": {
            "family_balance_is_not_probability": True,
            "probability_requires_chronological_calibration": True,
            "fair_odd_is_inverse_of_market_free_probability": True,
            "market_enters_only_for_posterior_edge_comparison": True,
        },
        "handicap": {
            "downstream_from_match_model": True,
            "requires_own_line_probability": True,
            "negative_shows_total_and_win_conditional_coverage": True,
            "positive_highlights_total_coverage": True,
            "moneyline_probability_is_not_reused_as_handicap_probability": True,
        },
    }


def audit_combination_model(model: Mapping[str, Any]) -> dict[str, Any]:
    """Audit an existing family combiner against the approved architecture.

    This deliberately evaluates architecture, not whether past metrics looked
    good.  A globally fitted stack can remain useful as a SHADOW benchmark,
    but it is not the approved contextual methodology.
    """
    violations: list[str] = []
    warnings: list[str] = []
    raw_coefficients = model.get("coefficients") or {}
    coefficients = model.get("family_coefficients") or {
        family: raw_coefficients.get(f"{family}__logit") for family in _BY_KEY
        if raw_coefficients.get(f"{family}__logit") is not None
    }
    mode = str(model.get("mode") or "")
    if not mode and coefficients:
        mode = "FROZEN_GLOBAL_FAMILY_STACK"

    if mode in {"OUT_OF_SAMPLE_FAMILY_STACK", "FROZEN_GLOBAL_FAMILY_STACK"}:
        violations.append("FIXED_GLOBAL_FAMILY_COEFFICIENTS")
    if not model.get("contextual_activation_rules"):
        violations.append("CONTEXT_GATES_NOT_IMPLEMENTED")

    recent = coefficients.get("recent_form")
    service = coefficients.get("serve_return")
    h2h = coefficients.get("matchup_h2h")
    if isinstance(recent, (int, float)):
        if isinstance(service, (int, float)) and service > recent:
            violations.append("SECONDARY_SERVICE_EXCEEDS_RECENT_FORM")
        if isinstance(h2h, (int, float)) and h2h > recent:
            violations.append("OPTIONAL_H2H_EXCEEDS_RECENT_FORM")
    else:
        warnings.append("RECENT_FORM_COEFFICIENT_NOT_AUDITABLE")

    if model.get("market_used") is True:
        violations.append("MARKET_CONTAMINATION")

    return {
        "methodology_version": METHODOLOGY_VERSION,
        "audited_mode": mode or None,
        "status": "COMPLIANT" if not violations else "NON_COMPLIANT",
        "violations": list(dict.fromkeys(violations)),
        "warnings": list(dict.fromkeys(warnings)),
        "production_eligible": not violations,
        "shadow_benchmark_allowed": model.get("market_used") is not True,
    }
