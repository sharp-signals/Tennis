"""Isolated report view-model and HTML renderer for contextual SHADOW v2."""

from __future__ import annotations

import base64
from datetime import datetime
from functools import lru_cache
import html
import json
import math
from pathlib import Path
from typing import Any, Mapping

from .contextual_shadow_handicap_v2 import build_market_review
from .contextual_shadow_moneyline_v1 import select_moneyline_history


CONTRACT_PATH = Path("data/models/contextual-shadow-report-v2.json")
PLAYER_IMAGES_PATH = Path("data/player_images.json")
MODEL_VERSION = "contextual-family-shadow-v2"


def load_report_contract(
    path: Path = CONTRACT_PATH,
    *,
    expected_model_version: str = MODEL_VERSION,
    expected_contract_version: str = "contextual-shadow-report-v2.2",
) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    rules = value.get("rules") or {}
    if (
        value.get("contract_version") != expected_contract_version
        or value.get("model_version") != expected_model_version
        or value.get("mode") != "SHADOW_PREVIEW_ONLY"
        or rules.get("market_must_not_enter_model_probability") is not True
        or rules.get("handicap_evidence_must_be_frozen_with_prediction") is not True
        or rules.get("handicap_requires_own_line_probability") is not True
        or rules.get("moneyline_evidence_must_be_frozen_with_prediction") is not True
        or rules.get("main_family_impact_must_use_probability_points") is not True
        or rules.get("technical_logits_must_remain_collapsed") is not True
        or rules.get("dependency_must_be_graded_not_binary") is not True
        or rules.get("market_divergence_is_diagnostic_only") is not True
        or rules.get("player_header_must_show_frozen_odds_when_available") is not True
        or (
            expected_contract_version in {
                "fenzobot-contextual-2026-11-report.5",
                "fenzobot-contextual-2026-11-report.6",
            }
            and (
                rules.get("latest_market_snapshot_must_be_used_for_display") is not True
                or rules.get("first_market_snapshot_must_be_used_for_evaluation") is not True
                or rules.get("four_handicap_reference_lines_must_be_highlighted") is not True
            )
        )
        or (
            expected_contract_version == "fenzobot-contextual-2026-11-report.6"
            and (
                rules.get("handicap_references_must_follow_model_side") is not True
                or rules.get("public_family_details_must_use_human_labels") is not True
                or rules.get("public_report_must_hide_internal_identifiers") is not True
            )
        )
        or rules.get("no_betting_recommendation") is not True
        or rules.get("no_automatic_publication") is not True
    ):
        raise ValueError("invalid contextual SHADOW report contract")
    return value


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _display_name(value: Any) -> str:
    text = " ".join(str(value or "").split())
    return text.title() if text else "Jogador N/D"


@lru_cache(maxsize=1)
def _player_images() -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        rows = json.loads(PLAYER_IMAGES_PATH.read_text(encoding="utf-8"))["players"]
    except (OSError, ValueError, KeyError, TypeError):
        rows = {}
    by_name = {
        " ".join(str(item.get("name") or "").casefold().split()): item
        for item in rows.values() if isinstance(item, Mapping)
    }
    return rows, by_name


def _player_image_url(tour: Any, player_id: Any, name: Any) -> str | None:
    rows, by_name = _player_images()
    item = rows.get(f"{str(tour).casefold()}:{player_id}")
    if not isinstance(item, Mapping):
        item = by_name.get(" ".join(str(name or "").casefold().split()))
    path = str((item or {}).get("path") or "")
    marker = "assets/players/"
    if marker not in path:
        return None
    filename = path.split(marker, 1)[1]
    local = Path("docs/assets/players") / filename
    try:
        encoded = base64.b64encode(local.read_bytes()).decode("ascii")
    except OSError:
        return f"https://sharp-signals.github.io/Tennis/assets/players/{filename}"
    mime = "image/png" if local.suffix.casefold() == ".png" else "image/jpeg"
    return f"data:{mime};base64,{encoded}"


def _market_plausibility(
    *, market_probability_a: float | None, interval_a: list[float],
) -> dict[str, Any]:
    """Audit market disagreement after prediction without changing pricing."""
    if market_probability_a is None:
        return {"status": "UNAVAILABLE", "requires_manual_review": False}
    lower, upper = interval_a
    if lower <= market_probability_a <= upper:
        return {
            "status": "WITHIN_MODEL_INTERVAL",
            "requires_manual_review": False,
            "distance_pp": 0.0,
        }
    distance = lower - market_probability_a if market_probability_a < lower else market_probability_a - upper
    return {
        "status": "OUTSIDE_MODEL_INTERVAL",
        "requires_manual_review": True,
        "market_side": "b" if market_probability_a < lower else "a",
        "distance_pp": round(100.0 * distance, 2),
        "rule": "MARKET_PROBABILITY_OUTSIDE_MODEL_90_INTERVAL",
    }


def _display_time(value: Any) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return "Data N/D"
    return parsed.strftime("%d/%m/%Y · %H:%M UTC")


def _fair_odd(value: Mapping[str, Any] | None) -> dict[str, float | None]:
    source = value or {}
    return {
        "central": _number(source.get("central")),
        "lower": _number(source.get("lower_odd")),
        "upper": _number(source.get("upper_odd")),
    }


def _state_label(value: Any) -> str:
    return {
        "OBSERVED": "Observado",
        "OBSERVED_NONE": "Consultado · sem ocorrências",
        "INSUFFICIENT_SAMPLE": "Amostra insuficiente",
        "UNAVAILABLE": "Dados indisponíveis",
        "DIAGNOSTIC_ONLY": "Apenas diagnóstico",
        "NOT_APPLICABLE": "Não aplicável",
    }.get(str(value or "").upper(), str(value or "N/D"))


def _coverage_grade_label(value: Any) -> str:
    return {
        "SOLID": "Evidência sólida",
        "PARTIAL": "Evidência parcial",
        "OBSERVED_NEUTRAL": "Consultado · sem ocorrência",
        "UNAVAILABLE": "Indisponível",
    }.get(str(value or "").upper(), "Indisponível")


def _impact_label(value: Any) -> str:
    return {
        "SLIGHT": "ligeiro", "MODERATE": "moderado",
        "STRONG": "forte", "DECISIVE": "muito forte",
    }.get(str(value or "").upper(), "neutro")


def _quality_label(value: Any) -> str:
    return {
        "PRIMARY_READY_COMPLETE": "Famílias principais completas",
        "PRIMARY_READY_SECONDARY_GAPS": "Principais prontas · lacunas secundárias",
        "PRIMARY_DEGRADED": "Família principal em falta",
    }.get(str(value or ""), str(value or "Qualidade N/D"))


def _surface_label(value: Any) -> str:
    key = str(value or "").strip().casefold()
    return {
        "i.hard": "Rápido indoor",
        "hard_indoor": "Rápido indoor",
        "hard_outdoor": "Rápido outdoor",
        "clay": "Terra batida",
        "grass": "Relva",
        "carpet": "Carpete",
    }.get(key, str(value or "Contexto N/D").replace("_", " ").title())


def _round_stage_label(value: Any) -> str:
    return {
        "QUALIFYING": "Qualificação",
        "EARLY_ROUNDS": "Primeiras rondas",
        "LATE_STAGES": "Fases finais",
        "ROUND_UNRESOLVED": "Ronda N/D",
    }.get(str(value or ""), str(value or "Ronda N/D"))


def _competition_round_label(competition: Mapping[str, Any]) -> str:
    """Translate special provider stages without changing model buckets."""
    stage = _round_stage_label(competition.get("round_stage"))
    if stage != "Ronda N/D":
        return stage
    tier = str(competition.get("tier") or "").strip().casefold()
    tournament = str(competition.get("tournament_name") or "").casefold()
    try:
        round_id = int(competition.get("round_id"))
    except (TypeError, ValueError):
        round_id = None
    if round_id == 8 and (
        tier == "championships" or "wta finals" in tournament
    ):
        return "Fase de grupos"
    return stage


def _status_label(value: Any) -> str:
    return {
        "READY_FOR_PROSPECTIVE_SHADOW": "Pronto para validação prospetiva",
        "NOT_OPERATIONALLY_READY": "Ainda não pronto para utilização operacional",
    }.get(str(value or ""), str(value or "Estado N/D"))


