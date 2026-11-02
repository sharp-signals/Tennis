"""Read-only orchestration for the next-generation contextual factor families.

This module deliberately does not calculate a score, probability, fair odd or
betting edge.  It only normalises factual family outputs and applies governance
rules before any future chronological calibration.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .contextual_family_methodology import FAMILY_METHODOLOGY, METHODOLOGY_VERSION


SCHEMA_VERSION = 1

_OWNERSHIP = {
    "recent_form": ("recent_results", "opponent_quality", "competitiveness"),
    "structural_strength": ("current_rank", "ranking_points", "trajectory", "inactivity"),
    "surface_conditions": ("surface", "pace", "indoor_outdoor", "surface_transition"),
    "matchup_h2h": ("pair_history", "style_interaction", "handedness_matchup"),
    "serve_return": ("serve_baseline", "return_baseline", "recent_deviation"),
}
FAMILY_DEFINITIONS: tuple[dict[str, Any], ...] = tuple({
    **definition,
    "optional": definition["key"] in {"matchup_h2h", "serve_return"},
    "owns": _OWNERSHIP[definition["key"]],
} for definition in FAMILY_METHODOLOGY)

_OBSERVED_STATUSES = {
    "AVAILABLE", "READY", "BILATERAL", "COMPLETE",
    "COMPLETE_CURRENT_AND_HISTORY", "OBSERVED",
}
_PARTIAL_STATUSES = {"PARTIAL", "INSUFFICIENT", "INSUFFICIENT_SAMPLE"}
_MISSING_STATUSES = {
    "MISSING", "MISSING_DATA", "SOURCE_UNAVAILABLE", "IDENTITY_UNRESOLVED",
    "CONTEXT_MISMATCH", "UNAVAILABLE",
}
_MARKET_FLAGS = {
    "market_used", "uses_market", "market_in_probability",
    "market_in_factor", "market_in_family",
}
_PRODUCTION_FLAGS = {"production_effect", "writes_production", "changes_pricing"}


def _truthy_flag(payload: Any, forbidden: set[str]) -> bool:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            if str(key).casefold() in forbidden and value is True:
                return True
            if _truthy_flag(value, forbidden):
                return True
    elif isinstance(payload, (list, tuple)):
        return any(_truthy_flag(value, forbidden) for value in payload)
    return False


def _normalise_data_state(payload: Mapping[str, Any]) -> tuple[str, list[str]]:
    raw = payload.get("data_state") or payload.get("status") or payload.get("evidence_status")
    status = str(raw or "MISSING_DATA").strip().upper()
    reasons = [str(value) for value in payload.get("reason_codes", ()) if value]

    if status in _OBSERVED_STATUSES:
        return "OBSERVED", reasons
    if status == "OBSERVED_NONE":
        return "OBSERVED_NONE", reasons
    if status == "NOT_APPLICABLE":
        return "NOT_APPLICABLE", reasons
    if status in _PARTIAL_STATUSES:
        return "INSUFFICIENT_SAMPLE", reasons
    if status == "CONFLICTING_EVIDENCE":
        return "OBSERVED", [*reasons, "CONFLICTING_EVIDENCE"]
    if status in _MISSING_STATUSES:
        return "MISSING_DATA", [*reasons, status]
    return "MISSING_DATA", [*reasons, "UNRECOGNISED_SOURCE_STATE"]


def _normalise_signal_state(payload: Mapping[str, Any], data_state: str) -> tuple[str, str | None]:
    if data_state == "OBSERVED_NONE":
        return "NONE", None
    if data_state in {"MISSING_DATA", "NOT_APPLICABLE", "INSUFFICIENT_SAMPLE"}:
        return "UNAVAILABLE", None

    direction = str(payload.get("direction") or "").strip().casefold()
    if direction in {"a", "player_a", "left"}:
        return "DIRECTIONAL", "a"
    if direction in {"b", "player_b", "right"}:
        return "DIRECTIONAL", "b"
    if direction in {"neutral", "tie", "equal"}:
        return "NEUTRAL", "neutral"
    if direction in {"conflicting", "conflict"}:
        return "CONFLICTING", None
    # Observed facts without a calibrated transformation are not a neutral vote.
    return "UNSCORED", None


def normalise_family_observation(
    definition: Mapping[str, Any], payload: Mapping[str, Any] | None,
) -> dict[str, Any]:
    source = dict(payload or {})
    if _truthy_flag(source, _MARKET_FLAGS):
        raise ValueError(f"market contamination in family {definition['key']}")
    if _truthy_flag(source, _PRODUCTION_FLAGS):
        raise ValueError(f"production mutation in observational family {definition['key']}")

    data_state, reasons = _normalise_data_state(source)
    signal_state, direction = _normalise_signal_state(source, data_state)
    if "CONFLICTING_EVIDENCE" in reasons:
        signal_state = "CONFLICTING"
        direction = None

    reliability = source.get("reliability")
    if not isinstance(reliability, (int, float)) or isinstance(reliability, bool):
        reliability = None

    return {
        "key": definition["key"],
        "label": definition["label"],
        "role": definition["role"],
        "role_label": definition["role_label"],
        "priority_tier": definition["priority_tier"],
        "contribution_mode": definition["contribution_mode"],
        "can_lead": definition["can_lead"],
        "standalone_signal": definition["standalone_signal"],
        "context_gates": list(definition["context_gates"]),
        "optional": definition["optional"],
        "owns": list(definition["owns"]),
        "data_state": data_state,
        "signal_state": signal_state,
        "direction": direction,
        "reliability": reliability,
        "reason_codes": list(dict.fromkeys(reasons)),
        "source_lineage": source.get("source_lineage"),
        "calibration_ready": data_state in {"OBSERVED", "OBSERVED_NONE"},
        "production_effect": False,
        "score": None,
        "weight": None,
        "probability": None,
    }


def build_contextual_family_vector(
    observations: Mapping[str, Mapping[str, Any] | None],
) -> dict[str, Any]:
    """Build a governed five-family observational vector.

    Readiness means that the vector may enter a future chronological replay;
    it does not mean that it is safe for production pricing.
    """
    families = [
        normalise_family_observation(definition, observations.get(definition["key"]))
        for definition in FAMILY_DEFINITIONS
    ]
    applicable = [row for row in families if row["data_state"] != "NOT_APPLICABLE"]
    observed = [
        row for row in applicable
        if row["data_state"] in {"OBSERVED", "OBSERVED_NONE"}
    ]
    required = [row for row in families if not row["optional"]]
    primary_ready = all(
        row["data_state"] in {"OBSERVED", "OBSERVED_NONE"} for row in required
    )
    enough_families = len(observed) >= 3

    directional_primary = {
        row["direction"] for row in required
        if row["signal_state"] == "DIRECTIONAL"
    }
    cross_family_conflict = len(directional_primary) > 1
    internal_conflict = any(row["signal_state"] == "CONFLICTING" for row in families)
    conflicts = []
    if cross_family_conflict:
        conflicts.append("PRIMARY_FAMILIES_DISAGREE")
    if internal_conflict:
        conflicts.append("INTERNAL_FAMILY_CONFLICT")

    return {
        "schema_version": SCHEMA_VERSION,
        "methodology_version": METHODOLOGY_VERSION,
        "model_status": "OBSERVATIONAL_ONLY",
        "families": families,
        "coverage": {
            "observed": len(observed),
            "applicable": len(applicable),
            "ratio": round(len(observed) / len(applicable), 4) if applicable else None,
            "missing": sum(row["data_state"] == "MISSING_DATA" for row in applicable),
            "insufficient": sum(
                row["data_state"] == "INSUFFICIENT_SAMPLE" for row in applicable
            ),
        },
        "conflicts": conflicts,
        "calibration_ready": primary_ready and enough_families and not internal_conflict,
        "pricing_ready": False,
        "missing_data_increases_uncertainty": True,
        "maximum_certainty_prohibited": True,
        "market_used": False,
        "production_effect": False,
        "score": None,
        "index": None,
        "probability": None,
        "fair_odd": None,
        "dependency_policy": {
            "single_owner_per_component": True,
            "component_scores_are_not_summed": True,
            "recent_form_opponent_quality_is_not_a_structural_vote": True,
            "h2h_context_tags_are_modifiers_not_extra_families": True,
            "surface_components_form_one_family": True,
            "serve_return_is_secondary_and_cannot_create_a_standalone_signal": True,
            "family_roles_are_human_governed": True,
            "history_may_refine_but_not_reorder_roles": True,
            "fixed_global_family_weights_are_prohibited": True,
        },
    }


def build_report_family_rows(vector: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return a stable, human-facing view model for the future report."""
    state_labels = {
        "OBSERVED": "Dados observados",
        "OBSERVED_NONE": "Pesquisa concluída · sem ocorrência",
        "NOT_APPLICABLE": "Não aplicável",
        "INSUFFICIENT_SAMPLE": "Amostra insuficiente",
        "MISSING_DATA": "Dados em falta",
    }
    signal_labels = {
        "DIRECTIONAL": "Tendência observada",
        "NEUTRAL": "Equilíbrio observado",
        "NONE": "Sem impacto",
        "CONFLICTING": "Evidência contraditória",
        "UNSCORED": "Ainda sem transformação calibrada",
        "UNAVAILABLE": "Sem sinal calculável",
    }
    rows = []
    for family in vector.get("families", []):
        direction = family.get("direction")
        if direction == "a":
            headline = "Tendência para o jogador A"
        elif direction == "b":
            headline = "Tendência para o jogador B"
        elif direction == "neutral":
            headline = "Sem diferença material"
        else:
            headline = signal_labels.get(family.get("signal_state"), "Estado por validar")
        rows.append({
            "key": family["key"],
            "label": family["label"],
            "role_label": family["role_label"],
            "data_label": state_labels.get(family["data_state"], family["data_state"]),
            "signal_label": signal_labels.get(
                family["signal_state"], family["signal_state"]
            ),
            "headline": headline,
            "detail_available": bool(family.get("source_lineage")),
        })
    return rows
