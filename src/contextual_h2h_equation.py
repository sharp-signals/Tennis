"""Bounded, market-free candidate equation for the matchup/H2H family."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


SCHEMA_VERSION = 1
EQUATION_VERSION = "contextual-h2h-global-shrunk-v1"


@dataclass(frozen=True)
class ContextualH2HConfig:
    prior_matches: float = 2.0


def _band(matches: int) -> str:
    if matches <= 0:
        return "none"
    if matches == 1:
        return "single_low"
    if matches <= 3:
        return "repeated_moderate"
    return "repeated_material_but_bounded"


def evaluate_contextual_h2h(
    factual_h2h: dict[str, Any],
    *,
    config: ContextualH2HConfig | None = None,
) -> dict[str, Any]:
    """Return one shrunk family signal; context remains diagnostic only."""
    cfg = config or ContextualH2HConfig()
    common = {
        "schema_version": SCHEMA_VERSION,
        "equation_version": EQUATION_VERSION,
        "candidate_parameters": asdict(cfg),
        "market_used": False,
        "production_effect": False,
        "probability_fitted": False,
        "fair_odd_fitted": False,
    }
    status = factual_h2h.get("status")
    if status == "OBSERVED_NONE":
        return {
            **common,
            "status": "READY_NEUTRAL",
            "data_state": "OBSERVED_NONE",
            "direction": "neutral",
            "magnitude": 0.0,
            "reliability": 1.0,
            "applicability": 0.0,
            "family_signal": 0.0,
            "evidence_band": "none",
            "reason_codes": ["NO_PRIOR_H2H_CONFIRMED"],
        }
    if status != "AVAILABLE":
        return {
            **common,
            "status": "UNAVAILABLE",
            "data_state": status or "UNKNOWN",
            "direction": None,
            "magnitude": None,
            "reliability": 0.0,
            "applicability": 0.0,
            "family_signal": None,
            "evidence_band": "none",
            "reason_codes": [f"H2H_{status or 'UNKNOWN'}"],
        }

    eligible = [
        match for match in factual_h2h.get("matches", [])
        if match.get("competitively_eligible") is True
    ]
    a_wins = sum(match.get("winner_side") == "a" for match in eligible)
    b_wins = sum(match.get("winner_side") == "b" for match in eligible)
    sample = a_wins + b_wins
    if sample <= 0:
        return {
            **common,
            "status": "NO_COMPETITIVE_SAMPLE",
            "data_state": "OBSERVED_NONSTANDARD_ONLY",
            "direction": None,
            "magnitude": None,
            "reliability": 0.0,
            "applicability": 0.0,
            "family_signal": None,
            "evidence_band": "none",
            "reason_codes": ["NO_COMPETITIVELY_ELIGIBLE_H2H"],
        }

    signal = (a_wins - b_wins) / (sample + cfg.prior_matches)
    reliability = sample / (sample + cfg.prior_matches)
    same_surface = sum(match.get("same_surface") is True for match in eligible)
    same_context = sum(
        match.get("same_competition_context") is True for match in eligible
    )
    recent = sum(
        isinstance(match.get("days_before_cutoff"), int)
        and match["days_before_cutoff"] <= 730
        for match in eligible
    )
    return {
        **common,
        "status": "READY",
        "data_state": "OBSERVED",
        "direction": "a" if signal > 0 else "b" if signal < 0 else "neutral",
        "magnitude": round(abs(signal), 6),
        "reliability": round(reliability, 6),
        "applicability": round(reliability, 6),
        "family_signal": round(signal, 6),
        "evidence_band": _band(sample),
        "components": {
            "eligible_matches": sample,
            "a_wins": a_wins,
            "b_wins": b_wins,
            "same_surface_matches": same_surface,
            "same_competition_context_matches": same_context,
            "recent_730d_matches": recent,
        },
        "governance": {
            "global_and_context_h2h_are_not_summed": True,
            "surface_and_recency_are_diagnostic_only": True,
            "single_match_is_low_evidence": sample == 1,
            "family_must_remain_bounded_in_combination": True,
            "family_cannot_lead_probability_alone": True,
        },
        "reason_codes": [],
    }