def _market_is_valid(
    observation: Mapping[str, Any], market: Mapping[str, Any] | None,
    *, expected_model_version: str = MODEL_VERSION,
) -> bool:
    if not isinstance(market, Mapping):
        return False
    return (
        market.get("observation_id") == observation.get("observation_id")
        and market.get("model_version") == expected_model_version
        and market.get("first_valid_quote_frozen") is True
        and market.get("production_effect") is False
    )


def _player_market(
    *, probability: float, interval_lower: float, odd: float | None,
    market_probability: float | None,
) -> dict[str, float | None]:
    if odd is None or market_probability is None:
        return {
            "odd": None,
            "probability": None,
            "probability_edge_pp": None,
            "expected_value_pct": None,
            "conservative_expected_value_pct": None,
        }
    return {
        "odd": odd,
        "probability": market_probability,
        "probability_edge_pp": 100.0 * (probability - market_probability),
        "expected_value_pct": 100.0 * (probability * odd - 1.0),
        "conservative_expected_value_pct": 100.0 * (
            interval_lower * odd - 1.0
        ),
    }


def build_report_view_model(
    observation: Mapping[str, Any],
    market: Mapping[str, Any] | None = None,
    outcome: Mapping[str, Any] | None = None,
    handicap_evidence: Mapping[str, Any] | None = None,
    moneyline_evidence: Mapping[str, Any] | None = None,
    *,
    contract: Mapping[str, Any] | None = None,
    expected_model_version: str = MODEL_VERSION,
) -> dict[str, Any]:
    """Join frozen ledgers without changing or recalculating the prediction."""
    contract = dict(contract or load_report_contract())
    shadow = observation.get("contextual_shadow") or {}
    if (
        (
            shadow.get("model_version") or shadow.get("global_release_id")
        ) != expected_model_version
        or shadow.get("market_used") is not False
        or shadow.get("production_effect") is not False
        or observation.get("paper_eligible") is not False
        or observation.get("green_eligible") is not False
    ):
        raise ValueError("contextual SHADOW report isolation violated")
    probability_a = float(shadow["probability_model_a"])
    probability_b = float(shadow["probability_model_b"])
    interval_a = list(map(float, shadow["probability_interval_90_model_a"]))
    interval_b = [1.0 - interval_a[1], 1.0 - interval_a[0]]
    valid_market = _market_is_valid(
        observation, market,
        expected_model_version=expected_model_version,
    )
    market = market if valid_market else None
    odds = (market or {}).get("odds") or {}
    market_probabilities = (market or {}).get("market_probability_devig") or {}
    player_a = (observation.get("players") or {}).get("a") or {}
    player_b = (observation.get("players") or {}).get("b") or {}
    competition = observation.get("competition") or {}
    valid_handicap_evidence = bool(
        isinstance(handicap_evidence, Mapping)
        and handicap_evidence.get("observation_id")
        == observation.get("observation_id")
        and handicap_evidence.get("model_version") == expected_model_version
        and handicap_evidence.get("configuration_fingerprint")
        == shadow.get("configuration_fingerprint")
        and handicap_evidence.get("production_effect") is False
    )
    valid_moneyline_evidence = bool(
        isinstance(moneyline_evidence, Mapping)
        and moneyline_evidence.get("observation_id")
        == observation.get("observation_id")
        and moneyline_evidence.get("model_version") == expected_model_version
        and moneyline_evidence.get("configuration_fingerprint")
        == shadow.get("configuration_fingerprint")
        and moneyline_evidence.get("production_effect") is False
    )

    family_rows = []
    absolute_total = sum(
        abs(float(item.get("impact_pp_model_a") or 0.0))
        for item in shadow.get("families") or []
    )
    for family in shadow.get("families") or []:
        contribution = float(family.get("impact_pp_model_a") or 0.0)
        if contribution > 1e-9:
            direction = "a"
        elif contribution < -1e-9:
            direction = "b"
        else:
            direction = "neutral"
        family_rows.append({
            "key": family.get("key"),
            "label": family.get("label") or family.get("key"),
            "data_state": family.get("data_state"),
            "data_state_label": _state_label(family.get("data_state")),
            "coverage_grade": family.get("coverage_grade") or "UNAVAILABLE",
            "coverage_grade_label": _coverage_grade_label(
                family.get("coverage_grade")
            ),
            "probability_a": _number(family.get("probability_model_a")),
            "impact_pp_model_a": contribution,
            "impact_intensity": family.get("impact_intensity") or "NEUTRAL",
            "impact_intensity_label": _impact_label(
                family.get("impact_intensity")
            ),
            "direction": direction,
            "direction_name": (
                _display_name(player_a.get("name")) if direction == "a"
                else _display_name(player_b.get("name")) if direction == "b"
                else "Sem vantagem material"
            ),
            "relative_contribution_pct": (
                100.0 * abs(contribution) / absolute_total
                if absolute_total > 0.0 else 0.0
            ),
            "internal_trace": dict(family.get("internal_trace") or {}),
            "context_audit": dict(family.get("context_audit") or {}),
        })

    market_a = _player_market(
        probability=probability_a,
        interval_lower=interval_a[0],
        odd=_number(odds.get("a")),
        market_probability=_number(market_probabilities.get("a")),
    )
    market_b = _player_market(
        probability=probability_b,
        interval_lower=interval_b[0],
        odd=_number(odds.get("b")),
        market_probability=_number(market_probabilities.get("b")),
    )
    comparisons = [("a", market_a), ("b", market_b)]
    comparisons = [
        item for item in comparisons
        if item[1]["probability_edge_pp"] is not None
    ]
    benchmark_side = max(
        comparisons,
        key=lambda item: float(item[1]["probability_edge_pp"]),
        default=(None, {}),
    )[0]
    winner_side = None
    plausibility = _market_plausibility(
        market_probability_a=_number(market_probabilities.get("a")),
        interval_a=interval_a,
    )
    if isinstance(outcome, Mapping) and (
        outcome.get("observation_id") == observation.get("observation_id")
    ):
        winner_side = outcome.get("winner_side")
    market_review = build_market_review(
        probabilities={"a": probability_a, "b": probability_b},
        intervals={"a": interval_a, "b": interval_b},
        odds={
            side: float(value) for side, value in odds.items()
            if side in {"a", "b"} and _number(value) is not None
        },
        evidence_record=handicap_evidence if valid_handicap_evidence else None,
        handicap_side="a" if probability_a >= probability_b else "b",
    )
    match_format = str(
        ((handicap_evidence or {}).get("handicap_evidence") or {}).get("format")
        or "bo3"
    )
    moneyline_history_a = select_moneyline_history(
        moneyline_evidence if valid_moneyline_evidence else None,
        side="a", observed_odd=_number(odds.get("a")),
        match_format=match_format,
    )
    moneyline_history_b = select_moneyline_history(
        moneyline_evidence if valid_moneyline_evidence else None,
        side="b", observed_odd=_number(odds.get("b")),
        match_format=match_format,
    )
    sensitivity = dict(shadow.get("family_sensitivity") or {})
    if sensitivity.get("dependency_grade") == "CRITICAL_DEPENDENCE":
        market_review = {
            "status": "FAVORITE_UNCONFIRMED",
            "candidate_side": None,
            "central_ev_pct": None,
            "conservative_ev_pct": None,
        }

    arguments_a = sorted(
        (item for item in family_rows if item["impact_pp_model_a"] > 0),
        key=lambda item: item["impact_pp_model_a"], reverse=True,
    )[:2]
    arguments_b = sorted(
        (item for item in family_rows if item["impact_pp_model_a"] < 0),
        key=lambda item: item["impact_pp_model_a"],
    )[:2]

    return {
        "contract_version": contract["contract_version"],
        "mode": "SHADOW_PREVIEW_ONLY",
        "observation_id": observation.get("observation_id"),
        "canonical_match_instance_id": observation.get(
            "canonical_match_instance_id"
        ),
        "model_version": (
            shadow.get("model_version") or shadow.get("global_release_id")
        ),
        "global_release_id": shadow.get("global_release_id"),
        "component_versions": dict(shadow.get("component_versions") or {}),
        "configuration_fingerprint": shadow.get("configuration_fingerprint"),
        "tour": str(observation.get("tour") or "").upper(),
        "tier": observation.get("tier") or "Tier N/D",
        "tournament_name": competition.get("tournament_name") or "Torneio N/D",
        "round_stage": _competition_round_label({
            **competition, "tier": observation.get("tier"),
        }),
        "surface_context": _surface_label(
            competition.get("surface") or shadow.get("surface_context")
        ),
        "commence_time": _display_time(observation.get("commence_time_utc")),
        "analyzed_at": _display_time(observation.get("analyzed_at_utc")),
        "players": {
            "a": {
                "name": _display_name(player_a.get("name")),
                "id": player_a.get("id"),
                "image_url": _player_image_url(
                    observation.get("tour"), player_a.get("id"), player_a.get("name")
                ),
                "probability": probability_a,
                "interval": interval_a,
                "fair_odd": _fair_odd(shadow.get("fair_odd_model_a")),
                "market": market_a,
                "moneyline_history": moneyline_history_a,
            },
            "b": {
                "name": _display_name(player_b.get("name")),
                "id": player_b.get("id"),
                "image_url": _player_image_url(
                    observation.get("tour"), player_b.get("id"), player_b.get("name")
                ),
                "probability": probability_b,
                "interval": interval_b,
                "fair_odd": _fair_odd(shadow.get("fair_odd_model_b")),
                "market": market_b,
                "moneyline_history": moneyline_history_b,
            },
        },
        "families": family_rows,
        "top_arguments": {"a": arguments_a, "b": arguments_b},
        "family_sensitivity": sensitivity,
        "family_coverage": dict(shadow.get("family_coverage") or {}),
        "quality_group": shadow.get("quality_group"),
        "quality_label": _quality_label(shadow.get("quality_group")),
        "model_status": shadow.get("status"),
        "model_status_label": _status_label(shadow.get("status")),
        "reason_codes": list(shadow.get("reason_codes") or []),
        "calibration_bin_sample": shadow.get("calibration_bin_sample"),
        "interval_source": shadow.get("interval_source"),
        "extrapolation": bool(shadow.get("extrapolation")),
        "market": {
            "available": valid_market,
            "benchmark_side": benchmark_side,
            "bookmaker": (market or {}).get("bookmaker"),
            "source": (market or {}).get("source"),
            "captured_at": _display_time((market or {}).get("captured_at_utc")),
            "quote_snapshots": int((market or {}).get("quote_snapshots") or 0),
            "previous_quote": dict((market or {}).get("previous_quote") or {}),
            "overround_pct": (
                100.0 * float(market["overround"])
                if market and market.get("overround") is not None else None
            ),
            "used_for_prediction": False,
            "plausibility": plausibility,
        },
        "outcome": {
            "available": winner_side in {"a", "b"},
            "winner_side": winner_side,
        },
        "market_review": market_review,
        "isolation": {
            "production_effect": False,
            "paper_eligible": False,
            "green_eligible": False,
            "notification_eligible": False,
            "published_as_operational_report": False,
        },
    }


