"""Política canónica de cobertura por tier de torneio.

O módulo separa explicitamente três capacidades: relatório factual, pricing
experimental e persistência PAPER. Não decide edge, não altera thresholds e
não contém exceções por nome ou tournamentId.
"""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping

from .config import (
    CHALLENGER_EXPERIMENTAL_HIGH_CONFIDENCE_COVERAGE,
    CHALLENGER_EXPERIMENTAL_MIN_EDGE_HIGH_CONFIDENCE_PCT,
    CHALLENGER_EXPERIMENTAL_MIN_EDGE_PARTIAL_PCT,
    CHALLENGER_EXPERIMENTAL_STRONG_EVIDENCE_COVERAGE,
    CHALLENGER_MANUAL_PAPER_MIN_FENZOBOT_INDEX,
    CHALLENGER_MANUAL_PAPER_MIN_RECENT_MATCHES,
    CHALLENGER_MANUAL_PAPER_STAKE_UNITS,
    CHALLENGER_MANUAL_PAPER_STRATEGY,
    EXPERIMENTAL_REPORT_ONLY_TIERS,
    EXPERIMENTAL_TIER_PAPER_REASON_CODE,
)


EXPERIMENTAL_EDGE_STATE = "EDGE_POSITIVE_EXPERIMENTAL_TIER"
EXPERIMENTAL_EDGE_BELOW_THRESHOLD_STATE = "EXPERIMENTAL_EDGE_BELOW_THRESHOLD"
EXPERIMENTAL_MANUAL_PAPER_CANDIDATE_STATE = "CHALLENGER_125_MANUAL_PAPER_CANDIDATE"


