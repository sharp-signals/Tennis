"""Candidate internal equation for the surface-and-conditions family."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


SCHEMA_VERSION = 1
EQUATION_VERSION = "surface-conditions-context-v1"
EQUATION_VERSION_V2 = "surface-conditions-context-v2-no-transition-vote"
EQUATION_VERSION_V3 = "surface-conditions-context-v3-surface-baseline-only"


@dataclass(frozen=True)
class SurfaceEquationConfig:
    prior_matches_surface: float = 10.0
    prior_matches_specific_context: float = 14.0
    contextual_max_adjustment: float = 0.30
    transition_max_adjustment: float = 0.12


def _record_signal(record: Any, prior_matches: float) -> tuple[float | None, float]:
    if not isinstance(record, dict):
        return None, 0.0
    try:
        matches = int(record.get("matches") or 0)
        wins = int(record.get("wins") or 0)
    except (TypeError, ValueError):
        return None, 0.0
    if matches <= 0 or wins < 0 or wins > matches:
        return None, 0.0
    # Symmetric beta shrinkage expressed directly as a signed win balance.
    signal = (2.0 * wins - matches) / (matches + prior_matches)
    reliability = matches / (matches + prior_matches)
    return max(-1.0, min(1.0, signal)), reliability


def _difference(
    a: Any, b: Any, prior_matches: float,
) -> tuple[float | None, float]:
    signal_a, reliability_a = _record_signal(a, prior_matches)
    signal_b, reliability_b = _record_signal(b, prior_matches)
    if signal_a is None or signal_b is None:
        return None, 0.0
    return max(-1.0, min(1.0, (signal_a - signal_b) / 2.0)), min(
        reliability_a, reliability_b,
    )


def _specific_context(
    pair: dict[str, Any], config: SurfaceEquationConfig,
) -> tuple[str | None, float | None, float]:
    # Use the most specific factual context once.  Pace, venue and surface are
    # overlapping samples and must never be added as independent votes.
    candidates: list[tuple[int, str, float, float]] = []
    for specificity, key in ((3, "pace_component"), (2, "venue_component")):
        component = pair.get(key) or {}
        signal, reliability = _difference(
            component.get("a"), component.get("b"),
            config.prior_matches_specific_context,
        )
        if signal is not None:
            candidates.append((specificity, key, signal, reliability))
    if not candidates:
        return None, None, 0.0
    _, key, signal, reliability = max(
        candidates, key=lambda row: (row[0], row[3]),
    )
    return key, signal, reliability


def evaluate_surface_conditions(
    pair: dict[str, Any], *, config: SurfaceEquationConfig | None = None,
) -> dict[str, Any]:
    """Produce one family signal without summing overlapping contexts."""
    cfg = config or SurfaceEquationConfig()
    if pair.get("status") != "READY" or pair.get("context_consistent") is not True:
        return {
            "schema_version": SCHEMA_VERSION,
            "equation_version": EQUATION_VERSION,
            "status": "CONTEXT_NOT_READY",
            "family_signal": None,
            "market_used": False,
            "production_effect": False,
        }

    surface = pair.get("surface_component") or {}
    baseline, baseline_reliability = _difference(
        surface.get("a"), surface.get("b"), cfg.prior_matches_surface,
    )
    if baseline is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "equation_version": EQUATION_VERSION,
            "status": "INSUFFICIENT_BILATERAL_SURFACE_SAMPLE",
            "family_signal": None,
            "market_used": False,
            "production_effect": False,
        }

    selected_context, context_signal, context_reliability = _specific_context(pair, cfg)
    context_adjustment = 0.0
    if context_signal is not None:
        # The more specific context modifies the surface baseline; it is not a
        # second full vote.  Small samples are automatically shrunk.
        context_adjustment = (
            cfg.contextual_max_adjustment * context_reliability
            * (context_signal - baseline)
        )

    transition = pair.get("transition_component") or {}
    transition_a = transition.get("a") is True
    transition_b = transition.get("b") is True
    transition_signal = float(transition_b) - float(transition_a)
    transition_adjustment = cfg.transition_max_adjustment * transition_signal

    signal = max(-1.0, min(1.0, baseline + context_adjustment + transition_adjustment))
    reliability = baseline_reliability
    if context_signal is not None:
        reliability = max(reliability, 0.75 * context_reliability)
    reliability = max(0.0, min(1.0, reliability))

    return {
        "schema_version": SCHEMA_VERSION,
        "equation_version": EQUATION_VERSION,
        "status": "READY",
        "direction": "a" if signal > 0 else "b" if signal < 0 else "neutral",
        "magnitude": round(abs(signal), 6),
        "reliability": round(reliability, 6),
        "applicability": 1.0,
        "family_signal": round(signal, 6),
        "components": {
            "surface_baseline": round(baseline, 6),
            "selected_specific_context": selected_context,
            "specific_context_signal": (
                None if context_signal is None else round(context_signal, 6)
            ),
            "specific_context_adjustment": round(context_adjustment, 6),
            "transition_signal": transition_signal,
            "transition_adjustment": round(transition_adjustment, 6),
        },
        "governance": {
            "overlapping_components_are_not_summed": True,
            "specific_context_modifies_surface_baseline": True,
            "small_samples_are_shrunk": True,
            "service_only_narrative_prohibited": True,
            "condition_performance_extension_pending": True,
        },
        "candidate_parameters": asdict(cfg),
        "market_used": False,
        "production_effect": False,
    }


def evaluate_surface_conditions_v2(
    pair: dict[str, Any], *, config: SurfaceEquationConfig | None = None,
) -> dict[str, Any]:
    """Keep observed transition as an alert, never as an automatic vote."""
    base = config or SurfaceEquationConfig()
    guarded = SurfaceEquationConfig(
        prior_matches_surface=base.prior_matches_surface,
        prior_matches_specific_context=base.prior_matches_specific_context,
        contextual_max_adjustment=base.contextual_max_adjustment,
        transition_max_adjustment=0.0,
    )
    result = evaluate_surface_conditions(pair, config=guarded)
    result["equation_version"] = EQUATION_VERSION_V2
    governance = dict(result.get("governance", {}))
    governance.update({
        "transition_is_diagnostic_only": True,
        "transition_automatic_vote_prohibited": True,
    })
    result["governance"] = governance
    return result


def evaluate_surface_conditions_v3(
    pair: dict[str, Any], *, config: SurfaceEquationConfig | None = None,
) -> dict[str, Any]:
    """Isolate the shrunk surface baseline; all other context is diagnostic."""
    base = config or SurfaceEquationConfig()
    baseline_only = SurfaceEquationConfig(
        prior_matches_surface=base.prior_matches_surface,
        prior_matches_specific_context=base.prior_matches_specific_context,
        contextual_max_adjustment=0.0,
        transition_max_adjustment=0.0,
    )
    result = evaluate_surface_conditions(pair, config=baseline_only)
    result["equation_version"] = EQUATION_VERSION_V3
    governance = dict(result.get("governance", {}))
    governance.update({
        "specific_context_is_diagnostic_only": True,
        "specific_context_automatic_vote_prohibited": True,
        "transition_is_diagnostic_only": True,
        "transition_automatic_vote_prohibited": True,
    })
    result["governance"] = governance
    return result