def _pct(value: Any, digits: int = 1) -> str:
    number = _number(value)
    return "N/D" if number is None else f"{100.0 * number:.{digits}f}%"


def _signed(value: Any, suffix: str = "") -> str:
    number = _number(value)
    return "N/D" if number is None else f"{number:+.1f}{suffix}"


def _odd(value: Any) -> str:
    number = _number(value)
    return "N/D" if number is None else f"{number:.2f}"


def _e(value: Any) -> str:
    return html.escape(str(value if value not in (None, "") else "N/D"))


_FEATURE_LABELS = {
    "contextual_recent_result_core_v1": "Resultados recentes",
    "contextual_recent_competitiveness_v1": "Competitividade recente",
    "contextual_recent_win_quality_v1": "Qualidade das vitórias",
    "contextual_recent_competitiveness_residual_v2": "Qualidade das derrotas",
    "contextual_recent_bad_loss_penalty_v2": "Penalização por derrotas inferiores",
    "contextual_recent_result_peer_higher_v5": "Resultados · nível igual/superior",
    "contextual_recent_competitiveness_peer_higher_v5": "Competitividade · nível igual/superior",
    "contextual_recent_win_quality_peer_higher_v5": "Vitórias de qualidade · nível igual/superior",
    "contextual_recent_result_lower_main_v5": "Resultados · nível ATP/WTA inferior",
    "contextual_recent_competitiveness_lower_main_v5": "Competitividade · nível ATP/WTA inferior",
    "contextual_recent_win_quality_lower_main_v5": "Vitórias de qualidade · nível ATP/WTA inferior",
    "contextual_recent_result_challenger_v5": "Resultados · Challenger",
    "contextual_recent_competitiveness_challenger_v5": "Competitividade · Challenger",
    "contextual_recent_win_quality_challenger_v5": "Vitórias de qualidade · Challenger",
    "contextual_recent_result_main_v7": "Resultados recentes · circuito principal",
    "contextual_recent_competitiveness_main_v7": "Competitividade · circuito principal",
    "contextual_recent_win_quality_main_v7": "Vitórias de qualidade · circuito principal",
    "contextual_recent_tier_win_credit_v7": "Qualidade das vitórias ajustada ao nível",
    "contextual_recent_circuit_downshift_v8": "Mudança recente de nível competitivo",
    "contextual_structural_material_rank_core_v6": "Distância material de ranking",
    "contextual_structural_representative_rank_core_v6": "Ranking representativo",
    "contextual_structural_points_log_ratio_v6": "Diferença de pontos",
    "contextual_structural_return_rank_contraction_v7": "Ajuste do ranking durante o regresso",
    "contextual_structural_return_points_contraction_v7": "Ajuste dos pontos durante o regresso",
    "contextual_structural_return_friction_margin_v7": "Contexto de regresso após hiato",
    "contextual_structural_trajectory_margin_v3": "Trajetória do ranking",
    "contextual_structural_inactivity_margin_v3": "Inatividade",
    "contextual_structural_recovery_margin_v3": "Regresso / recuperação",
    "exact_surface_career_margin_shrunk": "Carreira neste piso",
    "exact_surface_previous_margin_shrunk": "Época anterior neste piso",
    "exact_surface_current_margin_shrunk": "Época atual neste piso",
    "exact_surface_tier_win_credit_career_v8": "Qualidade no piso · carreira",
    "exact_surface_tier_win_credit_previous_v8": "Qualidade no piso · época anterior",
    "exact_surface_tier_win_credit_current_v8": "Qualidade no piso · época atual",
    "contextual_h2h_global_shrunk_v1": "Confronto direto global",
    "service_points_won_surface_margin_shrunk_v1": "Serviço no piso",
    "return_points_won_surface_margin_shrunk_v1": "Resposta no piso",
    "service_points_won_recent_deviation_v1": "Serviço recente",
    "return_points_won_recent_deviation_v1": "Resposta recente",
}


def _feature_label(value: Any) -> str:
    key = str(value or "")
    return _FEATURE_LABELS.get(key, key.replace("_", " ").strip().title())


def _factor_strength_label(share: float) -> str:
    if share >= 0.45:
        return "fator dominante nesta família"
    if share >= 0.25:
        return "impacto forte"
    if share >= 0.10:
        return "impacto moderado"
    if share > 0.0:
        return "impacto ligeiro"
    return "sem impacto material"


def _context_value(label: str, value: Any) -> str:
    number = _number(value)
    if number is None:
        return "N/D"
    if label in {"Ranking atual", "Melhor ranking observado"}:
        return f"#{int(round(number))}"
    if label in {"Pontos atuais", "Jogos desde o regresso"}:
        return str(int(round(number)))
    if label == "Representatividade do ranking atual":
        return f"{100.0 * number:.0f}%"
    if label == "Ranking típico (365 dias)":
        return f"~#{int(round(number))}"
    return f"{number:.1f}"


