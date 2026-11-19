"""Consensus-preserving contextual family combination v18.

The fitted family coefficients remain the hierarchy.  When both primary
families and every active secondary family agree, the fitted evidence is kept
instead of clipping every secondary to a weak primary.  Any directional
conflict keeps the strict realised hierarchy from v17.
"""

from __future__ import annotations

from typing import Any

from .contextual_family_combination_v2 import _attach_predictions
from .contextual_family_combination_v17 import (
    FAMILY_ORDER,
    _logit,
    _sigmoid,
    govern_recent_form_signal,
    mirror_contextual_row,
)
from .contextual_family_hierarchy import (
    PRIMARY_FAMILIES,
    govern_consensus_with_individual_cap,
    govern_ordered_family_contributions,
)


MODEL_VERSION = "contextual-family-combination-v18-unanimous-consensus"
UNCLIPPED_CONSENSUS_POLICY = (
    "FITTED_WEIGHTED_REINFORCEMENT_IF_BOTH_PRIMARIES_ALIGN"
)
V17_CONSENSUS_POLICY = "STRONGEST_PRIMARY_INDIVIDUAL_CAP"


def validate_combination_v18_contract(contract: dict[str, Any]) -> None:
    if contract.get("model_version") != MODEL_VERSION:
        raise ValueError("unexpected contextual combination v18 model version")
    if contract.get("mode") != "SHADOW_ONLY":
        raise ValueError("combination v18 contract must remain SHADOW_ONLY")
    if any(contract.get(key) is not False for key in (
        "market_used", "production_effect", "promotion_authorized",
    )):
        raise ValueError("combination v18 isolation invariant failed")


def _direction(value: float) -> int:
    return 1 if value > 0.0 else -1 if value < 0.0 else 0


def govern_v18_family_contributions(
    contributions: dict[str, float],
    *,
    unanimous_policy: str = UNCLIPPED_CONSENSUS_POLICY,
) -> tuple[dict[str, float], dict[str, Any]]:
    """Keep fitted unanimous evidence; fail closed on every conflict.

    Consensus requires both primary families to be active and aligned.  Zero
    or absent evidence never votes.  The statistical coefficients already
    make each primary family individually stronger than each secondary; the
    runtime must not erase several independent aligned signals by replacing
    all of them with the same artificial ceiling.
    """
    raw = {family: float(contributions.get(family, 0.0)) for family in FAMILY_ORDER}
    primary_directions = [_direction(raw[family]) for family in PRIMARY_FAMILIES]
    active_directions = {
        _direction(value) for value in raw.values() if _direction(value)
    }
    if unanimous_policy == V17_CONSENSUS_POLICY:
        if len(active_directions) == 1:
            governed, audit = govern_consensus_with_individual_cap(
                raw, consensus_cap_basis="strongest_primary",
            )
        else:
            governed, audit = govern_ordered_family_contributions(raw)
        return governed, {
            **audit,
            "candidate_policy_rejected": True,
            "absence_votes": False,
        }
    unanimous = (
        all(primary_directions)
        and len(set(primary_directions)) == 1
        and active_directions == {primary_directions[0]}
    )
    if unanimous:
        if unanimous_policy != UNCLIPPED_CONSENSUS_POLICY:
            raise ValueError(
                f"unsupported v18 unanimous policy: {unanimous_policy}"
            )
        return raw, {
            "applied": False,
            "policy": "UNANIMOUS_FITTED_WEIGHTED_REINFORCEMENT",
            "consensus_reinforcement": True,
            "both_primaries_active_and_aligned": True,
            "secondary_clipping": False,
            "capped_families": [],
            "absence_votes": False,
        }
    governed, audit = govern_ordered_family_contributions(raw)
    return governed, {
        **audit,
        "policy": "STRICT_CONFLICT_BLOCK_CAP",
        "consensus_reinforcement": False,
        "both_primaries_active_and_aligned": False,
    }


def predict_contextual_combination_v18(
    rows: list[dict[str, Any]], *, universe: str, contract: dict[str, Any],
) -> dict[str, Any]:
    """Predict symmetrically with unanimous reinforcement and strict conflicts."""
    validate_combination_v18_contract(contract)
    universe = str(universe).casefold()
    model = contract.get("universes", {}).get(universe)
    if not isinstance(model, dict):
        raise ValueError(f"combination v18 missing universe: {universe}")
    calibration = model["realized_hierarchy"]["post_hierarchy_calibration"]
    if abs(float(calibration.get("intercept", 0.0))) > 1e-12:
        raise ValueError("combination v18 calibration intercept must be zero")

    attached = _attach_predictions(
        rows, model["runtime_family_models"], universe=universe,
    )
    mirrored = _attach_predictions(
        [mirror_contextual_row(row) for row in rows],
        model["runtime_family_models"], universe=universe,
    )
    hierarchy = model["realized_hierarchy"]
    unanimous_policy = str(
        hierarchy.get("unanimous_policy", UNCLIPPED_CONSENSUS_POLICY)
    )
    h2h_multiplier = float(hierarchy.get("h2h_multiplier", 1.0))
    recent_governance = hierarchy["recent_form_governance"]
    probabilities = []
    for row, mirror in zip(attached, mirrored, strict=True):
        family_signals: dict[str, float | None] = {}
        for family in FAMILY_ORDER:
            direct = row["family_probabilities"].get(family)
            reverse = mirror["family_probabilities"].get(family)
            family_signals[family] = (
                None if direct is None or reverse is None else
                0.5 * (_logit(direct) - _logit(reverse))
            )
        if family_signals["recent_form"] is None:
            recent_audit = {"status": "UNAVAILABLE", "absence_votes": False}
        else:
            recent_signal, recent_audit = govern_recent_form_signal(
                row, model["runtime_family_models"]["recent_form"],
                result_weight_floor=float(
                    recent_governance["result_weight_floor"]
                ),
                opposing_modifier_cap=float(
                    recent_governance["opposing_modifier_cap"]
                ),
            )
            family_signals["recent_form"] = recent_signal
        row["family_probabilities"] = {
            family: (_sigmoid(signal) if signal is not None else None)
            for family, signal in family_signals.items()
        }
        raw = {
            family: (
                float(model["family_coefficients"].get(family, 0.0))
                * float(family_signals[family])
                * (h2h_multiplier if family == "matchup_h2h" else 1.0)
                if family_signals[family] is not None else 0.0
            )
            for family in FAMILY_ORDER
        }
        governed, audit = govern_v18_family_contributions(
            raw, unanimous_policy=unanimous_policy,
        )
        slope = float(calibration["slope"])
        final_logit = slope * sum(governed.values())
        row["pre_hierarchy_family_contributions"] = raw
        row["realized_family_contributions"] = governed
        row["calibrated_realized_family_contributions"] = {
            family: slope * contribution
            for family, contribution in governed.items()
        }
        row["realized_hierarchy_audit"] = {
            **audit,
            "hierarchy_contract": "ORDER_INVARIANT_REALIZED_HIERARCHY",
            "missingness_policy": "ABSENCE_NEVER_VOTES",
            "h2h_multiplier": h2h_multiplier,
            "recent_form_governance": recent_audit,
        }
        row["orientation_audit"] = {
            "policy": "PAIRED_DIRECTIONAL_ANTISYMMETRY",
            "alphabetical_order_votes": False,
            "neutral_probability": 0.5,
        }
        probabilities.append(_sigmoid(final_logit))
    return {
        "model_version": MODEL_VERSION,
        "universe": universe,
        "rows": attached,
        "probabilities": probabilities,
        "refit_performed": False,
        "market_used": False,
        "production_effect": False,
    }
