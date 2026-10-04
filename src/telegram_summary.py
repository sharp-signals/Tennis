"""Formatação testável dos quatro estados operacionais do Telegram."""

from __future__ import annotations

import html


def decision_row(payload: dict) -> tuple[int, str, str]:
    decision = payload.get("prelive_decision") or {}
    state = decision.get("state")
    a = html.escape(str(payload.get("player_a") or "?"))
    b = html.escape(str(payload.get("player_b") or "?"))
    player = html.escape(str(decision.get("player") or ""))
    edge = decision.get("expected_edge_pct")
    try:
        edge_text = f"{float(edge):+.1f}%"
    except (TypeError, ValueError):
        edge_text = "N/D"
    if state == "EDGE_POSITIVE":
        market = html.escape(str((decision.get("market") or {}).get("market") or "Moneyline"))
        identity_gate = decision.get("identity_gate") or {}
        if payload.get("identity_schema_version") == 2 and identity_gate.get("paper_eligible") is False:
            status = html.escape(str(identity_gate.get("status") or "IDENTITY_UNAVAILABLE"))
            return 2.5, "🟡", (
                f"{a} vs {b} — edge positivo {edge_text}, mas identidade canónica pendente "
                f"({status}) · sem PAPER"
            )
        return 3, "🟢", f"{a} vs {b} — <b>EDGE POSITIVO {edge_text}</b> · PAPER {market}"
    if state == "EDGE_POSITIVE_COVERAGE_INSUFFICIENT":
        coverage = (decision.get("coverage") or {}).get("weighted_pct")
        try:
            coverage_text = f"{float(coverage):.1f}%"
        except (TypeError, ValueError):
            coverage_text = "N/D"
        return 2.5, "🟡", f"{a} vs {b} — edge positivo {edge_text}, mas cobertura {coverage_text} insuficiente para PAPER"
    if state == "CHALLENGER_125_MANUAL_PAPER_CANDIDATE":
        gate = decision.get("experimental_tier_gate") or {}
        stake = gate.get("manual_paper_stake_units", 0.5)
        index = decision.get("fenzobot_index", "N/D")
        return 2.75, "🟣", (
            f"{a} vs {b} — <b>CHALLENGER 125 · CANDIDATO PAPER MANUAL {str(stake).replace('.', ',')}u</b> "
            f"· índice {index}/100 · edge {edge_text} · confirmar 22Bet"
        )
    if state == "EDGE_POSITIVE_EXPERIMENTAL_TIER":
        reason = html.escape(str(
            (decision.get("experimental_tier_gate") or {}).get("reason_code")
            or "EXPERIMENTAL_TIER"
        ))
        return 2.5, "🟡", (
            f"{a} vs {b} — edge positivo {edge_text} · Challenger 125 EXPERIMENTAL "
            f"· sem PAPER ({reason})"
        )
    if state == "EXPERIMENTAL_EDGE_BELOW_THRESHOLD":
        gate = decision.get("experimental_tier_gate") or {}
        threshold = gate.get("minimum_experimental_edge_pct", "N/D")
        return 0.8, "🟣", (
            f"{a} vs {b} — <b>CHALLENGER 125 · EDGE NÃO QUALIFICADO</b> "
            f"{edge_text} &lt; mínimo {html.escape(str(threshold))}% · sem PAPER"
        )
    if state == "EDGE_NEGATIVE":
        return 2, "🔴", f"{a} vs {b} — edge negativo {edge_text} em {player} · excluído"
    if state == "EDGE_ZERO":
        if not player:
            return 1, "⚪", f"{a} vs {b} — índice Fenzobot equilibrado · sem edge/PAPER"
        return 1, "⚪", f"{a} vs {b} — edge exatamente 0,0% em {player} · excluído"
    if state == "PRICING_UNAVAILABLE":
        reason = html.escape(str(decision.get("reason") or "preço de mercado indisponível"))
        return 0.5, "🟡", f"{a} vs {b} — <b>MERCADO PENDENTE</b> · análise factual disponível · reconsulta automática · {reason}"
    if state == "EXPERIMENTAL_FACTUAL_PARTIAL":
        reason = html.escape(str(decision.get("reason") or "cobertura bilateral parcial"))
        return 0.75, "🟡", (
            f"{a} vs {b} — <b>CHALLENGER 125 · COBERTURA PARCIAL</b> · "
            f"sem edge/PAPER · {reason}"
        )
    reason = html.escape(str(decision.get("reason") or "dados insuficientes"))
    return 0, "⚫", f"{a} vs {b} — <b>RELATÓRIO NULO</b> · {reason}"


def state_counts(payloads) -> dict[str, int]:
    counts = {"EDGE_POSITIVE": 0, "EDGE_POSITIVE_COVERAGE_INSUFFICIENT": 0, "CHALLENGER_125_MANUAL_PAPER_CANDIDATE": 0, "EDGE_NEGATIVE": 0, "EDGE_ZERO": 0, "PRICING_UNAVAILABLE": 0, "EXPERIMENTAL_FACTUAL_PARTIAL": 0, "EXPERIMENTAL_EDGE_BELOW_THRESHOLD": 0, "REPORT_NULL": 0}
    for payload in payloads:
        state = (payload.get("prelive_decision") or {}).get("state")
        if state == "EDGE_POSITIVE_EXPERIMENTAL_TIER":
            state = "EDGE_POSITIVE_COVERAGE_INSUFFICIENT"
        counts[state if state in counts else "REPORT_NULL"] += 1
    return counts