def _family_detail_html(
    family: Mapping[str, Any], players: Mapping[str, Mapping[str, Any]],
) -> str:
    trace = family.get("internal_trace") or {}
    features = trace.get("features") or []
    if not features:
        return '<p class="family-detail-empty">Sem decomposição adicional disponível.</p>'
    active_totals = []
    for feature in features:
        if feature.get("missing"):
            continue
        total = (
            (_number(feature.get("logit_contribution")) or 0.0)
            + (_number(feature.get("missing_logit_contribution")) or 0.0)
        )
        active_totals.append(abs(total))
    absolute_total = sum(active_totals)
    rows = []
    for feature in features:
        missing = bool(feature.get("missing"))
        contribution = _number(feature.get("logit_contribution")) or 0.0
        missing_contribution = _number(
            feature.get("missing_logit_contribution")
        ) or 0.0
        total = contribution + missing_contribution
        side = "A" if total > 1e-9 else "B" if total < -1e-9 else "—"
        direction = side.casefold() if side != "—" else "neutral"
        if missing:
            result = "Sem dados · sem leitura factual"
            strength = ""
            width = 0.0
            direction = "missing"
        elif side == "—":
            result = "Sem vantagem material"
            strength = "sem impacto material"
            width = 0.0
        else:
            player = players[side.casefold()]
            share = abs(total) / absolute_total if absolute_total else 0.0
            result = f"Favorece {player['name']}"
            strength = _factor_strength_label(share)
            width = min(100.0, 100.0 * share)
        rows.append(
            f'<div class="factor-row factor-{direction}">'
            f'<span class="factor-name">{_e(_feature_label(feature.get("key")))}</span>'
            f'<div class="factor-visual"><span class="factor-fill" style="--factor-width:{width:.1f}%"></span></div>'
            f'<b>{_e(result)}</b><small>{_e(strength)}</small></div>'
        )
    context = family.get("context_audit") or {}
    components = context.get("components") or {}
    structural = ""
    if components:
        fields = [
            ("Ranking atual", "current_rank_a", "current_rank_b"),
            ("Pontos atuais", "current_points_a", "current_points_b"),
            ("Melhor ranking observado", "observed_peak_rank_a", "observed_peak_rank_b"),
            ("Ranking típico (365 dias)", "typical_rank_365d_a", "typical_rank_365d_b"),
            ("Representatividade do ranking atual", "representativeness_a", "representativeness_b"),
        ]
        return_active = bool(components.get("return_contraction_active"))
        if return_active:
            fields.extend([
                ("Nível típico antes do hiato", "pre_layoff_typical_rank_a", "pre_layoff_typical_rank_b"),
                ("Jogos desde o regresso", "matches_since_return_a", "matches_since_return_b"),
            ])
        items = []
        for label, key_a, key_b in fields:
            if key_a in components or key_b in components:
                items.append(
                    f'<div><span>{_e(label)}</span><b>'
                    f'{_e(players["a"]["name"])} {_e(_context_value(label, components.get(key_a)))} · '
                    f'{_e(players["b"]["name"])} {_e(_context_value(label, components.get(key_b)))}</b></div>'
                )
        if items:
            structural = f'<div class="context-grid">{"".join(items)}</div>'
    if family.get("key") == "matchup_h2h" and context:
        h2h_items = (
            ("H2H factual encontrado", context.get("raw_matches")),
            ("H2H competitivo usado", context.get("eligible_matches")),
            ("No piso atual", context.get("eligible_surface_matches")),
            ("Exibições excluídas do cálculo", context.get("excluded_non_competitive")),
        )
        structural += '<div class="context-grid">' + ''.join(
            f'<div><span>{_e(label)}</span><b>{_e(value)}</b></div>'
            for label, value in h2h_items if value is not None
        ) + '</div>'
    return f'<div class="factor-table">{"".join(rows)}</div>{structural}'


def _player_card(side: str, player: Mapping[str, Any]) -> str:
    interval = player["interval"]
    fair = player["fair_odd"]
    market = player["market"]
    edge = market.get("probability_edge_pp")
    edge_class = "positive" if edge is not None and edge > 0 else "negative"
    history = player.get("moneyline_history") or {}
    general = history.get("general") or {}
    band = history.get("current_band") or {}
    general_text = (
        f"{_e(general.get('win_rate_pct'))}% · "
        f"{_e(general.get('wins'))}/{_e(general.get('sample'))}"
        if general.get("sample") else "N/D · sem amostra histórica com odds"
    )
    band_text = (
        f"{_e(band.get('win_rate_pct'))}% · "
        f"{_e(band.get('wins'))}/{_e(band.get('sample'))}"
        if band.get("sample") else "N/D · amostra inexistente nesta faixa"
    )
    observed_odd = _number(market.get("odd"))
    break_even = 100.0 / observed_odd if observed_odd else None
    band_margin = (
        _number(band.get("win_rate_pct")) - break_even
        if _number(band.get("win_rate_pct")) is not None and break_even is not None
        else None
    )
    return f"""
      <article class="player-card side-{side}">
        <div class="player-side">MODELO {side.upper()}</div>
        <h2>{_e(player['name'])}</h2>
        <div class="probability">{_pct(player['probability'])}</div>
        <div class="interval">Intervalo 90% · {_pct(interval[0])}–{_pct(interval[1])}</div>
        <div class="player-grid">
          <div><span>Fair odd</span><strong>{_odd(fair['central'])}</strong></div>
          <div><span>Faixa justa</span><strong>{_odd(fair['lower'])}–{_odd(fair['upper'])}</strong></div>
          <div><span>Odd observada</span><strong>{_odd(market.get('odd'))}</strong></div>
          <div class="{edge_class}"><span>Diferença vs prob. de-vig</span><strong>{_signed(edge, ' p.p.')}</strong></div>
        </div>
        <div class="ev-row">
          <span>EV central <b>{_signed(market.get('expected_value_pct'), '%')}</b></span>
          <span>EV no limite conservador <b>{_signed(market.get('conservative_expected_value_pct'), '%')}</b></span>
        </div>
        <div class="ml-history">
          <div><span>WIN RATE MONEYLINE · {_e(history.get('format'))}</span><b>{general_text}</b><small>Histórico geral com odds observadas</small></div>
          <div><span>HISTÓRICO NESTA FAIXA DE ODD · {_e(history.get('current_band_label'))}</span><b>{band_text}</b><small>Dado descritivo · break-even {_e(None if break_even is None else round(break_even, 1))}% · margem {_signed(band_margin, ' p.p.')}</small></div>
        </div>
      </article>"""


