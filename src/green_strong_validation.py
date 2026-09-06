"""Coorte prospetiva GREEN_STRONG_V1 e respetiva vista derivada.

Não chama APIs, não usa LLM e não altera decisões, PAPER ou snapshots antigos.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import market_memory_report


CHANGE_ID = "CHANGE-2026-09-06-026"
COHORT_NAME = "GREEN_STRONG_V1"
CONTRACT_VERSION = "green-strong-v1"
SCHEMA_VERSION = 1
DEFAULT_OUTPUT_PATH = Path("data/validation/green-strong-v1.json")
DEFAULT_MANUAL_PATH = Path("data/manual_paper_22bet.json")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _probability(pricing: Mapping[str, Any], kind: str, side: str) -> float | None:
    nested_key = "market_probability_pct" if kind == "market" else "sharp_estimate_pct"
    flat_key = f"market_probability_{side}" if kind == "market" else f"sharp_estimate_{side}"
    value = _mapping(_mapping(pricing.get("players")).get(side)).get(nested_key)
    scale = 100.0
    if value is None:
        value = pricing.get(flat_key)
        scale = 1.0
    try:
        number = float(value) / scale
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and 0 < number < 1 else None


def _divergence_side(payload: Mapping[str, Any], divergence: Mapping[str, Any]) -> str | None:
    try:
        a = float(divergence.get("indice_evidencia_a"))
        b = float(divergence.get("indice_evidencia_b"))
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(a) and math.isfinite(b)) or a == b:
        return None
    side = "a" if a > b else "b"
    named = divergence.get("indice_favorece")
    if named and str(named) != str(payload.get(f"player_{side}")):
        return None
    return side


def _is_prestart(classified_at_utc: str, commence_time_utc: Any) -> bool:
    try:
        classified = datetime.fromisoformat(classified_at_utc.replace("Z", "+00:00"))
        commence = datetime.fromisoformat(str(commence_time_utc).replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return False
    try:
        return classified < commence
    except TypeError:
        return False


def classify_snapshot(
    payload: Mapping[str, Any],
    *,
    snapshot_key: str,
    classified_at_utc: str,
    prospective: bool = True,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Classifica uma primeira fotografia ex-ante; qualquer dúvida falha fechada."""
    decision = _mapping(payload.get("prelive_decision"))
    divergence = _mapping(payload.get("divergencia"))
    pricing = _mapping(payload.get("pricing"))
    assessment = _mapping(payload.get("report_assessment"))
    reasons: list[str] = []

    if not prospective:
        reasons.append("NOT_PROSPECTIVE")
    if not _is_prestart(classified_at_utc, payload.get("commence_time_utc")):
        reasons.append("CLASSIFICATION_NOT_PRESTART")
    if decision.get("state") != "EDGE_POSITIVE":
        reasons.append("DECISION_STATE_NOT_EDGE_POSITIVE")
    if decision.get("paper_eligible") is not True:
        reasons.append("PAPER_NOT_ELIGIBLE")
    if divergence.get("tipo") != "direcao":
        reasons.append("DIVERGENCE_TYPE_NOT_DIRECTION")
    if _mapping(divergence.get("classificacao")).get("nivel") != 3:
        reasons.append("DIVERGENCE_LEVEL_NOT_STRONG")

    selected_side = decision.get("side") if decision.get("side") in {"a", "b"} else None
    divergence_side = _divergence_side(payload, divergence)
    if selected_side is None:
        reasons.append("SELECTED_SIDE_UNAVAILABLE")
    if divergence_side is None:
        reasons.append("DIVERGENCE_SIDE_UNAVAILABLE")
    if selected_side and divergence_side and selected_side != divergence_side:
        reasons.append("SELECTED_SIDE_MISMATCH")
    if not pricing.get("available"):
        reasons.append("PRICING_UNAVAILABLE")

    market = {side: _probability(pricing, "market", side) for side in ("a", "b")}
    fenzobot = {side: _probability(pricing, "fenzobot", side) for side in ("a", "b")}
    if None in market.values() or None in fenzobot.values():
        reasons.append("PROBABILITIES_UNAVAILABLE")

    selected_player = payload.get(f"player_{selected_side}") if selected_side else None
    if not selected_player or not decision.get("player"):
        reasons.append("SELECTED_PLAYER_UNAVAILABLE")
    if selected_side and decision.get("player") and decision.get("player") != selected_player:
        reasons.append("INTEGRITY_CONFLICT")
    candidate_side = pricing.get("candidate_side")
    if candidate_side in {"a", "b"} and selected_side and candidate_side != selected_side:
        reasons.append("INTEGRITY_CONFLICT")
    if decision.get("conflict") or assessment.get("report_null"):
        reasons.append("INTEGRITY_CONFLICT")
    if None not in market.values() and abs(sum(market.values()) - 1.0) > 0.001:
        reasons.append("PROBABILITIES_INCOHERENT")
    if None not in fenzobot.values() and abs(sum(fenzobot.values()) - 1.0) > 0.001:
        reasons.append("PROBABILITIES_INCOHERENT")
    reasons = list(dict.fromkeys(reasons))

    env = environment if environment is not None else os.environ
    identity = f"{CONTRACT_VERSION}|{snapshot_key}|{classified_at_utc}"
    return {
        "contract_version": CONTRACT_VERSION,
        "validation_id": hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24],
        "classified_at_utc": classified_at_utc,
        "prospective": bool(prospective),
        "eligible": not reasons,
        "status": "INELIGIBLE" if reasons else "ELIGIBLE",
        "selected_side": selected_side,
        "selected_player": selected_player,
        "reason_codes": reasons,
        "source": {
            "snapshot_key": snapshot_key,
            "decision_contract_version": decision.get("contract_version") or "UNAVAILABLE",
            "decision_state": decision.get("state") or "UNAVAILABLE",
            "divergence_type": divergence.get("tipo") or "UNAVAILABLE",
            "divergence_level": _mapping(divergence.get("classificacao")).get("nivel", "UNAVAILABLE"),
            "pricing_model_version": pricing.get("model_version") or "UNAVAILABLE",
            "pricing_configuration_fingerprint": pricing.get("configuration_fingerprint") or "UNAVAILABLE",
            "code_revision": env.get("GITHUB_SHA") or "UNAVAILABLE",
            "github_run_id": env.get("GITHUB_RUN_ID") or "UNAVAILABLE",
            "market_probabilities": market if None not in market.values() else "UNAVAILABLE",
            "fenzobot_probabilities": fenzobot if None not in fenzobot.values() else "UNAVAILABLE",
        },
    }


