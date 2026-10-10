"""Contrato unico da decisao pre-live do Fenzobot.

Este modulo nao calcula o indice nem inventa mercados. Recebe o indice do
Fenzobot e o pricing existente, valida a cobertura factual e produz o estado
que deve ser consumido pelo HTML, Telegram e carteira PAPER.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

try:
    from .config import (
        EXPERIMENTAL_REPORT_ONLY_TIERS,
        CHALLENGER_EXPERIMENTAL_MIN_DATA_COVERAGE,
        PAPER_MIN_WEIGHTED_COVERAGE,
        PRICING_MIN_QUALITY,
    )
except ImportError:  # pragma: no cover
    from config import (CHALLENGER_EXPERIMENTAL_MIN_DATA_COVERAGE,
                        EXPERIMENTAL_REPORT_ONLY_TIERS, PAPER_MIN_WEIGHTED_COVERAGE,
                        PRICING_MIN_QUALITY)


EDGE_POSITIVE = "EDGE_POSITIVE"
EDGE_POSITIVE_COVERAGE_INSUFFICIENT = "EDGE_POSITIVE_COVERAGE_INSUFFICIENT"
EDGE_NEGATIVE = "EDGE_NEGATIVE"
EDGE_ZERO = "EDGE_ZERO"
REPORT_NULL = "REPORT_NULL"
PRICING_UNAVAILABLE = "PRICING_UNAVAILABLE"
EXPERIMENTAL_FACTUAL_PARTIAL = "EXPERIMENTAL_FACTUAL_PARTIAL"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _positive_number(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0


def _valid_rank(payload: Mapping[str, Any], side: str) -> bool:
    rank = _mapping(payload.get(f"ranking_{side}")).get("rank")
    return _positive_number(rank)


def _is_experimental_tier(payload: Mapping[str, Any]) -> bool:
    """Challenger 125 tem relatório exploratório, não uma decisão relaxada."""
    coverage = _mapping(payload.get("tournament_coverage"))
    return (
        coverage.get("mode") == "EXPERIMENTAL_REPORT_ONLY"
        or str(payload.get("tier") or "").strip() in EXPERIMENTAL_REPORT_ONLY_TIERS
    )


def _factor_available(
    divergence: Mapping[str, Any] | None, *factor_keys: str,
) -> bool:
    statuses = _mapping(_mapping(divergence).get("fatores_status"))
    return any(bool(_mapping(statuses.get(key)).get("disponivel")) for key in factor_keys)


def _service_block_available(
    payload: Mapping[str, Any], divergence: Mapping[str, Any] | None = None,
) -> bool:
    """Exige pelo menos uma comparacao bilateral sustentada por amostra."""
    if _mapping(payload.get("competition_evidence_policy")).get("active") is True:
        return _factor_available(
            divergence, "servico_carreira", "servico_recente"
        )
    for prefix, sample_key, metric_keys in (
        ("pressure_profile", "matches", (
            "first_serve_won_pct", "second_serve_won_pct",
            "break_points_saved_pct", "break_points_converted_pct",
        )),
        ("serve_return_stats", "matches_used", (
            "avg_first_serve_won_pct", "avg_break_points_saved_pct",
            "avg_return_points_won_pct", "avg_break_points_converted_pct",
        )),
    ):
        a = _mapping(payload.get(f"{prefix}_a"))
        b = _mapping(payload.get(f"{prefix}_b"))
        if not (_positive_number(a.get(sample_key)) and _positive_number(b.get(sample_key))):
            continue
        if any(a.get(key) is not None and b.get(key) is not None for key in metric_keys):
            return True
    return False


def _scenario(payload: Mapping[str, Any], side: str, rate: str, count: str) -> bool:
    scenarios = _mapping(_mapping(payload.get(f"rich_stats_{side}")).get("scenarios"))
    return scenarios.get(rate) is not None and _positive_number(scenarios.get(count))


def _action_block_available(
    payload: Mapping[str, Any], divergence: Mapping[str, Any] | None = None,
) -> bool:
    """Detecta se existe ao menos um bloco bilateral que possa gerar acao.

    Com a política competitiva ativa, agregados sem proveniência nunca
    satisfazem este gate. O mapa pode abrir com mercado factual e ao menos
    um fator ponderado elegível; cenários adicionais são filtrados no HTML.
    """
    if _mapping(payload.get("competition_evidence_policy")).get("active") is True:
        market = _mapping(payload.get("market_odds_decimal"))
        return bool(market) and _factor_available(
            divergence,
            "forma_recente", "qualidade_vitorias", "indoor_outdoor",
            "velocidade_piso", "sazonal", "piso", "h2h", "h2h_piso",
            "servico_carreira", "servico_recente",
        )
    if all(
        _scenario(payload, side, "first_set_lose_then_win_pct", "first_set_lose_count")
        for side in ("a", "b")
    ):
        return True
    if all(
        _scenario(payload, side, "deciding_set_win_pct", "deciding_set_count")
        for side in ("a", "b")
    ):
        return True
    for key, sample_key in (
        ("deciding_set_stats", "deciding_set_count"),
        ("game_margin", "matches"),
        ("fatigue_signal", "matches_last_7d"),
    ):
        left = _mapping(payload.get(f"{key}_a"))
        right = _mapping(payload.get(f"{key}_b"))
        if left.get(sample_key) is not None and right.get(sample_key) is not None:
            return True
    return False


def weighted_coverage(divergence: Mapping[str, Any] | None) -> dict[str, Any]:
    statuses = _mapping(_mapping(divergence).get("fatores_status"))
    configured = 0.0
    available = 0.0
    factor_count = 0
    available_count = 0
    for raw in statuses.values():
        status = _mapping(raw)
        try:
            weight = max(0.0, float(status.get("peso_base_configurado") or 0.0))
        except (TypeError, ValueError):
            continue
        if weight <= 0:
            continue
        factor_count += 1
        configured += weight
        if bool(status.get("disponivel")):
            available_count += 1
            available += weight
    ratio = available / configured if configured > 0 else 0.0
    return {
        "weighted_ratio": round(ratio, 6),
        "weighted_pct": round(100.0 * ratio, 1),
        "available_weight": round(available, 3),
        "configured_weight": round(configured, 3),
        "available_factors": available_count,
        "configured_factors": factor_count,
    }


def assess_report(payload: Mapping[str, Any], divergence: Mapping[str, Any] | None) -> dict[str, Any]:
    coverage = weighted_coverage(divergence)
    reasons: list[str] = []
    experimental = _is_experimental_tier(payload)
    essential = {
        "ranking_bilateral": _valid_rank(payload, "a") and _valid_rank(payload, "b"),
        "service_return_bilateral": _service_block_available(payload, divergence),
        "action_map": _action_block_available(payload, divergence),
    }
    if not essential["ranking_bilateral"]:
        reasons.append("ranking ausente para pelo menos um jogador")
    if not essential["service_return_bilateral"]:
        reasons.append("serviço/resposta sem amostra bilateral utilizável")
    if not essential["action_map"]:
        reasons.append("mapa de ações sem informação bilateral utilizável")
    if not divergence:
        reasons.append("índice Fenzobot não calculável")
    quality = _mapping(payload.get("data_quality"))
    serious_quality_failure = any(bool(quality.get(key)) for key in ("serious_failure", "fatal", "invalid"))
    for issue in quality.get("issues") or []:
        issue = _mapping(issue)
        if str(issue.get("severity") or "").casefold() in {"error", "critical", "fatal"} or issue.get("blocking"):
            serious_quality_failure = True
            break
    if serious_quality_failure:
        reasons.append("falha crítica de qualidade dos dados")
    minimum_coverage = (
        CHALLENGER_EXPERIMENTAL_MIN_DATA_COVERAGE if experimental else PRICING_MIN_QUALITY
    )
    if coverage["weighted_ratio"] < minimum_coverage:
        reasons.append(
            f"cobertura ponderada inferior ao mínimo de {minimum_coverage:.0%}"
        )
    # No Challenger 125, estes motivos tornam a cobertura parcial — nunca
    # justificam inventar ranking/edge, mas também não apagam o relatório
    # factual se a identidade e os dados recebidos forem válidos.
    report_null = serious_quality_failure or (bool(reasons) and not experimental)
    partial = experimental and bool(reasons)
    coverage_status = "experimental_parcial" if partial else ("insuficiente" if report_null else (
        "suficiente" if coverage["weighted_ratio"] >= 0.999 else "reduzida"
    ))
    return {
        "report_null": report_null,
        "status": "REPORT_NULL" if report_null else "VALID",
        "reasons": reasons,
        "primary_reason": reasons[0] if reasons else None,
        "coverage": {**coverage, "status": coverage_status},
        "essential_blocks": essential,
        "experimental_partial": partial,
        "partial_reasons": reasons if partial else [],
        "minimum_weighted_coverage": minimum_coverage,
        "criteria_version": "prelive-validity-v3",
    }


def fenzobot_side(payload: Mapping[str, Any], divergence: Mapping[str, Any] | None) -> str | None:
    div = _mapping(divergence)
    try:
        a = float(div.get("indice_evidencia_a"))
        b = float(div.get("indice_evidencia_b"))
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(a) and math.isfinite(b)) or a == b:
        return None
    return "a" if a > b else "b"


def build_decision(
    payload: Mapping[str, Any],
    divergence: Mapping[str, Any] | None,
    pricing: Mapping[str, Any] | None,
    assessment: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    assessment = dict(assessment or assess_report(payload, divergence))
    base = {
        "contract_version": "fenzobot-prelive-v1",
        "coverage": assessment.get("coverage"),
        "report_assessment": assessment,
        "paper_eligible": False,
        "paper_markets": [],
    }
    if assessment.get("report_null"):
        return {**base, "state": REPORT_NULL, "reason": assessment.get("primary_reason")}
    if assessment.get("experimental_partial"):
        return {
            **base,
            "state": EXPERIMENTAL_FACTUAL_PARTIAL,
            "reason": "; ".join(assessment.get("partial_reasons") or ["cobertura parcial"]),
            "experimental_mode": "CHALLENGER_125_FACTUAL_ONLY",
        }

    pricing = _mapping(pricing)
    side = fenzobot_side(payload, divergence)
    if not pricing.get("available"):
        reason = pricing.get("reason") or "edge não calculável para o lado Fenzobot"
        return {**base, "state": PRICING_UNAVAILABLE, "reason": reason}
    if side not in {"a", "b"}:
        # Um empate real 50--50 é uma conclusão válida do modelo, não uma
        # falha de dados. Só índices ausentes, não numéricos ou não finitos
        # permanecem relatório nulo.
        div = _mapping(divergence)
        try:
            index_a = float(div.get("indice_evidencia_a"))
            index_b = float(div.get("indice_evidencia_b"))
        except (TypeError, ValueError):
            index_a = index_b = float("nan")
        if math.isfinite(index_a) and math.isfinite(index_b) and index_a == index_b:
            return {
                **base,
                "state": EDGE_ZERO,
                "reason": "índice Fenzobot equilibrado entre os dois jogadores; sem lado preferido",
                "fenzobot_index": index_a,
                "expected_edge_pct": 0.0,
                "side": None,
                "player": None,
            }
        return {**base, "state": REPORT_NULL, "reason": "lado Fenzobot não calculável"}

    players = _mapping(pricing.get("players"))
    side_data = _mapping(players.get(side))
    other = "b" if side == "a" else "a"
    try:
        edge = float(side_data.get("expected_edge_pct"))
    except (TypeError, ValueError):
        return {**base, "state": PRICING_UNAVAILABLE, "reason": "edge Fenzobot não calculável"}
    try:
        other_edge = float(_mapping(players.get(other)).get("expected_edge_pct"))
    except (TypeError, ValueError):
        other_edge = float("nan")
    if edge > 0 and math.isfinite(other_edge) and other_edge > 0:
        return {
            **base,
            "state": REPORT_NULL,
            "reason": "anomalia: ambos os lados apresentam edge positivo",
            "conflict": "both_sides_positive_edge",
        }

    state = EDGE_POSITIVE if edge > 0 else EDGE_NEGATIVE if edge < 0 else EDGE_ZERO
    div = _mapping(divergence)
    index = div.get(f"indice_evidencia_{side}")
    market = {
        "market_type": "Moneyline",
        "market": f"Moneyline {payload.get(f'player_{side}')}",
        "side": side,
        "player": payload.get(f"player_{side}"),
        "line": None,
        "odd": side_data.get("market_odd"),
        "fair_odd": side_data.get("fair_odd"),
        "sharp_estimate_pct": side_data.get("sharp_estimate_pct"),
        "expected_edge_pct": edge,
    }
    coverage = _mapping(assessment.get("coverage"))
    try:
        raw_ratio = coverage.get("weighted_ratio")
        coverage_ratio = float(raw_ratio) if raw_ratio is not None else float(coverage.get("weighted_pct")) / 100.0
    except (TypeError, ValueError):
        coverage_ratio = 0.0
    coverage_sufficient_for_paper = coverage_ratio >= PAPER_MIN_WEIGHTED_COVERAGE
    if state == EDGE_POSITIVE and not coverage_sufficient_for_paper:
        state = EDGE_POSITIVE_COVERAGE_INSUFFICIENT
        reason = (
            f"edge positivo, mas cobertura ponderada de {coverage_ratio:.1%} "
            f"inferior ao mínimo PAPER de {PAPER_MIN_WEIGHTED_COVERAGE:.0%}"
        )
    else:
        reason = "edge positivo" if state == EDGE_POSITIVE else (
            "edge negativo" if state == EDGE_NEGATIVE else "edge exatamente zero"
        )
    paper_markets = [market] if state == EDGE_POSITIVE else []
    return {
        **base,
        "state": state,
        "reason": reason,
        "side": side,
        "player": payload.get(f"player_{side}"),
        "fenzobot_index": index,
        "expected_edge_pct": edge,
        "market": market,
        "paper_eligible": state == EDGE_POSITIVE,
        "paper_markets": paper_markets,
    }