def _market_review_html(view: Mapping[str, Any]) -> str:
    review = view.get("market_review") or {}
    status = review.get("status")
    if status == "MARKET_UNAVAILABLE":
        body = (
            '<div class="review-empty"><b>Mercado ainda indisponível.</b> '
            "A previsão permanece guardada; não é formulado qualquer mercado."
            "</div>"
        )
    elif status == "FAVORITE_UNCONFIRMED":
        body = (
            '<div class="review-empty"><b>Mercados não formulados.</b> '
            "O lado favorito muda quando se retira uma única família. A estimativa central permanece visível para auditoria, mas não é robusta o suficiente para gerar uma seleção Moneyline ou handicap.</div>"
        )
    elif status == "NO_POSITIVE_EDGE" and not isinstance(review.get("handicap"), Mapping):
        body = (
            '<div class="review-empty"><b>Sem edge central positivo.</b> '
            "O relatório mantém a leitura factual, mas não destaca um mercado."
            "</div>"
        )
    else:
        side = str(review.get("candidate_side") or "")
        player = (view.get("players") or {}).get(side) or {}
        confidence = (
            "Edge também positivo no limite conservador"
            if status == "CONSERVATIVE_POSITIVE"
            else "Edge positivo apenas na estimativa central"
        )
        cards = []
        moneyline = review.get("moneyline")
        if isinstance(moneyline, Mapping):
            minimum = moneyline.get("minimum_odd")
            zone = (
                f"{float(minimum):.2f}–{float(moneyline['maximum_odd']):.2f}"
                if minimum is not None else "Fora da janela operacional"
            )
            cards.append(f"""
              <article class="review-card moneyline-card">
                <div class="review-type">MONEYLINE</div>
                <h3>{_e(player.get('name'))}</h3>
                <div class="review-big">{_odd(moneyline.get('observed_odd'))}</div>
                <p>Odd observada · fair odd {_odd(moneyline.get('fair_odd'))}</p>
                <div class="price-zone"><span>FAIXA PARA CONSIDERAR</span><b>{_e(zone)}</b></div>
              </article>""")
        handicap = review.get("handicap")
        if isinstance(handicap, Mapping):
            handicap_side = str(handicap.get("side") or side)
            handicap_player = (view.get("players") or {}).get(handicap_side) or {}
            positive = handicap.get("type") == "positive"
            # Preserve the five lines selected by the model, then display them
            # in natural handicap order rather than internal priority order.
            visible_lines = list((handicap.get("lines") or [])[:5])
            visible_lines.sort(
                key=lambda item: abs(float(item.get("line") or 0.0))
            )
            visible_cards = []
            for line in visible_lines:
                price = line.get("price") or {}
                if price.get("status") != "READY":
                    zone = "Sem preço validado · amostra relevante curta"
                elif price.get("minimum_odd") is None:
                    zone = (
                        f"Fair {_odd(price.get('fair_odd'))} · acima da janela"
                    )
                else:
                    zone = (
                        f"{float(price['minimum_odd']):.2f}–"
                        f"{float(price['maximum_odd']):.2f}"
                    )
                if positive:
                    primary = f"{_e(line.get('cover_pct'))}% cobre no total"
                    secondary = (
                        f"Quando vence: {_e(line.get('win_cover_pct'))}% "
                        f"({_e(line.get('win_cover'))}/{_e(line.get('win_total'))})"
                    )
                else:
                    primary = f"{_e(line.get('win_cover_pct'))}% cobre quando vence"
                    secondary = (
                        f"Total: {_e(line.get('cover_pct'))}% "
                        f"({_e(line.get('cover'))}/{_e(line.get('total'))})"
                    )
                losses = (
                    f"Nas derrotas: {_e(line.get('loss_cover_pct'))}% "
                    f"({_e(line.get('loss_cover'))}/{_e(line.get('loss_total'))})"
                    if line.get("loss_total") else "Nas derrotas: sem amostra"
                )
                push_copy = (
                    f"Push: {_e(line.get('push'))} em "
                    f"{_e(line.get('total'))} jogos"
                    if line.get("push") else ""
                )
                line_card = f"""
                  <div class="line-card">
                    <div class="line-name">{_e(line.get('line'))}</div>
                    <strong>{primary}</strong><small>{secondary}</small>
                    <small>{losses}</small>{f'<small>{push_copy}</small>' if push_copy else ''}<small>Amostra total: {_e(line.get('total'))} jogos</small>
                    <div class="line-zone"><span>ODD PARA CONSIDERAR</span><b>{_e(zone)}</b></div>
                  </div>"""
                visible_cards.append(line_card)
            cards.append(f"""
              <article class="review-card handicap-card">
                <div class="review-type">HANDICAPS DE {_e(handicap_player.get('name')).upper()} · {'POSITIVOS' if positive else 'NEGATIVOS'} · {_e(handicap.get('format'))}</div>
                <p class="line-intro">Linhas principais para leitura imediata. Cobertura total, em vitórias e em derrotas usam apenas evidência congelada antes do jogo.</p>
                <div class="line-grid">{''.join(visible_cards)}</div>
              </article>""")
        if not cards:
            cards.append(
                '<div class="review-empty">Edge identificado, mas a odd não '
                "está na janela Moneyline e não existe evidência de handicap "
                "congelada para esta observação.</div>"
            )
        lead = (
            f'<div><b>Valor Moneyline: {_e(player.get("name"))}</b><span>{_e(confidence)}</span></div>'
            f'<div><strong>{_signed(review.get("central_ev_pct"), "%")}</strong><span>EV central</span></div>'
            f'<div><strong>{_signed(review.get("conservative_ev_pct"), "%")}</strong><span>EV conservador</span></div>'
            if side else
            '<div class="review-no-ml"><b>Sem edge Moneyline positivo</b><span>Os handicaps abaixo pertencem ao lado indicado pelo modelo.</span></div>'
        )
        body = f"""
          <div class="review-lead">{lead}</div>
          <div class="review-grid">{''.join(cards)}</div>"""
    return f"""
      <section class="section market-review">
        <div class="section-head"><div><div class="eyebrow">VALIDAÇÃO HUMANA</div>
          <h2>Mercados a consultar</h2></div><div class="shadow-badge">SEM ENTRADA AUTOMÁTICA</div></div>
        {body}
        <div class="market-note">A Moneyline usa a fair odd independente. Cada handicap tem probabilidade própria calculada com a cobertura condicional congelada antes do jogo. A odd da linha deve ser confirmada na casa de apostas.</div>
      </section>"""


