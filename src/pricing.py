"""Pricing Fenzobot independente do mercado, calibrado em histórico liquidado.

O índice de evidência não é usado diretamente como probabilidade. Uma curva
logística estimada apenas com snapshots pré-jogo e resultados liquidados
converte força × qualidade numa probabilidade estrutural. As odds de mercado
entram depois, exclusivamente para calcular edge e detetar extrapolações.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping

try:
    from . import market_integrity
except ImportError:  # pragma: no cover - compatibilidade com imports diretos
    import market_integrity

try:
    from .config import (
        PRICING_FULL_QUALITY_FACTORS,
        PRICING_FULL_QUALITY_MASS,
        PRICING_MIN_EDGE_PCT,
        PRICING_MIN_FACTORS,
        PRICING_MIN_QUALITY,
    )
except ImportError:  # pragma: no cover - compatibilidade com imports diretos
    from config import (
        PRICING_FULL_QUALITY_FACTORS,
        PRICING_FULL_QUALITY_MASS,
        PRICING_MIN_EDGE_PCT,
        PRICING_MIN_FACTORS,
        PRICING_MIN_QUALITY,
    )


MODEL_VERSION = "factor-calibrated-v2.0"
CALIBRATION_VERSION = "factor-probability-calibration-v2"
CALIBRATION_STATUS = "HISTORICALLY_CALIBRATED_SHADOW"
VALIDATION_LABEL = "EXPERIMENTAL — EM VALIDAÇÃO"
DISCLAIMER = (
    "Estimativa experimental em desenvolvimento. Ainda não validada fora da "
    "amostra em dimensão suficiente. O expected edge é uma estimativa do "
    "modelo e não uma recomendação de aposta."
)
METHOD = (
    "P_fenzobot = logistic(beta_circuito × força_assinada_do_indice × "
    "qualidade_da_evidencia); edge = P_fenzobot × odd_mercado - 1. "
    "O mercado não participa na fair probability."
)


@dataclass(frozen=True)
class PricingParameters:
    """Configuracao versionada usada para produzir uma estimativa."""

    # Mantidos para compatibilidade com chamadas históricas; já não participam
    # no cálculo da probabilidade própria do FenzoBot.
    atp_maximum_adjustment_pp: float = 0.0
    wta_maximum_adjustment_pp: float = 0.0
    challenger_maximum_adjustment_pp: float = 0.0
    minimum_edge_pct: float = PRICING_MIN_EDGE_PCT
    minimum_factors: int = PRICING_MIN_FACTORS
    minimum_quality: float = PRICING_MIN_QUALITY
    full_quality_factors: int = PRICING_FULL_QUALITY_FACTORS
    full_quality_mass: float = PRICING_FULL_QUALITY_MASS
    # MLE e IC 95% calculados em 1 078 partidas canónicas liquidadas. O limite
    # inferior produz o edge conservador; o central produz a fair odd visível.
    atp_beta: float = 1.00911
    atp_beta_low: float = 0.63706
    atp_beta_high: float = 1.38116
    wta_beta: float = 1.24198
    wta_beta_low: float = 0.85680
    wta_beta_high: float = 1.62715
    challenger_beta: float = 0.80537
    challenger_beta_low: float = 0.0
    challenger_beta_high: float = 1.67285
    # Percentil 95 da diferença histórica |P_fenzobot - P_mercado sem margem|.
    atp_anomaly_gap_pp: float = 27.93
    wta_anomaly_gap_pp: float = 32.62
    challenger_anomaly_gap_pp: float = 37.71


def _configuration_fingerprint(parameters: PricingParameters) -> str:
    material = {
        "model_version": MODEL_VERSION,
        "parameters": asdict(parameters),
        "intensity_quality": {"0": 0.0, "1": 0.50, "2": 0.75, "3": 1.0},
        "probability_source": "settled_pre_match_factor_snapshots",
        "market_role": "edge_and_anomaly_check_only",
        "calibration_version": CALIBRATION_VERSION,
        "calibration_status": CALIBRATION_STATUS,
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


def calibrated_factor_probability(residual_predictor: float, beta: float) -> float:
    """Converte evidência assinada em probabilidade sem consultar o mercado."""
    z = float(residual_predictor) * max(0.0, float(beta))
    # Os valores atuais nunca chegam perto destes limites, mas o clamp evita
    # overflow e preserva a coerência matemática em payloads corrompidos.
    z = min(20.0, max(-20.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def evidence_probability(index_a: float, quality: float, *, maximum_probability: float = 0.85) -> float:
    """Converte evidencia direcional numa probabilidade experimental independente.

    O indice nao e tratado linearmente como probabilidade. A curva quadratica
    mantem sinais moderados perto de 50%, limita o extremo a 85% com evidencia
    completa e contrai a estimativa para 50% quando a qualidade e incompleta.
    Nenhum preco de mercado participa neste calculo.
    """
    index = min(100.0, max(0.0, float(index_a)))
    quality = min(1.0, max(0.0, float(quality)))
    ceiling = min(0.99, max(0.5, float(maximum_probability)))
    signed_strength = (index - 50.0) / 50.0
    directional_distance = math.copysign(abs(signed_strength) ** 2, signed_strength)
    probability = 0.5 + directional_distance * (ceiling - 0.5) * quality
    return min(0.99, max(0.01, probability))


def market_prior_probability(
    market_probability: float,
    index_a: float,
    quality: float,
    *,
    maximum_adjustment_pp: float,
) -> tuple[float, float]:
    """Aplica um residual limitado ao prior de mercado sem margem.

    Devolve ``(probabilidade, ajuste_decimal)``. Um indice extremo só usa o
    limite completo quando a qualidade também é completa; diferenças menores
    ou amostras frágeis encolhem proporcionalmente. Isto impede que consenso
    direcional seja confundido com 85% de probabilidade absoluta.
    """
    prior = min(0.99, max(0.01, float(market_probability)))
    index = min(100.0, max(0.0, float(index_a)))
    quality = min(1.0, max(0.0, float(quality)))
    signed_strength = (index - 50.0) / 50.0
    limit = max(0.0, float(maximum_adjustment_pp)) / 100.0
    adjustment = signed_strength * quality * limit
    probability = min(0.99, max(0.01, prior + adjustment))
    return probability, probability - prior


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


def _has_identity_resolution_warning(payload: Mapping[str, Any]) -> bool:
    quality = payload.get("data_quality")
    if not isinstance(quality, Mapping):
        return False
    issues = quality.get("issues")
    return isinstance(issues, list) and any(
        isinstance(issue, Mapping) and issue.get("type") == "name_resolution"
        for issue in issues
    )


def _coverage_values(divergence: Mapping[str, Any] | None) -> tuple[float, float, bool]:
    """Cobertura, fiabilidade e elegibilidade; defaults preservam payloads antigos."""
    if not isinstance(divergence, Mapping):
        return 1.0, 1.0, True
    coverage = divergence.get("evidence_coverage")
    if not isinstance(coverage, Mapping):
        return 1.0, 1.0, True
    try:
        coverage_quality = min(1.0, max(0.0, float(coverage.get("coverage_quality", 1.0))))
    except (TypeError, ValueError):
        coverage_quality = 0.0
    try:
        source_reliability = min(1.0, max(0.0, float(coverage.get("source_reliability", 1.0))))
    except (TypeError, ValueError):
        source_reliability = 0.0
    return coverage_quality, source_reliability, bool(coverage.get("pricing_eligible", True))


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
        "candidate_threshold_pct": 0.0,
        "disclaimer": DISCLAIMER,
    }


def estimate_market_residual_pricing(
    payload: Mapping[str, Any],
    divergence: Mapping[str, Any] | None,
    *,
    parameters: PricingParameters | None = None,
) -> dict[str, Any]:
    """Estima fair odds próprias e só depois compara com o mercado observado."""
    parameters = parameters or PricingParameters()
    assessment = payload.get("report_assessment")
    if isinstance(assessment, Mapping) and assessment.get("report_null"):
        return _unavailable(parameters, "report_null_insufficient_data")
    operational_quote = market_integrity.is_operational_pricing_payload(payload)
    experimental_challenger_quote = bool(
        payload.get("experimental_challenger_pricing_eligible") is True
        and market_integrity.is_experimental_challenger_pricing_provenance(
            payload.get("odds_provenance")
        )
    )
    if not operational_quote and not experimental_challenger_quote:
        return _unavailable(parameters, "operational_market_quote_ineligible")
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
    internal_quality = min(factor_quality, mass_quality, intensity_quality)
    coverage_quality, source_reliability, coverage_gate_passed = _coverage_values(divergence)
    identity_warning = _has_identity_resolution_warning(payload)
    if identity_warning:
        source_reliability = min(source_reliability, 0.5)
    source_gate_passed = not identity_warning and source_reliability >= 0.75
    quality = internal_quality * coverage_quality * source_reliability
    tier = str(payload.get("tier") or "").casefold()
    tour = str(payload.get("tour") or "").casefold()
    if experimental_challenger_quote or "challenger" in tier:
        calibration_segment = "challenger"
        beta = parameters.challenger_beta
        beta_low = parameters.challenger_beta_low
        beta_high = parameters.challenger_beta_high
        anomaly_gap_pp = parameters.challenger_anomaly_gap_pp
    elif tour == "wta":
        calibration_segment = "wta"
        beta = parameters.wta_beta
        beta_low = parameters.wta_beta_low
        beta_high = parameters.wta_beta_high
        anomaly_gap_pp = parameters.wta_anomaly_gap_pp
    else:
        calibration_segment = "atp"
        beta = parameters.atp_beta
        beta_low = parameters.atp_beta_low
        beta_high = parameters.atp_beta_high
        anomaly_gap_pp = parameters.atp_anomaly_gap_pp
    residual_predictor = signed_strength * quality
    sharp_a = calibrated_factor_probability(residual_predictor, beta)
    interval_a = sorted((
        calibrated_factor_probability(residual_predictor, beta_low),
        calibrated_factor_probability(residual_predictor, beta_high),
    ))
    sharp_a_low, sharp_a_high = interval_a
    sharp_b = 1.0 - sharp_a
    sharp_b_low, sharp_b_high = 1.0 - sharp_a_high, 1.0 - sharp_a_low
    adjustment_a = (sharp_a - market_a) * 100.0
    adjustment_b = -adjustment_a
    fair_a, fair_b = 1.0 / sharp_a, 1.0 / sharp_b
    edge_a = calculate_expected_edge(sharp_a, odd_a)
    edge_b = calculate_expected_edge(sharp_b, odd_b)
    conservative_edge_a = calculate_expected_edge(sharp_a_low, odd_a)
    conservative_edge_b = calculate_expected_edge(sharp_b_low, odd_b)
    anomaly_gap_observed_pp = abs(adjustment_a)
    anomaly_gate_passed = anomaly_gap_observed_pp <= anomaly_gap_pp

    serious_failure = _has_serious_data_failure(payload)
    quality_gate_passed = (
        factor_count >= parameters.minimum_factors
        and quality >= parameters.minimum_quality
        and not serious_failure
        and coverage_gate_passed
        and source_gate_passed
    )
    mathematical_side, mathematical_edge = max(
        (("a", edge_a), ("b", edge_b)), key=lambda item: item[1]
    )
    # O lado operacional e sempre o lado escolhido pelo indice Fenzobot.
    # O limiar historico de 5% deixa de decidir PAPER: qualquer edge > 0 e
    # elegivel depois do contrato de validade pre-live. O gate abaixo fica
    # apenas como diagnostico de qualidade do pricing.
    fenzobot_side = "a" if index_a > 50 else "b" if index_a < 50 else None
    fenzobot_edge = edge_a if fenzobot_side == "a" else edge_b if fenzobot_side == "b" else None
    conservative_edge = (
        conservative_edge_a if fenzobot_side == "a"
        else conservative_edge_b if fenzobot_side == "b" else None
    )
    candidate_side = (
        fenzobot_side
        if fenzobot_edge is not None
        and fenzobot_edge > 0
        and conservative_edge is not None
        and conservative_edge > 0
        and quality_gate_passed
        and anomaly_gate_passed
        else None
    )
    if candidate_side:
        candidate_status = "historically_supported_shadow_edge"
        visible_label = (
            f"EDGE SHADOW +{fenzobot_edge * 100.0:.1f}% · "
            f"conservador +{conservative_edge * 100.0:.1f}%"
        )
    elif fenzobot_edge is not None and fenzobot_edge > 0 and not anomaly_gate_passed:
        candidate_status = "market_discrepancy_out_of_calibration"
        visible_label = "DISCREPÂNCIA FORA DA CALIBRAÇÃO — REVISÃO OBRIGATÓRIA"
    elif fenzobot_edge is not None and fenzobot_edge > 0:
        candidate_status = "central_edge_not_confirmed"
        visible_label = "EDGE CENTRAL NÃO CONFIRMADO PELO INTERVALO CONSERVADOR"
    else:
        candidate_status = "non_positive_fenzobot_edge"
        visible_label = "SEM EDGE POSITIVO NO LADO FENZOBOT"

    players = {
        "a": {
            "market_probability_pct": round(market_a * 100.0, 2),
            "sharp_estimate_pct": round(sharp_a * 100.0, 2),
            "sharp_estimate_low_pct": round(sharp_a_low * 100.0, 2),
            "sharp_estimate_high_pct": round(sharp_a_high * 100.0, 2),
            "adjustment_pp": round(adjustment_a, 2),
            "fair_odd": round(fair_a, 3),
            "fair_odd_low": round(1.0 / sharp_a_high, 3),
            "fair_odd_high": round(1.0 / sharp_a_low, 3),
            "market_odd": round(odd_a, 3),
            "expected_edge_pct": round(edge_a * 100.0, 2),
            "conservative_edge_pct": round(conservative_edge_a * 100.0, 2),
        },
        "b": {
            "market_probability_pct": round(market_b * 100.0, 2),
            "sharp_estimate_pct": round(sharp_b * 100.0, 2),
            "sharp_estimate_low_pct": round(sharp_b_low * 100.0, 2),
            "sharp_estimate_high_pct": round(sharp_b_high * 100.0, 2),
            "adjustment_pp": round(adjustment_b, 2),
            "fair_odd": round(fair_b, 3),
            "fair_odd_low": round(1.0 / sharp_b_high, 3),
            "fair_odd_high": round(1.0 / sharp_b_low, 3),
            "market_odd": round(odd_b, 3),
            "expected_edge_pct": round(edge_b * 100.0, 2),
            "conservative_edge_pct": round(conservative_edge_b * 100.0, 2),
        },
    }
    return {
        "available": True,
        "model_version": MODEL_VERSION,
        "configuration_fingerprint": _configuration_fingerprint(parameters),
        "odds_source_contract_version": payload.get("odds_source_contract_version"),
        "odds_source_contract_fingerprint": payload.get("odds_source_contract_fingerprint"),
        "parameters": asdict(parameters),
        "status": "experimental",
        "market_quote_mode": (
            "challenger_observed_feed_experimental"
            if experimental_challenger_quote else "operational"
        ),
        "validation_status": VALIDATION_LABEL,
        "method": METHOD,
        "market_overround_pct": round(overround * 100.0, 3),
        "signed_strength": round(signed_strength, 6),
        "residual_logit": round(beta * residual_predictor, 6),
        "bounded_adjustment_pp": round(adjustment_a, 6),
        "maximum_adjustment_pp": None,
        "residual_calibration": {
            "version": CALIBRATION_VERSION,
            "status": CALIBRATION_STATUS,
            "segment": calibration_segment,
            "beta": beta,
            "beta_low": beta_low,
            "beta_high": beta_high,
            "anomaly_gap_pp": anomaly_gap_pp,
        },
        "probability_basis": "independent_factor_logistic_calibration",
        "market_used_in_fair_probability": False,
        "market_comparison": {
            "absolute_gap_pp": round(anomaly_gap_observed_pp, 2),
            "historical_p95_gap_pp": anomaly_gap_pp,
            "within_calibrated_range": anomaly_gate_passed,
        },
        "quality_score": round(quality, 6),
        "quality_gate_passed": quality_gate_passed,
        "evidence_quality": {
            "factor_count": factor_count,
            "effective_mass": round(effective_mass, 3),
            "factor_quality": round(factor_quality, 6),
            "mass_quality": round(mass_quality, 6),
            "intensity_quality": intensity_quality,
            "internal_quality": round(internal_quality, 6),
            "coverage_quality": round(coverage_quality, 6),
            "source_reliability": round(source_reliability, 6),
            "coverage_gate_passed": coverage_gate_passed,
            "source_gate_passed": source_gate_passed,
            "identity_resolution_warning": identity_warning,
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
        "conservative_edge_a": conservative_edge_a,
        "conservative_edge_b": conservative_edge_b,
        "mathematical_edge_side": mathematical_side,
        "candidate": bool(candidate_side),
        "candidate_side": candidate_side,
        "candidate_player": payload.get(f"player_{candidate_side}") if candidate_side else None,
        "candidate_status": candidate_status,
        "candidate_label": visible_label,
        "candidate_threshold_pct": 0.0,
        "disclaimer": DISCLAIMER,
    }
