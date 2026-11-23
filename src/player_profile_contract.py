"""Contrato estruturado e pesquisável das fichas de jogador v2.

Este módulo não altera previsões nem pesos. Organiza evidência factual para
alimentar a futura base visual de jogadores e deixa explícito se cada métrica
é usada pelo modelo, apenas descritiva ou candidata a replay.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Mapping


SCHEMA_VERSION = 2

MODEL_ACTIVE = "MODEL_ACTIVE"
CANDIDATE_REPLAY_REQUIRED = "CANDIDATE_REPLAY_REQUIRED"
DESCRIPTIVE_ONLY = "DESCRIPTIVE_ONLY"
MODEL_ROLES = {MODEL_ACTIVE, CANDIDATE_REPLAY_REQUIRED, DESCRIPTIVE_ONLY}


def assess_sample(sample_size: int | None, *, applicable: bool = True) -> dict:
    """Classifica a robustez factual sem transformar ausência em zero.

    A regra pedida para a ficha é deliberadamente conservadora: abaixo de
    20 jogos a amostra é manifestamente baixa e recebe um alerta forte.
    """
    if not applicable:
        return {
            "status": "NOT_APPLICABLE",
            "label": "Não aplicável",
            "alert_level": "NONE",
            "eligible_for_comparison": False,
        }
    if sample_size is None:
        return {
            "status": "UNAVAILABLE",
            "label": "Sem dados",
            "alert_level": "WARNING",
            "eligible_for_comparison": False,
        }
    if sample_size < 0:
        raise ValueError("sample_size não pode ser negativo")
    if sample_size < 20:
        return {
            "status": "VERY_LOW",
            "label": "Amostra muito baixa",
            "alert_level": "CRITICAL",
            "eligible_for_comparison": False,
        }
    if sample_size < 50:
        return {
            "status": "LIMITED",
            "label": "Amostra limitada",
            "alert_level": "WARNING",
            "eligible_for_comparison": True,
        }
    if sample_size < 100:
        return {
            "status": "REASONABLE",
            "label": "Amostra razoável",
            "alert_level": "NONE",
            "eligible_for_comparison": True,
        }
    return {
        "status": "SOLID",
        "label": "Amostra sólida",
        "alert_level": "NONE",
        "eligible_for_comparison": True,
    }


def make_metric(
    *,
    metric_id: str,
    label: str,
    family: str,
    value: object,
    sample_size: int | None,
    source: str,
    model_role: str = DESCRIPTIVE_ONLY,
    applicable: bool = True,
    unit: str | None = None,
    context: Mapping | None = None,
) -> dict:
    if model_role not in MODEL_ROLES:
        raise ValueError(f"model_role inválido: {model_role}")
    if not metric_id or not label or not family or not source:
        raise ValueError("metric_id, label, family e source são obrigatórios")
    return {
        "metric_id": metric_id,
        "label": label,
        "family": family,
        "value": value,
        "unit": unit,
        "sample_size": sample_size,
        "sample_assessment": assess_sample(sample_size, applicable=applicable),
        "source": source,
        "model_role": model_role,
        "context": dict(context or {}),
    }


def build_profile_contract(
    *,
    player_name: str,
    tour: str,
    overall_matches: int,
    metrics: Iterable[Mapping],
    generated_at_utc: str | None = None,
    identity: Mapping | None = None,
) -> dict:
    normalized_tour = str(tour).strip().lower()
    if normalized_tour not in {"atp", "wta"}:
        raise ValueError("tour deve ser atp ou wta")
    if not player_name.strip():
        raise ValueError("player_name é obrigatório")
    overall_assessment = assess_sample(int(overall_matches))
    alerts = []
    if overall_assessment["status"] == "VERY_LOW":
        alerts.append({
            "code": "PLAYER_SAMPLE_BELOW_20",
            "severity": "CRITICAL",
            "message": (
                f"Apenas {overall_matches} jogos disponíveis. A ficha é factual, "
                "mas não deve sustentar conclusões fortes."
            ),
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or datetime.now(timezone.utc).isoformat(),
        "player": {
            "name": player_name.strip(),
            "tour": normalized_tour,
            **dict(identity or {}),
        },
        "overall_sample": {
            "matches": int(overall_matches),
            **overall_assessment,
        },
        "alerts": alerts,
        "metrics": [dict(metric) for metric in metrics],
    }


def build_search_index_entry(profile: Mapping) -> dict:
    player = dict(profile.get("player") or {})
    sample = dict(profile.get("overall_sample") or {})
    return {
        "name": player.get("name"),
        "tour": player.get("tour"),
        "player_id": player.get("player_id"),
        "country": player.get("country"),
        "current_rank": player.get("current_rank"),
        "matches": sample.get("matches"),
        "sample_status": sample.get("status"),
        "has_critical_alert": any(
            alert.get("severity") == "CRITICAL"
            for alert in (profile.get("alerts") or [])
        ),
        "generated_at_utc": profile.get("generated_at_utc"),
    }