def render_report_html(view: Mapping[str, Any]) -> str:
    """Render a standalone, responsive preview with no operational actions."""
    release_label = (
        view.get("global_release_id") or "CONTEXTUAL V2"
    )
    players = view["players"]
    families = []
    for family in view["families"]:
        contribution = float(family["impact_pp_model_a"])
        width = min(100.0, float(family["relative_contribution_pct"]))
        direction = family["direction"]
        advantage = family.get("direction_name") or "Sem vantagem material"
        intensity = {
            "forte": "forte",
            "moderado": "moderada",
            "ligeiro": "ligeira",
            "neutro": "neutra",
        }.get(
            str(family.get("impact_intensity_label") or "").casefold(),
            str(family.get("impact_intensity_label") or "N/D"),
        )
        families.append(f"""
          <div class="family-row grade-{_e(family['coverage_grade']).lower()}">
            <div class="family-copy">
              <strong>{_e(family['label'])}</strong>
              <small>{_e(family['coverage_grade_label'])}</small>
            </div>
            <div class="family-scale" aria-label="Contributo relativo da família">
              <span class="axis"></span>
              <span class="bar {direction}" style="--strength:{width:.2f}%"></span>
            </div>
            <div class="family-result {direction}">
              {_e(advantage)}
              <small>vantagem {_e(intensity)}</small>
            </div>
          </div>
          <details class="family-detail"><summary>Ver o que entrou nesta família</summary>
            {_family_detail_html(family, players)}
          </details>""")
    market = view["market"]
    if market["available"]:
        market_copy = (
            f"Cotação mais recente desta execução · {_e(market['bookmaker'])} · "
            f"{_e(market['source'])} · {_e(market['captured_at'])}"
        )
        previous_quote = market.get("previous_quote") or {}
        previous_odds = previous_quote.get("odds") or {}
        if previous_odds:
            movement = []
            for side in ("a", "b"):
                old = _number(previous_odds.get(side))
                current = _number((players[side].get("market") or {}).get("odd"))
                if old is not None and current is not None:
                    movement.append(
                        f"{players[side]['name']}: {old:.2f} → {current:.2f}"
                    )
            if movement:
                market_copy += " · Movimento desde a leitura anterior: " + " | ".join(movement)
        benchmark_badge = "ODD DE MERCADO CAPTURADA"
        benchmark_meta = f"{_e(market['bookmaker'])} · {_e(market['captured_at'])}"
    else:
        market_copy = "Cotação pós-previsão ainda indisponível. A previsão mantém-se válida e imutável."
        benchmark_badge = "MERCADO N/D"
        benchmark_meta = "Sem cotação válida nesta execução"
    plausibility = market.get("plausibility") or {}
    plausibility_html = ""
    if plausibility.get("requires_manual_review"):
        market_side = plausibility.get("market_side")
        market_name = players.get(str(market_side), {}).get("name")
        plausibility_html = f"""
        <div class="plausibility-alert"><b>REVISÃO DE PLAUSIBILIDADE</b>
          <span>O mercado está fora do intervalo de 90% do modelo e favorece
          mais {_e(market_name)} em {_e(plausibility.get('distance_pp'))} p.p.
          Esta divergência não altera a fair odd, mas exige rever identidade,
          dados em falta e calibração antes de qualquer decisão.</span></div>"""
    coverage = view.get("family_coverage") or {}
    solid = coverage.get("solid", coverage.get("observed", 0))
    partial = coverage.get("partial", 0)
    neutral = coverage.get("observed_neutral", 0)
    unavailable = coverage.get("unavailable", 0)
    usable = coverage.get("usable", solid + partial)
    measured = coverage.get("measured", usable + neutral)
    total = coverage.get("total", 5)
    coverage_pct = coverage.get("pct", 0)
    preferred = max(players, key=lambda side: players[side]["probability"])
    preferred_name = players[preferred]["name"]
    sensitivity = view.get("family_sensitivity") or {}
    dependency_grade = sensitivity.get("dependency_grade") or "ROBUST"
    lead_authority = sensitivity.get("lead_authority") or {}
    authorised_lead = bool(lead_authority.get("authorised"))
    favorite_confirmed = dependency_grade == "ROBUST"
    dominant_family = sensitivity.get("dominant_family_if_unstable")
    family_labels = {
        str(item.get("key")): str(item.get("label") or item.get("key"))
        for item in view.get("families") or []
    }
    if dependency_grade == "CRITICAL_DEPENDENCE":
        direct_read = (
            f"Estimativa central: {preferred_name} {_pct(players[preferred]['probability'])}. "
            f"Favoritismo não confirmado: ao retirar {family_labels.get(str(dominant_family), dominant_family)}, "
            "o lado favorito muda de forma crítica. Não formular decisão operacional."
        )
    elif authorised_lead:
        direct_read = (
            f"Estimativa central: {preferred_name} {_pct(players[preferred]['probability'])}. "
            f"A direção é liderada por {family_labels.get(str(dominant_family), dominant_family)}, "
            "uma família principal com evidência sólida e componentes internos coerentes."
        )
    elif dependency_grade in {"BALANCED_SENSITIVE", "MATERIAL_DEPENDENCE"}:
        direct_read = (
            f"Estimativa central: {preferred_name} {_pct(players[preferred]['probability'])}. "
            f"Leitura {_e('sensível em jogo equilibrado' if dependency_grade == 'BALANCED_SENSITIVE' else 'com dependência material')}: "
            f"{family_labels.get(str(dominant_family), dominant_family)} pode mudar o lado, mas a previsão permanece visível com incerteza reforçada."
        )
    elif view["model_status"] == "READY_FOR_PROSPECTIVE_SHADOW":
        direct_read = (
            f"O modelo inclina-se para {preferred_name}, mantendo a incerteza "
            "explicitamente visível. A comparação de mercado é posterior e não altera esta leitura."
        )
    else:
        direct_read = (
            "A previsão foi preservada, mas a qualidade disponível ainda não permite "
            "tratá-la como operacionalmente pronta."
        )
    title = f"{players['a']['name']} vs {players['b']['name']}"
    robustness_class = "confirmed" if favorite_confirmed else "unstable"
    robustness_title = {
        "ROBUST": "LEITURA ESTÁVEL",
        "BALANCED_SENSITIVE": "JOGO EQUILIBRADO · LEITURA SENSÍVEL",
        "MATERIAL_DEPENDENCE": "DEPENDÊNCIA MATERIAL DE UMA FAMÍLIA",
        "CRITICAL_DEPENDENCE": "DEPENDÊNCIA CRÍTICA · BLOQUEADO",
    }.get(dependency_grade, "ROBUSTEZ N/D")
    if authorised_lead:
        robustness_title = (
            "LIDERANÇA PRINCIPAL VÁLIDA · "
            + family_labels.get(str(dominant_family), str(dominant_family)).upper()
        )
    robustness_copy = {
        "ROBUST": "Nenhuma família isolada muda o lado favorito.",
        "BALANCED_SENSITIVE": "Uma família muda o lado apenas dentro de uma zona próxima de 50/50.",
        "MATERIAL_DEPENDENCE": "Uma família tem influência material; a faixa de fair odd incorpora essa sensibilidade.",
        "CRITICAL_DEPENDENCE": "Uma família isolada sustenta uma vantagem forte; o jogo fica bloqueado para decisão.",
    }.get(dependency_grade, "Robustez não classificada.")
    if authorised_lead:
        robustness_copy = (
            "A retirada desta família muda o lado favorito, mas a liderança é "
            "aceite porque a evidência é sólida e não depende de um único componente."
        )
    direction_counts = {
        "a": sum(1 for item in view["families"] if item.get("direction") == "a"),
        "b": sum(1 for item in view["families"] if item.get("direction") == "b"),
        "neutral": sum(
            1 for item in view["families"] if item.get("direction") == "neutral"
        ),
    }
    favorite_margin = abs(float(players[preferred]["probability"]) - 0.5)
    global_intensity = (
        "forte" if favorite_margin >= 0.12
        else "moderada" if favorite_margin >= 0.07
        else "ligeira" if favorite_margin >= 0.03
        else "equilibrada"
    )
    preferred_fair = players[preferred]["fair_odd"]
    market_review = view.get("market_review") or {}
    value_side = market_review.get("candidate_side")
    if value_side in {"a", "b"}:
        conservative_value = _number(market_review.get("conservative_ev_pct"))
        value_measure = (
            f"EV conservador {_signed(conservative_value, '%')}"
            if conservative_value is not None and conservative_value > 0
            else f"apenas EV central {_signed(market_review.get('central_ev_pct'), '%')}"
        )
        value_copy = f"{players[value_side]['name']} · {value_measure}"
    else:
        value_copy = "Sem valor Moneyline confirmado"
    sensitivity_rows = sensitivity.get("scenarios") or []
    sensitive_row = min(
        (
            item for item in sensitivity_rows
            if _number(item.get("probability_model_a_without_family")) is not None
        ),
        key=lambda item: abs(
            float(item["probability_model_a_without_family"]) - 0.5
        ),
        default=None,
    )
    sensitive_copy = robustness_copy
    if favorite_confirmed and sensitive_row:
        family_name = family_labels.get(
            str(sensitive_row.get("family")), str(sensitive_row.get("family"))
        )
        remaining_probability_a = float(
            sensitive_row["probability_model_a_without_family"]
        )
        remaining_probability = (
            remaining_probability_a if preferred == "a"
            else 1.0 - remaining_probability_a
        )
        if remaining_probability < 0.53:
            robustness_class = "unstable"
            robustness_title = "LADO MANTIDO · MARGEM FRÁGIL"
            sensitive_copy = (
                f"Teste de robustez: ao retirar apenas {family_name}, "
                f"{preferred_name} continua à frente, mas por margem curta "
                f"({_pct(remaining_probability)})."
            )
        else:
            sensitive_copy = (
                f"Teste de robustez: ao retirar apenas {family_name}, "
                f"{preferred_name} continua à frente "
                f"({_pct(remaining_probability)})."
            )
    consensus_items = []
    for side in ("a", "b"):
        if direction_counts[side]:
            consensus_items.append(
                f'<div class="consensus-side side-{side}"><strong>{direction_counts[side]}</strong>'
                f'<span>família(s) favorecem<br>{_e(players[side]["name"])}</span></div>'
            )
    if direction_counts["neutral"]:
        consensus_items.append(
            f'<div class="consensus-side neutral"><strong>{direction_counts["neutral"]}</strong>'
            '<span>família(s)<br>neutras</span></div>'
        )
    def hero_player(side: str) -> str:
        player = players[side]
        image = player.get("image_url")
        initials = "".join(
            part[:1] for part in str(player.get("name") or "?").split()[:2]
        ).upper()
        portrait = (
            f'<img src="{_e(image)}" alt="{_e(player.get("name"))}">'
            if image else f'<span>{_e(initials)}</span>'
        )
        odd = _odd((player.get("market") or {}).get("odd"))
        fair = _odd((player.get("fair_odd") or {}).get("central"))
        central_ev = _number((player.get("market") or {}).get("expected_value_pct"))
        conservative_ev = _number(
            (player.get("market") or {}).get("conservative_expected_value_pct")
        )
        value_label = (
            "VALOR CONSERVADOR"
            if conservative_ev is not None and conservative_ev > 0
            else "VALOR CENTRAL"
            if central_ev is not None and central_ev > 0
            else "SEM EDGE POSITIVO"
        )
        return f'''<div class="hero-player side-{side}"><div class="portrait">{portrait}</div>
          <div><h1>{_e(player['name'])}</h1><b>{_pct(player['probability'])} Fenzobot</b>
          <small>Fair {fair} · Mercado {odd}</small><em>{value_label}</em></div></div>'''
    return f"""<!doctype html>
<html lang="pt-PT">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{_e(title)} · {_e(release_label)}</title>
  <style>
    :root{{--ink:#eef7ff;--muted:#8ba9c4;--panel:#0c2035;--panel2:#102a45;--line:#244866;
      --cyan:#43d9d0;--blue:#55a7ff;--orange:#ff9b55;--red:#ff6475;--navy:#061522;--gold:#ffc857}}
    *{{box-sizing:border-box}} body{{margin:0;background:radial-gradient(circle at 15% 0,#113354 0,#061522 42%);
      color:var(--ink);font:15px/1.45 Inter,Segoe UI,Arial,sans-serif}}
    .shell{{max-width:1180px;margin:auto;padding:28px 18px 70px}} .topline{{display:flex;gap:12px;align-items:center;
      justify-content:space-between;margin-bottom:18px}} .brand{{font-weight:900;letter-spacing:.16em;color:var(--cyan)}}
    .shadow-badge,.market-badge{{border:1px solid var(--gold);color:var(--gold);border-radius:14px;padding:7px 11px;
      font-size:11px;font-weight:800;letter-spacing:.09em}} .hero,.section{{background:linear-gradient(145deg,rgba(16,42,69,.96),rgba(8,27,45,.96));
      border:1px solid var(--line);border-radius:22px;box-shadow:0 18px 50px #0005}}
    .hero{{padding:26px}} .context{{text-align:center;color:var(--muted);text-transform:uppercase;letter-spacing:.09em;font-size:12px}}
    .versus{{display:grid;grid-template-columns:1fr auto 1fr;gap:18px;align-items:center;margin-top:8px}}
    .versus h1{{font-size:clamp(23px,4vw,40px);line-height:1.05;margin:8px 0}} .versus .right{{text-align:right}}
    .hero-player{{display:flex;gap:15px;align-items:center}}.hero-player.side-b{{flex-direction:row-reverse;text-align:right}}
    .hero-player small,.hero-player b{{display:block}}.hero-player small{{color:var(--muted)}}
    .hero-player em{{display:inline-block;margin-top:5px;padding:4px 7px;border-radius:999px;background:#173956;color:var(--cyan);font-size:9px;font-style:normal;font-weight:900;letter-spacing:.06em}}
    .portrait{{width:76px;height:76px;flex:0 0 76px;border-radius:50%;overflow:hidden;border:3px solid var(--blue);display:grid;place-items:center;background:#173956;font-weight:900;font-size:22px}}
    .side-b .portrait{{border-color:var(--orange)}}.portrait img{{width:100%;height:100%;object-fit:cover}}
    .vs{{color:var(--muted);font-weight:900;font-size:20px}} .summary{{margin:18px 0 0;border-top:1px solid var(--line);
      padding-top:17px;display:flex;gap:14px;justify-content:space-between;align-items:center}}
    .summary strong{{font-size:18px}} .summary span{{color:var(--muted)}} .section{{margin-top:18px;padding:24px}}
    .section-head{{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:18px}}
    .eyebrow{{color:var(--cyan);font-weight:900;letter-spacing:.12em;font-size:12px}} h2,h3,p{{margin-top:0}}
    .pricing-grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}} .player-card{{border:1px solid var(--line);
      border-top:4px solid var(--blue);border-radius:16px;padding:20px;background:#0b2137}} .player-card.side-b{{border-top-color:var(--orange)}}
    .player-side{{font-size:10px;letter-spacing:.14em;color:var(--muted);font-weight:900}} .player-card h2{{margin:6px 0}}
    .probability{{font-size:42px;font-weight:950;letter-spacing:-.04em}} .interval{{color:var(--muted);margin-bottom:18px}}
    .player-grid{{display:grid;grid-template-columns:1fr 1fr;gap:8px}} .player-grid div{{padding:12px;background:#132f4d;border-radius:10px}}
    .player-grid span,.ev-row span{{display:block;color:var(--muted);font-size:11px}} .player-grid strong{{font-size:18px}}
    .positive strong{{color:var(--cyan)}} .negative strong{{color:#b8c9d8}} .ev-row{{display:flex;gap:18px;margin-top:12px}}
    .ml-history{{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:14px}}.ml-history>div{{padding:12px;background:#091b2c;border-radius:10px}}
    .ml-history span,.ml-history small{{display:block;color:var(--muted);font-size:10px}}.ml-history b{{display:block;margin:3px 0;font-size:16px}}
    .market-badge small{{display:block;color:var(--muted);font-size:9px;letter-spacing:0;margin-top:2px}}
    .decision-strip{{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-top:15px}}.decision-strip>div{{padding:12px 14px;border-radius:12px;background:#102a45;border:1px solid var(--line)}}
    .decision-strip span,.decision-strip b{{display:block}}.decision-strip span{{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.08em}}.decision-strip b{{font-size:16px;margin-top:3px}}
    .robustness{{margin-top:9px;padding:10px 13px;border-radius:10px;border:1px solid var(--cyan);background:#0a2b35;font-size:12px}}
    .robustness.unstable{{border-color:var(--gold);background:#322914}}.robustness b{{display:block;letter-spacing:.08em}}.robustness span{{color:#c8d8e7}}
    .consensus{{display:grid;grid-template-columns:minmax(220px,1.4fr) repeat(3,minmax(130px,1fr));gap:9px;margin-top:13px}}
    .consensus-summary,.consensus-side{{padding:12px 14px;border-radius:12px;background:#102a45;border:1px solid var(--line)}}
    .consensus-summary b,.consensus-summary span,.consensus-side strong,.consensus-side span{{display:block}}
    .consensus-summary span,.consensus-side span{{color:var(--muted);font-size:11px}}.consensus-side strong{{font-size:24px}}
    .consensus-side.side-a{{border-color:var(--blue)}}.consensus-side.side-b{{border-color:var(--orange)}}
    .market-note{{margin-top:14px;padding:13px 15px;border-left:3px solid var(--gold);background:#152a3d;color:#c8d8e7}}
    .plausibility-alert{{margin-top:14px;padding:15px 18px;border:1px solid var(--red);border-radius:12px;background:#361c2a}}
    .plausibility-alert b,.plausibility-alert span{{display:block}}.plausibility-alert b{{color:#ff9aa6;letter-spacing:.08em}}
    .review-lead{{display:grid;grid-template-columns:2fr 1fr 1fr;gap:10px;margin-bottom:14px}}.review-lead>div{{padding:14px;background:#132f4d;border-radius:11px}}
    .review-lead .review-no-ml{{grid-column:1/-1}}
    .review-lead b,.review-lead strong{{display:block;font-size:21px}}.review-lead span{{color:var(--muted);font-size:11px}}
    .review-grid{{display:grid;grid-template-columns:minmax(250px,.8fr) minmax(0,2fr);gap:14px}}.review-card{{background:#0b2137;border:1px solid var(--line);border-radius:16px;padding:18px}}
    .handicap-card{{grid-column:1/-1}}
    .review-type{{color:var(--cyan);font-size:10px;font-weight:900;letter-spacing:.12em}}.review-big{{font-size:38px;font-weight:950}}
    .review-card p,.line-card small{{color:var(--muted)}}.price-zone,.line-zone{{margin-top:12px;padding:10px;background:#132f4d;border-radius:9px}}
    .price-zone span,.line-zone span{{display:block;color:var(--muted);font-size:9px;letter-spacing:.08em}}.price-zone b,.line-zone b{{font-size:16px}}
    .line-grid{{display:grid;grid-template-columns:repeat(4,minmax(175px,1fr));gap:9px;margin-top:12px}}.line-card{{padding:13px;background:#102a45;border:1px solid #285171;border-radius:11px}}
    .line-card strong,.line-card small{{display:block}}.line-card strong{{font-size:17px;line-height:1.2}}.line-name{{font-weight:950;font-size:23px;margin-bottom:7px;color:var(--cyan)}}.line-intro{{color:var(--muted);margin:8px 0 0}}
    .all-lines{{margin-top:14px}}.all-lines summary,.family-detail summary{{color:var(--cyan);font-weight:800}}.full-lines{{grid-template-columns:repeat(4,minmax(0,1fr))}}
    .review-empty{{padding:20px;border:1px dashed #54718a;border-radius:14px;color:var(--muted)}}
    .quality{{display:grid;grid-template-columns:160px 1fr;gap:20px;align-items:center}} .ring{{width:140px;height:140px;border-radius:50%;
      display:grid;place-content:center;text-align:center;background:conic-gradient(var(--cyan) {float(coverage_pct):.1f}%,#16334d 0);
      position:relative}} .ring:after{{content:"";position:absolute;inset:12px;border-radius:50%;background:#0b2137}}
    .ring strong,.ring small{{position:relative;z-index:1}} .ring strong{{font-size:30px}} .quality-copy p{{color:var(--muted)}}
    .family-row{{display:grid;grid-template-columns:minmax(210px,1fr) minmax(240px,2fr) 88px;gap:16px;align-items:center;
      padding:14px 0;border-bottom:1px solid #1b3a55}} .family-row:last-child{{border-bottom:0}} .family-copy small,
    .family-result small{{display:block;color:var(--muted);font-size:11px}} .family-scale{{height:18px;position:relative;background:#091b2c;border-radius:9px}}
    .axis{{position:absolute;left:50%;top:0;bottom:0;width:1px;background:#66829b}} .bar{{position:absolute;top:4px;height:10px;width:calc(var(--strength)/2);border-radius:6px}}
    .bar.a{{right:50%;background:var(--blue)}} .bar.b{{left:50%;background:var(--orange)}} .bar.neutral{{left:50%;width:2px;background:#66829b}}
    .grade-partial .bar{{background-image:repeating-linear-gradient(45deg,#ffffff22 0 4px,transparent 4px 8px)}}
    .grade-unavailable{{opacity:.55}} .grade-observed_neutral .family-scale{{opacity:.6}}
    .family-result{{text-align:right;font-weight:900}} .family-result.a{{color:var(--blue)}} .family-result.b{{color:var(--orange)}}
    .family-detail{{margin:0 0 8px;padding:10px 0 13px;border-top:0;border-bottom:1px solid #1b3a55}}.factor-table{{display:grid;gap:6px;margin-top:10px}}
    .factor-row{{display:grid;grid-template-columns:minmax(210px,1.4fr) minmax(150px,1fr) minmax(180px,1fr) 130px;gap:12px;padding:10px;background:#091b2c;border-radius:8px;align-items:center}}
    .factor-row b{{font-size:12px}}.factor-row small{{color:var(--muted);font-size:10px}}.factor-visual{{height:9px;border-radius:8px;background:#173956;overflow:hidden}}
    .factor-fill{{display:block;height:100%;width:var(--factor-width);background:var(--blue);border-radius:8px}}.factor-b .factor-fill{{background:var(--orange)}}
    .factor-a b{{color:var(--blue)}}.factor-b b{{color:var(--orange)}}.factor-missing{{opacity:.62}}
    .context-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:7px;margin-top:9px}}.context-grid div{{padding:9px;background:#132f4d;border-radius:8px}}
    .context-grid span,.context-grid b{{display:block;font-size:11px}}.context-grid span{{color:var(--muted)}}.family-detail-empty{{color:var(--muted)}}
    details{{margin-top:18px;border-top:1px solid var(--line);padding-top:14px}} summary{{cursor:pointer;color:var(--muted)}}
    .foot{{color:var(--muted);text-align:center;margin-top:18px;font-size:12px}}
    @media(max-width:980px){{.line-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}.review-grid{{grid-template-columns:1fr}}
      .handicap-card{{grid-column:auto}}.factor-row{{grid-template-columns:minmax(180px,1.3fr) minmax(130px,1fr) minmax(150px,1fr)}}.factor-row>:last-child{{grid-column:2/-1}}}}
    @media(max-width:760px){{.pricing-grid{{grid-template-columns:1fr}}.quality{{grid-template-columns:1fr}}.ring{{margin:auto}}
      .family-row{{grid-template-columns:1fr}}.family-result{{text-align:left}}.versus{{grid-template-columns:1fr;text-align:center}}
      .versus .right{{text-align:center}}.hero-player,.hero-player.side-b{{flex-direction:column;text-align:center}}.vs{{display:none}}.summary{{display:block}}.player-grid{{grid-template-columns:1fr}}
      .consensus,.decision-strip,.review-lead,.review-grid,.line-grid,.ml-history,.context-grid,.factor-row{{grid-template-columns:1fr}}}}
  </style>
</head>
<body><main class="shell">
  <div class="topline"><div class="brand">FENZOBOT · {_e(release_label)}</div><div class="shadow-badge">SHADOW · SEM DECISÃO</div></div>
  <section class="hero">
    <div class="context">{_e(view['tour'])} · {_e(view['tier'])} · {_e(view['tournament_name'])} · {_e(view['round_stage'])} · {_e(view['surface_context'])} · {_e(view['commence_time'])}</div>
    <div class="versus">{hero_player('a')}<div class="vs">VS</div>{hero_player('b')}</div>
    <div class="summary"><div><strong>LEITURA DIRETA</strong><br><span>{_e(direct_read)}</span></div>
      <div class="market-badge">{benchmark_badge}<small>{benchmark_meta}</small></div></div>
    <div class="decision-strip">
      <div><span>Favorito do modelo</span><b>{_e(preferred_name)} · {_pct(players[preferred]['probability'])}</b></div>
      <div><span>Faixa justa do favorito</span><b>{_odd(preferred_fair['lower'])}–{_odd(preferred_fair['upper'])}</b></div>
      <div><span>Valor Moneyline</span><b>{_e(value_copy)}</b></div>
    </div>
    <div class="robustness {robustness_class}"><b>{robustness_title}</b><span>{_e(sensitive_copy)}</span></div>
    <div class="consensus"><div class="consensus-summary"><b>Vantagem global {_e(global_intensity)}</b>
      <span>A direção conta; a intensidade de cada família determina quanto pesa.</span></div>{''.join(consensus_items)}</div>
  </section>
  <section class="section">
    <div class="section-head"><div><div class="eyebrow">NÚCLEO DE PRICING</div><h2>Probabilidade e fair odd independentes</h2></div></div>
    <div class="pricing-grid">{_player_card('a', players['a'])}{_player_card('b', players['b'])}</div>
    <div class="market-note"><b>Mercado observado apenas depois da previsão.</b> {_e(market_copy)}</div>
    {plausibility_html}
  </section>
  {_market_review_html(view)}
  <section class="section">
    <div class="section-head"><div><div class="eyebrow">QUALIDADE DA EVIDÊNCIA</div><h2>O que foi realmente medido</h2></div></div>
    <div class="quality"><div class="ring"><strong>{float(coverage_pct):.0f}%</strong><small>{measured}/{total} avaliadas</small></div>
      <div class="quality-copy"><h3>{_e(view['quality_label'])}</h3><p>{_e(view['model_status_label'])}</p>
      <p><b>{solid} sólida(s)</b> · <b>{partial} parcial(is)</b> · {neutral} consultada(s) sem ocorrência · {unavailable} indisponível(is). Uma consulta sem ocorrência conta como cobertura, mas vale zero no índice.</p>
      <p>Bin histórico de calibração: <b>{_e(view['calibration_bin_sample'])} casos</b>. Evidência parcial alarga a incerteza; dados em falta nunca são tratados como empate.</p></div></div>
  </section>
  <section class="section">
    <div class="section-head"><div><div class="eyebrow">MAPA DAS FAMÍLIAS</div><h2>Direção e contributo para a previsão</h2></div></div>
    {''.join(families)}
    <div class="market-note">As barras mostram a força relativa dentro de cada família. Ao abrir uma família, o relatório identifica em linguagem simples que fator favorece cada jogador e com que intensidade.</div>
  </section>
  <p class="foot">Modelo em validação prospetiva · o mercado nunca entra na probabilidade Fenzobot · sem entrada automática.</p>
</main></body></html>"""


