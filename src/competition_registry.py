"""Versioned factual ATP competition/edition registry for CHANGE-102.

Authorization is exact and fail-closed. Provider ranking fields, odds and
fuzzy tournament-name similarity are deliberately ignored.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REGISTRY_PATH = (
    Path(__file__).resolve().parents[1]
    / "data" / "competition_registry" / "atp_ranking_eligible_v1.json"
)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "atp-competition-eligibility-registry-v1":
        raise ValueError("unsupported ATP competition registry schema")
    return payload


REGISTRY = load_registry()
REGISTRY_VERSION = str(REGISTRY["registry_version"])
REGISTRY_SHA256 = hashlib.sha256(
    _canonical_json(REGISTRY).encode("utf-8")
).hexdigest()


def normalize_exact_name(value: Any) -> str:
    """Normalize typography only; never perform partial or fuzzy matching."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _clean(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or not math.isfinite(value)):
        return None
    try:
        same = value == value
        if not isinstance(same, bool):
            bool(same)
        elif not same:
            return None
    except (TypeError, ValueError):
        return None
    if isinstance(value, str):
        value = value.strip()
        if value.casefold() in {
            "", "n/a", "na", "nan", "none", "null", "unknown",
            "unavailable", "not available", "nd", "n/d", "<na>",
        }:
            return None
    return value


def _value(record: Mapping[str, Any], path: str) -> Any:
    current: Any = record
    for part in path.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return _clean(current)


def _names(record: Mapping[str, Any]) -> set[str]:
    result: set[str] = set()
    for path in (
        "tourney_name", "tournament_name", "tournamentName", "Tournament",
        "competition_name", "competitionName", "event_name",
        "tournament.name",
    ):
        normalized = normalize_exact_name(_value(record, path))
        if normalized:
            result.add(normalized)
    tournament = _value(record, "tournament")
    if isinstance(tournament, str):
        normalized = normalize_exact_name(tournament)
        if normalized:
            result.add(normalized)
    return result


def _tournament_id(record: Mapping[str, Any]) -> str | None:
    for path in (
        "tournamentId", "tournament_id", "tourney_id", "tournament.id"
    ):
        value = _value(record, path)
        if value is not None:
            return str(value)
    return None


def _year(record: Mapping[str, Any]) -> int | None:
    for path in (
        "edition_year", "year", "tourney_date", "date", "Date",
        "start_time_utc", "scheduled_start_utc", "tournament.date",
    ):
        value = _value(record, path)
        if value is None:
            continue
        text = str(value).strip()
        if re.fullmatch(r"(?:19|20)\d{6}", text):
            return int(text[:4])
        match = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", text)
        if match:
            return int(match.group(1))
    return None


def _signal(
    classification: str,
    reason_code: str,
    matched_by: str,
    value: str,
    provenance: str,
) -> dict[str, str]:
    return {
        "classification": classification,
        "reason_code": reason_code,
        "matched_by": matched_by,
        "matched_value": value,
        "provenance": provenance,
    }


def _edition_override(
    names: set[str], year: int | None,
) -> dict[str, str] | None:
    if year is None:
        return None
    for rule in REGISTRY.get("edition_overrides", []):
        allowed = set(rule.get("normalized_names") or [])
        matches_names = names.intersection(allowed)
        if not matches_names:
            continue
        exact_year = rule.get("year")
        lower = rule.get("year_from")
        upper = rule.get("year_to")
        matches = (
            (exact_year is not None and int(exact_year) == year)
            or (
                exact_year is None
                and (lower is None or year >= int(lower))
                and (upper is None or year <= int(upper))
            )
        )
        if matches:
            return _signal(
                str(rule["classification"]),
                str(rule["reason_code"]),
                "edition_override",
                f"{sorted(matches_names)[0]}:{year}",
                str(rule["provenance"]),
            )
    return None


def classify(record: Mapping[str, Any]) -> dict[str, Any]:
    """Classify one ATP result by exact registry evidence.

    Temporal overrides are authoritative for that exact edition. Outside an
    override, contradictory exact signals fail closed.
    """
    names = _names(record)
    tournament_id = _tournament_id(record)
    year = _year(record)
    override = _edition_override(names, year)
    if override:
        signals = [override]
    else:
        signals: list[dict[str, str]] = []
        id_rule = (
            REGISTRY.get("exact_tournament_ids", {}).get(tournament_id)
            if tournament_id is not None else None
        )
        if isinstance(id_rule, Mapping):
            signals.append(_signal(
                str(id_rule["classification"]), str(id_rule["reason_code"]),
                "exact_tournament_id", str(tournament_id),
                str(id_rule["provenance"]),
            ))
        reason_codes = REGISTRY.get("exact_name_reason_codes", {})
        for classification, allowed_names in (
            REGISTRY.get("exact_competition_names", {}).items()
        ):
            for name in sorted(names.intersection(set(allowed_names or []))):
                signals.append(_signal(
                    str(classification),
                    str(reason_codes.get(classification) or "EXACT_NAME_MATCH"),
                    "exact_competition_name", name,
                    "registry_exact_competition_names",
                ))
        for field, value_map in (
            REGISTRY.get("explicit_category_fields", {}).items()
        ):
            raw = _value(record, field)
            if raw is None:
                continue
            normalized = normalize_exact_name(raw)
            classification = (value_map or {}).get(normalized)
            if classification:
                signals.append(_signal(
                    str(classification),
                    "EXPLICIT_CATEGORY_RANKING_STATUS",
                    f"category:{field}", normalized,
                    "registry_explicit_category_fields",
                ))
        scope = normalize_exact_name(_value(
            record, "_history_competition_scope"
        ))
        classification = (
            REGISTRY.get("repository_history_scope", {}).get(scope)
            if scope else None
        )
        if classification:
            signals.append(_signal(
                str(classification),
                "REPOSITORY_HISTORY_SCOPE_RANKING_ELIGIBLE",
                "repository_history_scope", scope,
                "repository_source_scope",
            ))

    classifications = {item["classification"] for item in signals}
    base = {
        "registry_version": REGISTRY_VERSION,
        "registry_sha256": REGISTRY_SHA256,
        "tournament_id": tournament_id,
        "edition_year": year,
        "normalized_names": sorted(names),
        "identity_evidence": signals,
    }
    if not signals:
        return {
            **base, "competition": "UNRESOLVED",
            "classification": "UNRESOLVED", "weight": None,
            "status": "BLOCKED",
            "reason_code": "ATP_RANKING_ELIGIBILITY_UNRESOLVED",
        }
    if len(classifications) != 1:
        return {
            **base, "competition": "UNRESOLVED",
            "classification": "UNRESOLVED", "weight": None,
            "status": "BLOCKED",
            "reason_code": "ATP_RANKING_ELIGIBILITY_CONFLICT",
        }
    classification = next(iter(classifications))
    weight = REGISTRY["classification_weights"].get(classification)
    if weight is None:
        return {
            **base, "competition": "UNRESOLVED",
            "classification": "UNRESOLVED", "weight": None,
            "status": "BLOCKED",
            "reason_code": "ATP_RANKING_CLASSIFICATION_UNSUPPORTED",
        }
    selected = signals[0]
    return {
        **base, "competition": classification,
        "classification": classification, "weight": float(weight),
        "status": "EXCLUDED" if float(weight) == 0 else "INCLUDED",
        "reason_code": selected["reason_code"],
    }
