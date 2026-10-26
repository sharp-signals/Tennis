"""Contrato único de promoção do pricing SHADOW."""

from __future__ import annotations

from typing import Any


PROMOTION_GATE_VERSION = "pricing-promotion-gate-v1"
# Só pode mudar através de uma alteração explícita, auditada e versionada
# após aprovação humana dos resultados walk-forward.
PROMOTION_APPROVED = False


def promotion_gate() -> dict[str, Any]:
    return {
        "version": PROMOTION_GATE_VERSION,
        "passed": PROMOTION_APPROVED,
        "reason": (
            "explicit_walk_forward_approval"
            if PROMOTION_APPROVED
            else "manual_audit_required_and_no_automatic_promotion"
        ),
    }