def _metric(rows: Iterable[Mapping[str, Any]], probability_field: str) -> dict[str, Any]:
    return market_memory_report.evaluate_probabilities(list(rows), probability_field)


def _movement(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    values = []
    for row in rows:
        side = row.get("selected_side")
        entry = row.get("pricing_market_probabilities")
        closing = row.get("last_valid_prestart_market_probabilities")
        if side not in {"a", "b"} or not isinstance(entry, Mapping) or not isinstance(closing, Mapping):
            continue
        try:
            values.append(100 * (float(closing[side]) - float(entry[side])))
        except (KeyError, TypeError, ValueError):
            continue
    return {
        "sample_size": len(values),
        "average_probability_pp": round(statistics.fmean(values), 4) if values else None,
        "median_probability_pp": round(statistics.median(values), 4) if values else None,
        "positive_direction_pct": round(100 * sum(value > 0 for value in values) / len(values), 2) if values else None,
    }


def _cohort_metrics(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    settled = [row for row in rows if row.get("outcome_side") in {"a", "b"}]
    wins = sum(row.get("outcome_side") == row.get("selected_side") for row in settled)
    selected_market = []
    selected_fenzobot = []
    for row in rows:
        side = row.get("selected_side")
        if side not in {"a", "b"}:
            continue
        for field, target in (("pricing_market_probabilities", selected_market), ("fenzobot_probabilities", selected_fenzobot)):
            values = row.get(field)
            if isinstance(values, Mapping) and values.get(side) is not None:
                target.append(float(values[side]))
    market_eval = _metric(settled, "pricing_market_probabilities")
    fenzobot_eval = _metric(settled, "fenzobot_probabilities")
    return {
        "sample_size": len(rows),
        "settled_sample_size": len(settled),
        "entry_market_usable": sum(isinstance(row.get("pricing_market_probabilities"), Mapping) for row in rows),
        "closing_market_comparable": sum(isinstance(row.get("last_valid_prestart_market_probabilities"), Mapping) for row in rows),
        "wins": wins,
        "win_rate_pct": round(100 * wins / len(settled), 2) if settled else None,
        "average_selected_market_probability": round(statistics.fmean(selected_market), 6) if selected_market else None,
        "average_selected_fenzobot_probability": round(statistics.fmean(selected_fenzobot), 6) if selected_fenzobot else None,
        "market": market_eval,
        "fenzobot": fenzobot_eval,
        "paired_delta": {
            "brier": round(fenzobot_eval["brier_score"] - market_eval["brier_score"], 6)
            if fenzobot_eval.get("brier_score") is not None and market_eval.get("brier_score") is not None else None,
            "log_loss": round(fenzobot_eval["log_loss"] - market_eval["log_loss"], 6)
            if fenzobot_eval.get("log_loss") is not None and market_eval.get("log_loss") is not None else None,
        },
        "closing_movement": _movement(rows),
    }


def _segments(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    dimensions = {
        "tour": lambda row: row.get("tour") or "UNAVAILABLE",
        "match_format": lambda row: row.get("match_format") or "UNAVAILABLE",
        "selected_side_market_position": lambda row: row.get("selected_side_market_position") or "UNAVAILABLE",
        "pricing_model": lambda row: f"{row.get('pricing_model_version') or 'UNAVAILABLE'}:{row.get('pricing_configuration_fingerprint') or 'UNAVAILABLE'}",
        "code_revision": lambda row: row.get("cohort_code_revision") or "UNAVAILABLE",
    }
    result = {}
    for name, getter in dimensions.items():
        buckets: dict[str, list[Mapping[str, Any]]] = {}
        for row in rows:
            buckets.setdefault(str(getter(row)), []).append(row)
        result[name] = {key: _cohort_metrics(list(value)) for key, value in sorted(buckets.items())}
    return result


def _manual_strategy(path: Path) -> Mapping[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return _mapping(_mapping(document).get("by_strategy")).get("GUERRA_SELECTION_V1") or {}


def _observation(row: Mapping[str, Any]) -> dict[str, Any]:
    membership = _mapping(_mapping(row.get("cohort_memberships")).get(COHORT_NAME))
    side = row.get("selected_side")
    market = row.get("pricing_market_probabilities")
    fenzobot = row.get("fenzobot_probabilities")
    closing = row.get("last_valid_prestart_market_probabilities")

    def selected(values: Any) -> float | None:
        if side not in {"a", "b"} or not isinstance(values, Mapping):
            return None
        try:
            return round(float(values[side]), 6)
        except (KeyError, TypeError, ValueError):
            return None

    entry_value = selected(market)
    closing_value = selected(closing)
    return {
        "snapshot_key": row.get("snapshot_key"),
        "validation_id": membership.get("validation_id"),
        "scheduled_start_utc": row.get("scheduled_start_utc"),
        "tour": row.get("tour") or "UNAVAILABLE",
        "surface": row.get("surface") or "UNAVAILABLE",
        "match_format": row.get("match_format") or "UNAVAILABLE",
        "selected_side": side,
        "selected_side_market_position": row.get("selected_side_market_position") or "UNAVAILABLE",
        "entry_market_probability": entry_value,
        "fenzobot_probability": selected(fenzobot),
        "outcome_side": row.get("outcome_side") or "UNAVAILABLE",
        "selected_side_won": row.get("outcome_side") == side if row.get("outcome_side") in {"a", "b"} else None,
        "last_valid_prestart_market_probability": closing_value,
        "closing_movement_probability_pp": round(100 * (closing_value - entry_value), 4)
        if entry_value is not None and closing_value is not None else None,
        "pricing_model_version": row.get("pricing_model_version") or "UNAVAILABLE",
        "pricing_configuration_fingerprint": row.get("pricing_configuration_fingerprint") or "UNAVAILABLE",
        "code_revision": row.get("cohort_code_revision") or "UNAVAILABLE",
    }


def build_report(*, memory_report: Mapping[str, Any], manual_path: Path = DEFAULT_MANUAL_PATH) -> dict[str, Any]:
    events = [dict(row) for row in memory_report.get("events") or [] if isinstance(row, Mapping)]
    classifications = []
    eligible = []
    for row in events:
        membership = _mapping(_mapping(row.get("cohort_memberships")).get(COHORT_NAME))
        if not membership:
            continue
        classifications.append({
            "snapshot_key": row.get("snapshot_key"),
            "commence_time_utc": row.get("scheduled_start_utc"),
            "eligible": membership.get("eligible") is True,
            "status": membership.get("status") or ("ELIGIBLE" if membership.get("eligible") is True else "INELIGIBLE"),
            "validation_id": membership.get("validation_id"),
            "selected_side": membership.get("selected_side"),
            "selected_side_market_position": row.get("selected_side_market_position") or "UNAVAILABLE",
            "reason_codes": membership.get("reason_codes") or [],
        })
        if membership.get("eligible") is True:
            eligible.append(row)
    metrics = _cohort_metrics(eligible)
    manual = dict(_manual_strategy(manual_path))
    return {
        "schema_version": SCHEMA_VERSION,
        "change_id": CHANGE_ID,
        "cohort": COHORT_NAME,
        "contract_version": CONTRACT_VERSION,
        "generated_at_utc": _now(),
        "mode": "PROSPECTIVE_SHADOW_VALIDATION",
        "claims": "EXPERIMENTAL_NOT_VALIDATED",
        "source_of_truth": ["calibration_snapshots", "market_time_ledger", "settled_outcomes"],
        "prospective_classifications": classifications,
        "eligible_observations": [_observation(row) for row in eligible],
        "metrics": metrics,
        "segments": _segments(eligible),
        "guerra_selection_v1": manual or {"status": "UNAVAILABLE"},
        "unavailable_semantics": "Missing or contradictory evidence remains UNAVAILABLE and is never inferred.",
    }


def write_report(report: Mapping[str, Any], *, path: Path = DEFAULT_OUTPUT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def build_and_write(**kwargs: Any) -> dict[str, Any]:
    output_path = kwargs.pop("output_path", DEFAULT_OUTPUT_PATH)
    report = build_report(**kwargs)
    write_report(report, path=output_path)
    return report
