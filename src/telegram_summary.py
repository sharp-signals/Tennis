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
        return 3, "🟢", f"{a} vs {b} — <b>EDGE POSITIVO {edge_text}</b> · PAPER {market}"
    if state == "EDGE_POSITIVE_COVERAGE_INSUFFICIENT":
        coverage = (decision.get("coverage") or {}).get("weighted_pct")
        try:
            coverage_text = f"{float(coverage):.1f}%"
        except (TypeError, ValueError):
            coverage_text = "N/D"
        return 2.5, "🟡", f"{a} vs {b} — edge positivo {edge_text}, mas cobertura {coverage_text} insuficiente para PAPER"
    if state == "EDGE_NEGATIVE":
        return 2, "🔴", f"{a} vs {b} — edge negativo {edge_text} em {player} · excluído"
    if state == "EDGE_ZERO":
        return 1, "⚪", f"{a} vs {b} — edge exatamente 0,0% em {player} · excluído"
    if state == "PRICING_UNAVAILABLE":
        reason = html.escape(str(decision.get("reason") or "preço de mercado indisponível"))
        return 0, "🟡", f"{a} vs {b} — <b>PREÇO INDISPONÍVEL</b> · análise factual disponível · {reason}"
    reason = html.escape(str(decision.get("reason") or "dados insuficientes"))
    return 0, "⚫", f"{a} vs {b} — <b>RELATÓRIO NULO</b> · {reason}"


def state_counts(payloads) -> dict[str, int]:
    counts = {"EDGE_POSITIVE": 0, "EDGE_POSITIVE_COVERAGE_INSUFFICIENT": 0, "EDGE_NEGATIVE": 0, "EDGE_ZERO": 0, "PRICING_UNAVAILABLE": 0, "REPORT_NULL": 0}
    for payload in payloads:
        state = (payload.get("prelive_decision") or {}).get("state")
        counts[state if state in counts else "REPORT_NULL"] += 1
    return counts
