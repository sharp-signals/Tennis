"""Política canónica de cobertura por tier de torneio.

O módulo separa explicitamente três capacidades: relatório factual, pricing
experimental e persistência PAPER. Não decide edge, não altera thresholds e
não contém exceções por nome ou tournamentId.
"""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping

from .config import (
    EXPERIMENTAL_REPORT_ONLY_TIERS,
    EXPERIMENTAL_TIER_PAPER_REASON_CODE,
)


EXPERIMENTAL_EDGE_STATE = "EDGE_POSITIVE_EXPERIMENTAL_TIER"


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
    would_be_candidate = decision.get("paper_eligible") is True
    original_markets = decision.get("paper_markets") or []
    decision["experimental_tier_gate"] = {
        "status": "BLOCKED",
        "reason_code": policy["reason_code"],
        "tier": policy["tier"],
        "paper_eligible": False,
        "green_eligible": False,
        "would_be_paper_candidate": would_be_candidate,
        "would_be_paper_market_count": len(original_markets),
    }
    if would_be_candidate:
        decision["state_before_experimental_gate"] = decision.get("state")
        decision["state"] = EXPERIMENTAL_EDGE_STATE
        decision["reason"] = (
            "edge positivo observado, mas o tier Challenger 125 permanece "
            "experimental e não é elegível para PAPER"
        )
    decision["paper_eligible"] = False
    decision["paper_markets"] = []
    return would_be_candidate