def _coverage_ratio(decision: Mapping[str, Any]) -> float:
    try:
        return float((decision.get("coverage") or {}).get("weighted_ratio") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _challenger_edge_rule(coverage: float) -> tuple[float, str]:
    """Limiar de edge para um alerta Challenger, não para PAPER."""
    if coverage >= CHALLENGER_EXPERIMENTAL_HIGH_CONFIDENCE_COVERAGE:
        evidence = (
            "evidência forte" if coverage >= CHALLENGER_EXPERIMENTAL_STRONG_EVIDENCE_COVERAGE
            else "evidência suficiente"
        )
        return CHALLENGER_EXPERIMENTAL_MIN_EDGE_HIGH_CONFIDENCE_PCT, evidence
    return CHALLENGER_EXPERIMENTAL_MIN_EDGE_PARTIAL_PCT, "evidência limitada"


def _recent_match_count(payload: Mapping[str, Any], side: str) -> int:
    """Amostra recente válida, sem inferir dados quando a fonte a omite."""
    try:
        value = (payload.get(f"recent_form_{side}") or {}).get("matches")
        count = int(value)
    except (AttributeError, TypeError, ValueError):
        return 0
    return max(0, count)


def _manual_paper_candidate_reason(
    payload: Mapping[str, Any],
    decision: Mapping[str, Any],
    edge_pct: float | None,
    coverage: float,
    threshold: float,
) -> str | None:
    """Devolve o bloqueio explícito para a seleção manual Challenger 0,5u."""
    if edge_pct is None or edge_pct < threshold:
        return "edge abaixo do mínimo experimental"
    try:
        index = float(decision.get("fenzobot_index"))
    except (TypeError, ValueError):
        return "índice Fenzobot indisponível"
    if index < CHALLENGER_MANUAL_PAPER_MIN_FENZOBOT_INDEX:
        return f"índice Fenzobot inferior a {CHALLENGER_MANUAL_PAPER_MIN_FENZOBOT_INDEX}"
    if coverage < 0.50:
        return "cobertura ponderada inferior a 50%"
    samples = [_recent_match_count(payload, side) for side in ("a", "b")]
    if min(samples) < CHALLENGER_MANUAL_PAPER_MIN_RECENT_MATCHES:
        return (
            "forma recente inferior a "
            f"{CHALLENGER_MANUAL_PAPER_MIN_RECENT_MATCHES} jogos para pelo menos um jogador"
        )
    if not isinstance(decision.get("market"), Mapping):
        return "mercado Moneyline indisponível"
    return None


def coverage_policy(tier: object) -> dict[str, Any]:
    """Devolve a política declarativa do tier sem consultar fontes externas."""
    normalized = str(tier or "").strip()
    if normalized in EXPERIMENTAL_REPORT_ONLY_TIERS:
        return {
            "mode": "EXPERIMENTAL_REPORT_ONLY",
            "tier": normalized,
            "label": f"{normalized} · EXPERIMENTAL",
            "analysis_allowed": True,
            "pricing_allowed": True,
            "paper_allowed": False,
            "green_allowed": False,
            "reason_code": EXPERIMENTAL_TIER_PAPER_REASON_CODE,
        }
    return {
        "mode": "STANDARD",
        "tier": normalized or None,
        "analysis_allowed": True,
        "pricing_allowed": True,
        "paper_allowed": True,
        "green_allowed": True,
        "reason_code": None,
    }


def is_experimental_report_only(payload: Mapping[str, Any]) -> bool:
    """Reconhece o tier pela configuração, mesmo antes de existir metadata."""
    metadata = payload.get("tournament_coverage")
    if isinstance(metadata, Mapping):
        return metadata.get("mode") == "EXPERIMENTAL_REPORT_ONLY"
    return str(payload.get("tier") or "").strip() in EXPERIMENTAL_REPORT_ONLY_TIERS


def is_experimental_snapshot(snapshot: Mapping[str, Any]) -> bool:
    """Distingue snapshots explicitamente marcados sem reclassificar legacy.

    Snapshots anteriores ao CHANGE-053 não possuem ``tournament_coverage`` e
    mantêm, por isso, exatamente a semântica histórica. O tier isolado não é
    suficiente para retirar uma observação legacy da calibração standard.
    """
    metadata = snapshot.get("tournament_coverage")
    return (
        isinstance(metadata, Mapping)
        and metadata.get("mode") == "EXPERIMENTAL_REPORT_ONLY"
    )


def paper_block_reason(payload: Mapping[str, Any]) -> str | None:
    if not is_experimental_report_only(payload):
        return None
    metadata = payload.get("tournament_coverage")
    if isinstance(metadata, Mapping) and metadata.get("reason_code"):
        return str(metadata["reason_code"])
    return EXPERIMENTAL_TIER_PAPER_REASON_CODE


def apply_experimental_paper_gate(payload: MutableMapping[str, Any]) -> bool:
    """Bloqueia PAPER/GREEN sem esconder o pricing factual já calculado.

    O estado específico mantém explícito que existia edge positivo segundo a
    lógica normal, mas que a persistência foi bloqueada pelo regime EXPERIMENT.
    Retorna ``True`` apenas quando seria candidato PAPER sem este gate.
    """
    policy = coverage_policy(payload.get("tier"))
    payload["tournament_coverage"] = policy
    if policy["mode"] != "EXPERIMENTAL_REPORT_ONLY":
        return False
    decision = payload.get("prelive_decision")
    if not isinstance(decision, MutableMapping):
        return False
    # Para Challenger, um edge positivo com 50--59,9% de dados ainda pode ser
    # observado, embora a política PAPER standard o excluísse. É por isso que
    # olhamos para o estado/edge, nunca para uma inferência de ranking.
    edge = decision.get("expected_edge_pct")
    try:
        edge_pct = float(edge)
    except (TypeError, ValueError):
        edge_pct = None
    coverage = _coverage_ratio(decision)
    threshold, evidence_band = _challenger_edge_rule(coverage)
    positive_edge = edge_pct is not None and edge_pct > 0
    would_be_candidate = positive_edge and coverage >= 0.50
    original_markets = decision.get("paper_markets") or []
    manual_candidate_reason = _manual_paper_candidate_reason(
        payload, decision, edge_pct, coverage, threshold,
    )
    manual_candidate = would_be_candidate and manual_candidate_reason is None
    decision["experimental_tier_gate"] = {
        "status": "BLOCKED",
        "reason_code": policy["reason_code"],
        "tier": policy["tier"],
        "paper_eligible": False,
        "green_eligible": False,
        "would_be_paper_candidate": would_be_candidate,
        "would_be_paper_market_count": len(original_markets),
        "data_coverage_pct": round(coverage * 100, 1),
        "minimum_experimental_edge_pct": threshold,
        "evidence_band": evidence_band,
        "manual_paper_candidate": manual_candidate,
        "manual_paper_candidate_reason": manual_candidate_reason,
        "manual_paper_strategy": CHALLENGER_MANUAL_PAPER_STRATEGY,
        "manual_paper_stake_units": CHALLENGER_MANUAL_PAPER_STAKE_UNITS,
        "minimum_fenzobot_index": CHALLENGER_MANUAL_PAPER_MIN_FENZOBOT_INDEX,
        "minimum_recent_matches_per_player": CHALLENGER_MANUAL_PAPER_MIN_RECENT_MATCHES,
    }
    if would_be_candidate:
        decision["state_before_experimental_gate"] = decision.get("state")
        if manual_candidate:
            decision["state"] = EXPERIMENTAL_MANUAL_PAPER_CANDIDATE_STATE
            decision["reason"] = (
                f"candidato Challenger manual de {CHALLENGER_MANUAL_PAPER_STAKE_UNITS:g}u: "
                f"edge {edge_pct:+.1f}%, índice {float(decision.get('fenzobot_index')):.0f}/100, "
                f"cobertura {coverage:.0%} ({evidence_band})"
            )
        elif edge_pct >= threshold:
            decision["state"] = EXPERIMENTAL_EDGE_STATE
            decision["reason"] = (
                f"edge positivo Challenger de {edge_pct:+.1f}% com {coverage:.0%} de dados "
                f"({evidence_band}); sem candidatura manual: {manual_candidate_reason}"
            )
        else:
            decision["state"] = EXPERIMENTAL_EDGE_BELOW_THRESHOLD_STATE
            decision["reason"] = (
                f"edge Challenger de {edge_pct:+.1f}% abaixo do mínimo experimental de "
                f"{threshold:.1f}% para {coverage:.0%} de dados; análise factual apenas"
            )
    decision["paper_eligible"] = False
    decision["paper_markets"] = []
    return would_be_candidate