def render_index_html(views: list[Mapping[str, Any]]) -> str:
    release_label = (
        views[0].get("global_release_id") if views else None
    ) or "CONTEXTUAL V2"
    cards = []
    for view in views:
        a = view["players"]["a"]
        b = view["players"]["b"]
        filename = f"report-{view['observation_id']}.html"
        cards.append(f"""
        <a class="card" href="{_e(filename)}"><small>{_e(view['tour'])} · {_e(view['tier'])}</small>
          <h2>{_e(a['name'])}<span>vs</span>{_e(b['name'])}</h2>
          <div><b>{_pct(a['probability'])}</b><i>{'mercado congelado' if view['market']['available'] else 'mercado N/D'}</i><b>{_pct(b['probability'])}</b></div>
          <p>{_e(view['quality_label'])}</p></a>""")
    return f"""<!doctype html><html lang="pt-PT"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Fenzobot · {_e(release_label)}</title><style>
    body{{margin:0;background:#061522;color:#eef7ff;font:15px Inter,Segoe UI,Arial,sans-serif}}main{{max-width:1120px;margin:auto;padding:35px 18px}}
    h1{{font-size:38px}}header p,.card p,.card small{{color:#8ba9c4}}.notice{{padding:14px 16px;border:1px solid #ffc857;border-radius:12px;color:#ffc857}}
    .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:14px;margin-top:22px}}.card{{display:block;color:inherit;text-decoration:none;
    background:#0c2035;border:1px solid #244866;border-radius:16px;padding:18px;transition:.15s}}.card:hover{{transform:translateY(-2px);border-color:#43d9d0}}
    .card h2{{font-size:19px;display:flex;flex-direction:column;gap:3px}}.card h2 span{{color:#8ba9c4;font-size:11px;text-transform:uppercase}}
    .card div{{display:flex;justify-content:space-between;align-items:center}}.card b{{font-size:23px}}.card i{{font-size:10px;color:#43d9d0}}
    </style></head><body><main><header><small>FENZOBOT · {_e(release_label)}</small><h1>Novo relatório contextual</h1>
    <p>Previews construídos exclusivamente a partir das previsões congeladas. Nenhuma página abaixo cria PAPER, GREEN ou decisão.</p></header>
    <div class="notice">SHADOW PREVIEW ONLY · mercado observado posteriormente e nunca usado para formar a fair odd.</div>
    <section class="grid">{''.join(cards) or '<p>Sem observações disponíveis.</p>'}</section></main></body></html>"""
