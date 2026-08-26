"""Pricing residual experimental com o mercado de-vig como baseline.

O indice de evidencia continua a nao ser uma probabilidade. Este modulo usa
apenas a sua direcao e forca normalizada para aplicar um desvio pequeno,
limitado e auditavel no espaco log-odds da probabilidade de mercado.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping

try:
    from .config import (
        PRICING_FULL_QUALITY_FACTORS,
        PRICING_FULL_QUALITY_MASS,
        PRICING_MAX_LOGIT_SHIFT,
        PRICING_MIN_EDGE_PCT,
        PRICING_MIN_FACTORS,
        PRICING_MIN_QUALITY,
    )
except ImportError:  # pragma: no cover - compatibilidade com imports diretos
    from config import (
        PRICING_FULL_QUALITY_FACTORS,
        PRICING_FULL_QUALITY_MASS,
        PRICING_MAX_LOGIT_SHIFT,
        PRICING_MIN_EDGE_PCT,
        PRICING_MIN_FACTORS,
        PRICING_MIN_QUALITY,
    )


MODEL_VERSION = "market-residual-v0.1"
VALIDATION_LABEL = "EXPERIMENTAL — EM VALIDAÇÃO"
DISCLAIMER = (
    "Estimativa experimental em desenvolvimento. Ainda não validada fora da "
    "amostra em dimensão suficiente. O expected edge é uma estimativa do "
    "modelo e não uma recomendação de aposta."
)
METHOD = (
    "logit(P_sharp) = logit(P_market_de_vig) + "
    "max_logit_shift × signed_strength × quality"
)


@dataclass(frozen=True)
class PricingParameters:
    """Configuracao versionada usada para produzir uma estimativa."""

    max_logit_shift: float = PRICING_MAX_LOGIT_SHIFT
    minimum_edge_pct: float = PRICING_MIN_EDGE_PCT
    minimum_factors: int = PRICING_MIN_FACTORS
    minimum_quality: float = PRICING_MIN_QUALITY
    full_quality_factors: int = PRICING_FULL_QUALITY_FACTORS
    full_quality_mass: float = PRICING_FULL_QUALITY_MASS


def _configuration_fingerprint(parameters: PricingParameters) -> str:
    material = {
        "model_version": MODEL_VERSION,
        "parameters": asdict(parameters),
        "intensity_quality": {"0": 0.0, "1": 0.50, "2": 0.75, "3": 1.0},
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def de_vig_market_probabilities(odd_a: float, odd_b: float) -> tuple[float, float, float]:
    """Devolve probabilidades normalizadas A/B e overround (todos 0..1)."""
    odd_a = float(odd_a)
    odd_b = float(odd_b)
    if not math.isfinite(odd_a) or not math.isfinite(odd_b) or odd_a <= 1 or odd_b <= 1:
        raise ValueError("São necessárias duas odds Moneyline decimais válidas (>1).")
    raw_a, raw_b = 1.0 / odd_a, 1.0 / odd_b
    total = raw_a + raw_b
    return raw_a / total, raw_b / total, total - 1.0


def apply_logit_residual(market_probability: float, residual: float) -> float:
    """Aplica um residual em log-odds sem confundir score com probabilidade."""
    probability = float(market_probability)
    if not 0 < probability < 1:
        raise ValueError("A probabilidade de mercado tem de estar entre 0 e 1.")
    logit = math.log(probability / (1.0 - probability))
    shifted = logit + float(residual)
    return 1.0 / (1.0 + math.exp(-shifted))


def calculate_expected_edge(sharp_probability: float, market_odd: float) -> float:
    """Expected edge decimal: P_sharp × odd de mercado - 1."""
    return float(sharp_probability) * float(market_odd) - 1.0


def _coerce_odd(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value > 1 else None


def _extract_two_way_odds(payload: Mapping[str, Any]) -> tuple[float, float] | None:
    odds = payload.get("market_odds_decimal")
    if not isinstance(odds, Mapping):
        return None
    name_a = str(payload.get("player_a") or "")
    name_b = str(payload.get("player_b") or "")

    def find(side: str, name: str) -> float | None:
        direct = _coerce_odd(odds.get(f"player_{side}"))
        if direct is not None:
            return direct
        for key, value in odds.items():
            if str(key).casefold() == name.casefold():
                found = _coerce_odd(value)
                if found is not None:
                    return found
        surname = name.split()[-1].casefold() if name else ""
        if surname:
            for key, value in odds.items():
                if surname in str(key).casefold():
                    found = _coerce_odd(value)
                    if found is not None:
                        return found
        return None

    odd_a, odd_b = find("a", name_a), find("b", name_b)
    if odd_a is not None and odd_b is not None:
        return odd_a, odd_b
    numeric = [_coerce_odd(value) for value in odds.values()]
    numeric = [value for value in numeric if value is not None]
    if len(numeric) == 2:
        return numeric[0], numeric[1]
    return None


def _evidence_values(divergence: Mapping[str, Any] | None) -> tuple[float, int, int, float]:
    if not isinstance(divergence, Mapping):
        return 50.0, 0, 0, 0.0
    nested = divergence.get("indice_evidencia")
    raw_index = divergence.get("indice_evidencia_a")
    if raw_index is None and isinstance(nested, Mapping):
        raw_index = nested.get("a")
    try:
        index_a = min(100.0, max(0.0, float(raw_index)))
    except (TypeError, ValueError):
        index_a = 50.0
    try:
        factor_count = max(0, int(divergence.get("n_fatores") or 0))
    except (TypeError, ValueError):
        factor_count = 0
    try:
        intensity = min(3, max(0, int(divergence.get("intensidade_nivel") or 0)))
    except (TypeError, ValueError):
        intensity = 0
    statuses = divergence.get("fatores_status")
    effective_mass = 0.0
    counted = 0
    if isinstance(statuses, Mapping):
        for status in statuses.values():
            if not isinstance(status, Mapping):
                continue
            try:
                weight = max(0.0, float(status.get("peso_efetivo") or 0.0))
            except (TypeError, ValueError):
                continue
            if weight > 0:
                effective_mass += weight
                counted += 1
    if factor_count == 0:
        factor_count = counted
    return index_a, factor_count, intensity, effective_mass


def _has_serious_data_failure(payload: Mapping[str, Any]) -> bool:
    quality = payload.get("data_quality")
    if not isinstance(quality, Mapping):
        return False
    if any(bool(quality.get(key)) for key in ("serious_failure", "fatal", "invalid")):
        return True
    if str(quality.get("status") or "").casefold() in {"error", "failed", "invalid"}:
        return True
    issues = quality.get("issues")
    if isinstance(issues, list):
        for issue in issues:
            if not isinstance(issue, Mapping):
                continue
            severity = str(issue.get("severity") or "").casefold()
            if severity in {"error", "critical", "fatal"} or bool(issue.get("blocking")):
                return True
    return False


def _unavailable(parameters: PricingParameters, reason: str) -> dict[str, Any]:
    return {
        "available": False,
        "model_version": MODEL_VERSION,
        "configuration_fingerprint": _configuration_fingerprint(parameters),
        "parameters": asdict(parameters),
        "status": "unavailable",
        "validation_status": VALIDATION_LABEL,
        "method": METHOD,
        "reason": reason,
        "candidate": False,
        "candidate_side": None,
        "candidate_threshold_pct": parameters.minimum_edge_pct,
        "disclaimer": DISCLAIMER,
    }


def estimate_market_residual_pricing(
    payload: Mapping[str, Any],
    divergence: Mapping[str, Any] | None,
    *,
    parameters: PricingParameters | None = None,
) -> dict[str, Any]:
    """Estima fair odds/edge a partir do mercado e de um residual limitado.

    O resultado e sempre coerente a duas vias: calcula-se apenas P(A) e usa-se
    P(B)=1-P(A). Sem odds validas, nao se fabricam probabilidades.
    """
    parameters = parameters or PricingParameters()
    observed = _extract_two_way_odds(payload)
    if observed is None:
        return _unavailable(parameters, "missing_or_invalid_two_way_moneyline")
    odd_a, odd_b = observed
    try:
        market_a, market_b, overround = de_vig_market_probabilities(odd_a, odd_b)
    except ValueError:
        return _unavailable(parameters, "missing_or_invalid_two_way_moneyline")

    index_a, factor_count, intensity, effective_mass = _evidence_values(divergence)
    signed_strength = min(1.0, max(-1.0, (index_a - 50.0) / 50.0))
    factor_quality = min(1.0, factor_count / max(1, parameters.full_quality_factors))
    mass_quality = (
        min(1.0, effective_mass / parameters.full_quality_mass)
        if effective_mass > 0 and parameters.full_quality_mass > 0
        else factor_quality
    )
    # Nivel 0 significa que o proprio motor considera o sinal inconclusivo;
    # nesse caso nao ha residual utilizavel e o mercado permanece inalterado.
    intensity_quality = (0.0, 0.50, 0.75, 1.0)[intensity]
    quality = min(factor_quality, mass_quality, intensity_quality)
    residual = parameters.max_logit_shift * signed_strength * quality

    sharp_a = apply_logit_residual(market_a, residual)
    sharp_b = 1.0 - sharp_a
    adjustment_a = (sharp_a - market_a) * 100.0
    adjustment_b = -adjustment_a
    fair_a, fair_b = 1.0 / sharp_a, 1.0 / sharp_b
    edge_a = calculate_expected_edge(sharp_a, odd_a)
    edge_b = calculate_expected_edge(sharp_b, odd_b)

    serious_failure = _has_serious_data_failure(payload)
    quality_gate_passed = (
        factor_count >= parameters.minimum_factors
        and quality >= parameters.minimum_quality
        and not serious_failure
    )
    mathematical_side, mathematical_edge = max(
        (("a", edge_a), ("b", edge_b)), key=lambda item: item[1]
    )
    reaches_threshold = mathematical_edge * 100.0 >= parameters.minimum_edge_pct
    candidate_side = mathematical_side if reaches_threshold and quality_gate_passed else None
    if candidate_side:
        candidate_status = "experimental_edge"
        visible_label = f"EDGE EXPERIMENTAL +{mathematical_edge * 100.0:.1f}%"
    elif reaches_threshold:
        candidate_status = "edge_not_promoted_insufficient_evidence"
        visible_label = "EDGE NÃO PROMOVIDO — EVIDÊNCIA INSUFICIENTE"
    else:
        candidate_status = "below_edge_threshold"
        visible_label = f"SEM EDGE EXPERIMENTAL ≥ +{parameters.minimum_edge_pct:.1f}%"

    players = {
        "a": {
            "market_probability_pct": round(market_a * 100.0, 2),
            "sharp_estimate_pct": round(sharp_a * 100.0, 2),
            "adjustment_pp": round(adjustment_a, 2),
            "fair_odd": round(fair_a, 3),
            "market_odd": round(odd_a, 3),
            "expected_edge_pct": round(edge_a * 100.0, 2),
        },
        "b": {
            "market_probability_pct": round(market_b * 100.0, 2),
            "sharp_estimate_pct": round(sharp_b * 100.0, 2),
            "adjustment_pp": round(adjustment_b, 2),
            "fair_odd": round(fair_b, 3),
            "market_odd": round(odd_b, 3),
            "expected_edge_pct": round(edge_b * 100.0, 2),
        },
    }
    return {
        "available": True,
        "model_version": MODEL_VERSION,
        "configuration_fingerprint": _configuration_fingerprint(parameters),
        "parameters": asdict(parameters),
        "status": "experimental",
        "validation_status": VALIDATION_LABEL,
        "method": METHOD,
        "market_overround_pct": round(overround * 100.0, 3),
        "signed_strength": round(signed_strength, 6),
        "residual_logit": round(residual, 8),
        "quality_score": round(quality, 6),
        "quality_gate_passed": quality_gate_passed,
        "evidence_quality": {
            "factor_count": factor_count,
            "effective_mass": round(effective_mass, 3),
            "factor_quality": round(factor_quality, 6),
            "mass_quality": round(mass_quality, 6),
            "intensity_quality": intensity_quality,
            "serious_data_quality_failure": serious_failure,
        },
        "players": players,
        # Campos planos para o ledger de validacao/OOS.
        "market_probability_a": market_a,
        "market_probability_b": market_b,
        "sharp_estimate_a": sharp_a,
        "sharp_estimate_b": sharp_b,
        "adjustment_pp_a": adjustment_a,
        "adjustment_pp_b": adjustment_b,
        "fair_odd_a": fair_a,
        "fair_odd_b": fair_b,
        "market_odd_a": odd_a,
        "market_odd_b": odd_b,
        "expected_edge_a": edge_a,
        "expected_edge_b": edge_b,
        "mathematical_edge_side": mathematical_side if reaches_threshold else None,
        "candidate": bool(candidate_side),
        "candidate_side": candidate_side,
        "candidate_player": payload.get(f"player_{candidate_side}") if candidate_side else None,
        "candidate_status": candidate_status,
        "candidate_label": visible_label,
        "candidate_threshold_pct": parameters.minimum_edge_pct,
        "disclaimer": DISCLAIMER,
    }
