"""Prospective weighting of team-event evidence for individual performance.

CHANGE-2026-10-10-099. The policy is inert until an explicit version and
UTC cutover are configured. Historical artefacts are never rewritten.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

try:
    from . import competition_registry
except ImportError:  # pragma: no cover - legacy direct-module test path
    import competition_registry

CHANGE_ID = "CHANGE-2026-10-10-099"
POLICY_VERSION = "davis-laver-performance-v1"
LAVER_ONLY_CHANGE_ID = "CHANGE-2026-10-11-101"
LAVER_ONLY_ORIGINAL_ALIAS = "CHANGE-2026-10-11-100"
LAVER_ONLY_POLICY_VERSION = "laver-only-performance-v1"
RANKING_ELIGIBLE_CHANGE_ID = "CHANGE-2026-10-11-102"
RANKING_ELIGIBLE_POLICY_VERSION = "atp-ranking-eligible-performance-v1"
RANKING_ELIGIBLE_V2_CHANGE_ID = "CHANGE-2026-10-11-105"
RANKING_ELIGIBLE_V2_POLICY_VERSION = "atp-ranking-eligible-performance-v2"
RANKING_ELIGIBLE_V1_EFFECTIVE_FROM_UTC = "2026-10-12T00:00:00Z"
RANKING_REGISTRY_VERSION = competition_registry.REGISTRY_VERSION
RANKING_REGISTRY_SHA256 = competition_registry.REGISTRY_SHA256
ACTIVATION_VERSION_ENV = "FENZOBOT_COMPETITION_EVIDENCE_VERSION"
ACTIVATION_UTC_ENV = "FENZOBOT_COMPETITION_EVIDENCE_EFFECTIVE_FROM_UTC"

# Factual ids observed in repository fixtures. Davis ids are deliberately not
# mapped: an id or a final tie score cannot prove the pre-match tie state.
LAVER_TOURNAMENT_IDS = frozenset({"19409", "20363", "21353"})
_POLICY_SPEC = {
    "change_id": CHANGE_ID,
    "version": POLICY_VERSION,
    "individual_reference_weight": 1.0,
    "davis_competitive_weight": 0.5,
    "laver_weight": 0.0,
    "davis_decided": "BLOCK",
    "davis_unknown": "BLOCK",
    "selection_order": "select_sample_then_apply_weights",
    "fatigue_load": "raw_factual_unweighted",
}
CONFIG_HASH = hashlib.sha256(
    json.dumps(
        _POLICY_SPEC, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
).hexdigest()[:20]
_LAVER_ONLY_POLICY_SPEC = {
    "change_id": LAVER_ONLY_CHANGE_ID,
    "version": LAVER_ONLY_POLICY_VERSION,
    "individual_reference_weight": 1.0,
    "davis_treatment": "PRESERVE_CURRENT_PRODUCTION",
    "laver_weight": 0.0,
    "selection_order": "select_sample_then_exclude_laver",
    "fatigue_load": "raw_factual_unweighted",
}
LAVER_ONLY_CONFIG_HASH = hashlib.sha256(
    json.dumps(_LAVER_ONLY_POLICY_SPEC, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()[:20]
_RANKING_ELIGIBLE_POLICY_SPEC = {
    "change_id": RANKING_ELIGIBLE_CHANGE_ID,
    "version": RANKING_ELIGIBLE_POLICY_VERSION,
    "registry_version": RANKING_REGISTRY_VERSION,
    "registry_sha256": RANKING_REGISTRY_SHA256,
    "included": [
        "RANKING_ELIGIBLE", "DAVIS_EXCEPTION",
        "NEXT_GEN_EXCEPTION", "OLYMPICS_EXCEPTION",
    ],
    "excluded": ["NON_RANKING"],
    "blocked": ["UNRESOLVED", "CONFLICT"],
    "included_weight": 1.0,
    "non_ranking_weight": 0.0,
    "selection_order": "select_sample_then_apply_eligibility",
    "fatigue_load": "raw_factual_unweighted",
    "authorization": "exact_registry_no_fuzzy",
    "temporal_application": "per_match_t0_delta",
    "pre_t0_policy_version": LAVER_ONLY_POLICY_VERSION,
    "post_t0_policy_version": RANKING_ELIGIBLE_POLICY_VERSION,
    "missing_match_date": "BLOCK",
}
RANKING_ELIGIBLE_CONFIG_HASH = hashlib.sha256(
    json.dumps(
        _RANKING_ELIGIBLE_POLICY_SPEC,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()[:20]
_RANKING_ELIGIBLE_V2_WEIGHTS = {
    "RANKING_ELIGIBLE": 1.0,
    "DAVIS_EXCEPTION": 0.5,
    "NEXT_GEN_EXCEPTION": 0.5,
    "OLYMPICS_EXCEPTION": 0.5,
    "NON_RANKING": 0.0,
}
_RANKING_ELIGIBLE_V2_POLICY_SPEC = {
    "change_id": RANKING_ELIGIBLE_V2_CHANGE_ID,
    "version": RANKING_ELIGIBLE_V2_POLICY_VERSION,
    "registry_version": RANKING_REGISTRY_VERSION,
    "registry_sha256": RANKING_REGISTRY_SHA256,
    "classification_weights": _RANKING_ELIGIBLE_V2_WEIGHTS,
    "blocked": ["UNRESOLVED", "CONFLICT"],
    "selection_order": "select_sample_then_apply_eligibility",
    "fatigue_load": "raw_factual_unweighted",
    "authorization": "exact_registry_no_fuzzy",
    "temporal_application": "per_match_t1_delta",
    "pre_t0_policy_version": LAVER_ONLY_POLICY_VERSION,
    "intermediate_policy_version": RANKING_ELIGIBLE_POLICY_VERSION,
    "post_t1_policy_version": RANKING_ELIGIBLE_V2_POLICY_VERSION,
    "v1_effective_from_utc": RANKING_ELIGIBLE_V1_EFFECTIVE_FROM_UTC,
    "missing_match_date": "BLOCK",
    "registry_factual_taxonomy_reused": True,
}
RANKING_ELIGIBLE_V2_CONFIG_HASH = hashlib.sha256(
    json.dumps(
        _RANKING_ELIGIBLE_V2_POLICY_SPEC,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()[:20]


def _policy_contract(policy: Mapping[str, Any] | None = None) -> tuple[str, str, str]:
    version = str((policy or {}).get("version") or POLICY_VERSION)
    if version == LAVER_ONLY_POLICY_VERSION:
        return LAVER_ONLY_CHANGE_ID, LAVER_ONLY_POLICY_VERSION, LAVER_ONLY_CONFIG_HASH
    if version == RANKING_ELIGIBLE_POLICY_VERSION:
        return (
            RANKING_ELIGIBLE_CHANGE_ID,
            RANKING_ELIGIBLE_POLICY_VERSION,
            RANKING_ELIGIBLE_CONFIG_HASH,
        )
    if version == RANKING_ELIGIBLE_V2_POLICY_VERSION:
        return (
            RANKING_ELIGIBLE_V2_CHANGE_ID,
            RANKING_ELIGIBLE_V2_POLICY_VERSION,
            RANKING_ELIGIBLE_V2_CONFIG_HASH,
        )
    return CHANGE_ID, POLICY_VERSION, CONFIG_HASH


def policy_is_supported(policy: Mapping[str, Any] | None) -> bool:
    if not isinstance(policy, Mapping):
        return False
    _change, version, config_hash = _policy_contract(policy)
    return policy.get("version") == version and policy.get("config_hash") == config_hash


def is_laver_only(policy: Mapping[str, Any] | None) -> bool:
    """Recognize the Laver-only contract independently of runtime activation."""
    return policy_is_supported(policy) and policy.get("version") == LAVER_ONLY_POLICY_VERSION


def is_active_laver_only(policy: Mapping[str, Any] | None) -> bool:
    """Authorize Laver-only behaviour only inside its active ATP scope."""
    return (
        is_laver_only(policy)
        and policy.get("active") is True
        and str(policy.get("tour") or "").strip().casefold() == "atp"
    )


def is_ranking_eligible(policy: Mapping[str, Any] | None) -> bool:
    """Recognize the CHANGE-102/105 family independently of activation."""
    return (
        policy_is_supported(policy)
        and policy.get("version") in {
            RANKING_ELIGIBLE_POLICY_VERSION,
            RANKING_ELIGIBLE_V2_POLICY_VERSION,
        }
    )


def is_ranking_eligible_v2(policy: Mapping[str, Any] | None) -> bool:
    """Recognize CHANGE-105 without treating v1 metadata as v2."""
    return (
        policy_is_supported(policy)
        and policy.get("version") == RANKING_ELIGIBLE_V2_POLICY_VERSION
    )


def is_active_ranking_eligible(policy: Mapping[str, Any] | None) -> bool:
    """Authorize CHANGE-102 only inside its explicit prospective ATP scope."""
    return (
        is_ranking_eligible(policy)
        and policy.get("active") is True
        and str(policy.get("tour") or "").strip().casefold() == "atp"
    )


def uses_match_level_competition_evidence(
    policy: Mapping[str, Any] | None,
) -> bool:
    """Require reconstructed match-level sources for active ATP policies."""
    return is_active_laver_only(policy) or is_active_ranking_eligible(policy)


_DAVIS_RE = re.compile(r"\bdavis(?:\s+cup)?\b", re.IGNORECASE)
_LAVER_RE = re.compile(r"\blaver(?:\s+cup)?\b", re.IGNORECASE)
_GENERIC_CUP_RE = re.compile(r"\bcup\b", re.IGNORECASE)
_COMPETITIVE = frozenset({"IN_DISPUTE", "COMPETITIVE", "LIVE", "TIE_LIVE"})
_DECIDED = frozenset(
    {"DECIDED", "DEAD_RUBBER", "TIE_DECIDED", "NON_COMPETITIVE"}
)

# Explicitly identified competitions outside this CHANGE keep their existing
# treatment. This is not an inference that they are individual tournaments.
_OUT_OF_SCOPE_TEAM_COMPETITIONS = (
    re.compile(r"\bunited\s+cup\b", re.IGNORECASE),
    re.compile(r"\batp\s+cup\b", re.IGNORECASE),
    re.compile(r"\bbillie\s+jean\s+king\s+cup\b", re.IGNORECASE),
    re.compile(r"\bfed\s+cup\b", re.IGNORECASE),
    re.compile(r"\bolympic", re.IGNORECASE),
)

# Result-derived factor families. They stay present for factual display. The
# decision engine admits each factor only when its own source carries compatible
# match-level competition provenance.
RESULT_DERIVED_FEATURE_KEYS = frozenset({
    "h2h", "h2h_piso", "piso", "forma_recente", "qualidade_vitorias",
    "indoor_outdoor", "velocidade_piso", "tiebreak", "pressao_ronda",
    "nivel_adversario", "historico_torneio", "comeback_set1", "sazonal",
    "recuperacao_sets", "matchup_maos", "servico_carreira",
    "servico_recente", "surface_momentum", "opposition_quality",
    "pressure_profile", "game_margin", "game_differential",
})
DIRECT_UNSEPARABLE_CONSUMERS = frozenset({
    "recuperacao_sets", "matchup_maos", "historico_torneio", "comeback_set1",
})
INSEPARABLE_SOURCE_BLOCKERS = (
    "rapidapi_recent_stats_aggregate",
    "rapidapi_perf_breakdown_aggregate",
    "rapidapi_h2h_vs_all_aggregate",
    "local_result_helpers_without_competition_provenance",
)


def activation_from_environment(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return the explicit forward-only activation state; never auto-activate."""
    source = os.environ if environ is None else environ
    requested = str(source.get(ACTIVATION_VERSION_ENV) or "").strip()
    effective_from = str(source.get(ACTIVATION_UTC_ENV) or "").strip()
    parsed_effective = None
    if effective_from:
        try:
            parsed_effective = datetime.fromisoformat(
                effective_from.replace("Z", "+00:00")
            )
            if parsed_effective.tzinfo is None:
                parsed_effective = parsed_effective.replace(tzinfo=timezone.utc)
        except ValueError:
            parsed_effective = None
    supported_versions = {
        POLICY_VERSION,
        LAVER_ONLY_POLICY_VERSION,
        RANKING_ELIGIBLE_POLICY_VERSION,
        RANKING_ELIGIBLE_V2_POLICY_VERSION,
    }
    selected = (
        requested if requested in supported_versions else POLICY_VERSION
    )
    selected_change, selected_version, selected_hash = _policy_contract({"version": selected})
    active = (
        requested in supported_versions
        and parsed_effective is not None
        and datetime.now(timezone.utc) >= parsed_effective.astimezone(timezone.utc)
    )
    reason = (
        "ACTIVE"
        if active
        else "ACTIVATION_EFFECTIVE_FROM_UTC_INVALID_OR_FUTURE"
        if requested in supported_versions and effective_from
        else "ACTIVATION_EFFECTIVE_FROM_UTC_MISSING"
        if requested in supported_versions
        else "ACTIVATION_VERSION_NOT_SELECTED"
    )
    return {
        "change_id": selected_change,
        "version": selected_version,
        "config_hash": selected_hash,
        "status": reason,
        "active": active,
        "effective_from_utc": effective_from or None,
        "requested_version": requested or None,
        "application": "PROSPECTIVE_ONLY",
        "scope": "ATP_ONLY",
    }


def activation_for_tour(
    activation: Mapping[str, Any], tour: str | None,
) -> dict[str, Any]:
    """Limit the approved experiment to ATP without changing other circuits."""
    scoped = dict(activation)
    normalized = str(tour or "").strip().casefold()
    if activation.get("active") is True and normalized != "atp":
        scoped["active"] = False
        scoped["status"] = "OUT_OF_SCOPE_TOUR"
        scoped["scope_reason_code"] = "COMPETITION_POLICY_ATP_ONLY"
    scoped["tour"] = normalized or None
    return scoped


_MISSING_SENTINELS = frozenset({
    "", "n/a", "na", "nan", "none", "null", "unknown", "unavailable",
    "not available", "desconhecido", "nd", "n/d", "<na>",
})


def _clean_scalar(value: Any) -> Any:
    """Normalize provider missing values without importing pandas here."""
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return None if cleaned.casefold() in _MISSING_SENTINELS else cleaned
    if isinstance(value, float) and math.isnan(value):
        return None
    # pandas.NA deliberately raises when coerced to bool; treat that as missing.
    try:
        equality = value == value
        if isinstance(equality, bool) and not equality:
            return None
        if not isinstance(equality, bool):
            bool(equality)
    except (TypeError, ValueError):
        return None
    return value


def _value(record: Mapping[str, Any], *paths: str) -> Any:
    for path in paths:
        current: Any = record
        for part in path.split("."):
            if not isinstance(current, Mapping):
                current = None
                break
            current = current.get(part)
        current = _clean_scalar(current)
        if current is not None:
            return current
    return None


def _tournament_text(record: Mapping[str, Any]) -> str:
    values = [
        _value(record, "tourney_name"),
        _value(record, "tournament_name"),
        _value(record, "tournamentName"),
        _value(record, "competition_name"),
        _value(record, "competitionName"),
        _value(record, "event_name"),
        _value(record, "tournament.name"),
    ]
    tournament = _value(record, "tournament")
    if isinstance(tournament, str) and tournament.strip():
        values.append(tournament)
    ambiguous_name = _value(record, "name")
    if (
        ambiguous_name not in (None, "")
        and re.search(
            r"\b(?:davis|laver)\s+cup\b",
            str(ambiguous_name),
            re.IGNORECASE,
        )
    ):
        values.append(ambiguous_name)
    return " | ".join(str(value).strip() for value in values if value not in (None, ""))


def _tournament_id(record: Mapping[str, Any]) -> str | None:
    value = _value(
        record, "tournamentId", "tournament_id", "tourney_id", "tournament.id"
    )
    return str(value) if value not in (None, "") else None


def _explicit_davis_state(record: Mapping[str, Any]) -> str | None:
    raw = _value(
        record,
        "davis_tie_status_before_match",
        "tie_status_before_match",
        "competition_context.davis_tie_status_before_match",
        "competition_context.tie_status_before_match",
    )
    if raw in (None, ""):
        return None
    return str(raw).strip().upper().replace("-", "_").replace(" ", "_")


def _blocked(
    reason_code: str,
    *,
    competition: str = "UNRESOLVED",
    tournament_id: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "competition": competition,
        "weight": None,
        "status": "BLOCKED",
        "reason_code": reason_code,
        "tournament_id": tournament_id,
        **extra,
    }


def classify_match(record: Mapping[str, Any], policy: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Classify one result without inventing identity or Davis tie state."""
    if is_ranking_eligible(policy):
        classification = competition_registry.classify(record)
        if not is_ranking_eligible_v2(policy):
            return classification
        factual_class = str(classification.get("classification") or "")
        if factual_class not in _RANKING_ELIGIBLE_V2_WEIGHTS:
            return classification
        weight = _RANKING_ELIGIBLE_V2_WEIGHTS[factual_class]
        return {
            **classification,
            "weight": weight,
            "status": "EXCLUDED" if weight == 0.0 else "INCLUDED",
            "factual_registry_weight": classification.get("weight"),
            "weight_policy_version": RANKING_ELIGIBLE_V2_POLICY_VERSION,
        }
    name = _tournament_text(record)
    tournament_id = _tournament_id(record)
    davis_name = bool(_DAVIS_RE.search(name))
    laver_name = bool(_LAVER_RE.search(name))
    laver_id = tournament_id in LAVER_TOURNAMENT_IDS

    # A known Laver id may stand alone, but may never override a
    # contradictory factual competition name.
    if (
        (davis_name and (laver_name or laver_id))
        or (laver_id and name and not laver_name)
    ):
        return _blocked(
            "COMPETITION_IDENTITY_CONFLICT",
            tournament_id=tournament_id,
        )
    if laver_id or laver_name:
        return {
            "competition": "LAVER_CUP",
            "weight": 0.0,
            "status": "WEIGHTED",
            "reason_code": "LAVER_EXCLUDED_FROM_PERFORMANCE",
            "tournament_id": tournament_id,
        }
    if davis_name:
        if is_laver_only(policy):
            return {
                "competition": "DAVIS_CUP",
                "weight": 1.0,
                "status": "PRESERVED",
                "reason_code": "DAVIS_CURRENT_PRODUCTION_TREATMENT_PRESERVED",
                "tournament_id": tournament_id,
            }
        state = _explicit_davis_state(record)
        if state in _COMPETITIVE:
            return {
                "competition": "DAVIS_CUP",
                "weight": 0.5,
                "status": "WEIGHTED",
                "reason_code": "DAVIS_TIE_COMPETITIVE_PRE_MATCH",
                "davis_tie_status_before_match": state,
                "tournament_id": tournament_id,
            }
        if state in _DECIDED:
            return _blocked(
                "DAVIS_TIE_ALREADY_DECIDED_NO_COEFFICIENT",
                competition="DAVIS_CUP",
                tournament_id=tournament_id,
                davis_tie_status_before_match=state,
            )
        return _blocked(
            "DAVIS_PRE_MATCH_TIE_STATE_UNKNOWN",
            competition="DAVIS_CUP",
            tournament_id=tournament_id,
            davis_tie_status_before_match=state,
        )

    if not name:
        return _blocked(
            "COMPETITION_IDENTITY_UNRESOLVED",
            tournament_id=tournament_id,
        )
    if any(pattern.search(name) for pattern in _OUT_OF_SCOPE_TEAM_COMPETITIONS):
        return {
            "competition": "OUT_OF_SCOPE_IDENTIFIED",
            "weight": 1.0,
            "status": "PRESERVED",
            "reason_code": "OUT_OF_SCOPE_COMPETITION_PRESERVED",
            "tournament_id": tournament_id,
        }
    if _GENERIC_CUP_RE.search(name):
        return _blocked(
            "COMPETITION_CUP_IDENTITY_UNRESOLVED",
            tournament_id=tournament_id,
        )
    return {
        "competition": "INDIVIDUAL_REFERENCE",
        "weight": 1.0,
        "status": "WEIGHTED",
        "reason_code": "INDIVIDUAL_REFERENCE",
        "tournament_id": tournament_id,
    }


def _policy_effective_from(
    policy: Mapping[str, Any] | None,
) -> datetime | None:
    raw = _clean_scalar((policy or {}).get("effective_from_utc"))
    if raw is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _match_datetime(record: Mapping[str, Any]) -> datetime | None:
    raw = _value(
        record,
        "tourney_date", "match_date", "date", "start_time",
        "startTime", "scheduled_start_utc", "scheduledStartUtc",
    )
    if raw is None:
        return None
    if isinstance(raw, datetime):
        parsed = raw
    else:
        text = str(raw).strip()
        try:
            if re.fullmatch(r"\d{8}", text):
                parsed = datetime.strptime(text, "%Y%m%d")
            elif re.fullmatch(r"\d{10,13}(?:\.0+)?", text):
                stamp = float(text)
                if stamp >= 10_000_000_000:
                    stamp /= 1000.0
                parsed = datetime.fromtimestamp(stamp, tz=timezone.utc)
            else:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except (OverflowError, TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def classify_selected_match(
    record: Mapping[str, Any],
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply ranking policies per match without reweighting an earlier era."""
    if not is_ranking_eligible(policy):
        return classify_match(record, policy)
    effective_from = _policy_effective_from(policy)
    if effective_from is None:
        return _blocked(
            (
                "COMPETITION_POLICY_T1_INVALID"
                if is_ranking_eligible_v2(policy)
                else "COMPETITION_POLICY_T0_INVALID"
            ),
            temporal_scope=(
                "UNRESOLVED_T1"
                if is_ranking_eligible_v2(policy)
                else "UNRESOLVED_T0"
            ),
            applied_policy_version=None,
        )
    match_at = _match_datetime(record)
    if match_at is None:
        return _blocked(
            "COMPETITION_MATCH_DATE_UNRESOLVED",
            temporal_scope="UNRESOLVED_MATCH_DATE",
            applied_policy_version=None,
            effective_from_utc=effective_from.isoformat(),
        )

    v1_effective_from = datetime.fromisoformat(
        RANKING_ELIGIBLE_V1_EFFECTIVE_FROM_UTC.replace("Z", "+00:00")
    )
    if is_ranking_eligible_v2(policy):
        if effective_from <= v1_effective_from:
            return _blocked(
                "COMPETITION_POLICY_T1_NOT_AFTER_V1_T0",
                temporal_scope="UNRESOLVED_T1",
                applied_policy_version=None,
                effective_from_utc=effective_from.isoformat(),
                v1_effective_from_utc=v1_effective_from.isoformat(),
            )
        if match_at < v1_effective_from:
            applied_policy = {
                "version": LAVER_ONLY_POLICY_VERSION,
                "config_hash": LAVER_ONLY_CONFIG_HASH,
            }
            temporal_scope = "PRE_T0_GRANDFATHERED"
            prospective = False
        elif match_at < effective_from:
            applied_policy = {
                "version": RANKING_ELIGIBLE_POLICY_VERSION,
                "config_hash": RANKING_ELIGIBLE_CONFIG_HASH,
            }
            temporal_scope = "V1_INTERVAL_CHANGE_102"
            prospective = False
        else:
            applied_policy = policy
            temporal_scope = "POST_T1_CHANGE_105"
            prospective = True
        classification = classify_match(record, applied_policy)
        return {
            **classification,
            "temporal_scope": temporal_scope,
            "applied_policy_version": applied_policy["version"],
            "prospective_policy_applied": prospective,
            "match_at_utc": match_at.isoformat(),
            "effective_from_utc": effective_from.isoformat(),
            "v1_effective_from_utc": v1_effective_from.isoformat(),
        }

    if match_at < effective_from:
        legacy_policy = {
            "version": LAVER_ONLY_POLICY_VERSION,
            "config_hash": LAVER_ONLY_CONFIG_HASH,
        }
        classification = classify_match(record, legacy_policy)
        return {
            **classification,
            "temporal_scope": "PRE_T0_GRANDFATHERED",
            "applied_policy_version": LAVER_ONLY_POLICY_VERSION,
            "prospective_policy_applied": False,
            "match_at_utc": match_at.isoformat(),
            "effective_from_utc": effective_from.isoformat(),
        }
    classification = classify_match(record, policy)
    return {
        **classification,
        "temporal_scope": "POST_T0_CHANGE_102",
        "applied_policy_version": RANKING_ELIGIBLE_POLICY_VERSION,
        "prospective_policy_applied": True,
        "match_at_utc": match_at.isoformat(),
        "effective_from_utc": effective_from.isoformat(),
    }


def weighted_observations(
    records: Iterable[Mapping[str, Any]], *, active: bool,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify selected match rows once for other match-level aggregators."""
    selected = [dict(record) for record in records if isinstance(record, Mapping)]
    if not active:
        return {
            "records": [(record, 1.0) for record in selected],
            "competition_evidence": None,
        }
    _change, version, config_hash = _policy_contract(policy)
    counts: Counter[str] = Counter()
    classifications: Counter[str] = Counter()
    blockers: Counter[str] = Counter()
    temporal_scopes: Counter[str] = Counter()
    weighted: list[tuple[dict[str, Any], float]] = []
    source_ids: list[str] = []
    for record in selected:
        classification = classify_selected_match(record, policy)
        reason = str(classification["reason_code"])
        counts[reason] += 1
        classifications[str(
            classification.get("classification")
            or classification.get("competition")
            or "UNRESOLVED"
        )] += 1
        temporal_scope = classification.get("temporal_scope")
        if temporal_scope:
            temporal_scopes[str(temporal_scope)] += 1
        weight = classification.get("weight")
        if weight is None:
            blockers[reason] += 1
        else:
            weighted.append((record, float(weight)))
        source_id = _value(
            record, "id", "matchId", "match_id", "eventId", "event_id"
        )
        if source_id is not None:
            source_ids.append(str(source_id))
    blocked = bool(blockers)
    weighted_matches = sum(weight for _record, weight in weighted)
    evidence = {
        "version": version,
        "config_hash": config_hash,
        "status": "BLOCKED" if blocked else "APPLIED",
        "eligible_for_performance": not blocked and weighted_matches > 0,
        "raw_matches": len(selected),
        "weighted_matches": None if blocked else round(weighted_matches, 3),
        "laver_excluded": counts["LAVER_EXCLUDED_FROM_PERFORMANCE"],
        "davis_weighted": counts["DAVIS_TIE_COMPETITIVE_PRE_MATCH"],
        "davis_preserved": counts["DAVIS_CURRENT_PRODUCTION_TREATMENT_PRESERVED"],
        "non_ranking_excluded": classifications["NON_RANKING"],
        "ranking_eligible_included": classifications["RANKING_ELIGIBLE"],
        "davis_exception_included": classifications["DAVIS_EXCEPTION"],
        "next_gen_exception_included": classifications["NEXT_GEN_EXCEPTION"],
        "olympics_exception_included": classifications["OLYMPICS_EXCEPTION"],
        "classification_counts": dict(sorted(classifications.items())),
        "unresolved": sum(blockers.values()),
        "reason_counts": dict(sorted(counts.items())),
        "blocker_reason_counts": dict(sorted(blockers.items())),
        "temporal_scope_counts": dict(sorted(temporal_scopes.items())),
        "grandfathered_pre_t0": temporal_scopes["PRE_T0_GRANDFATHERED"],
        "preserved_v1_interval": temporal_scopes["V1_INTERVAL_CHANGE_102"],
        "prospective_post_t0": temporal_scopes["POST_T0_CHANGE_102"],
        "prospective_post_t1": temporal_scopes["POST_T1_CHANGE_105"],
        "source_match_ids": source_ids,
    }
    return {
        "records": [] if blocked else weighted,
        "competition_evidence": evidence,
    }


def weighted_binary_record(
    records: Iterable[Mapping[str, Any]],
    won: Callable[[Mapping[str, Any]], bool],
    *,
    active: bool,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply weights after sample selection, preserving raw factual counts."""
    selected = [dict(record) for record in records if isinstance(record, Mapping)]
    raw_wins = sum(1 for record in selected if won(record))
    raw_matches = len(selected)
    base = {
        "wins": raw_wins,
        "losses": raw_matches - raw_wins,
        "matches": raw_matches,
    }
    if not active:
        return base

    _change, version, config_hash = _policy_contract(policy)
    weighted_wins = 0.0
    weighted_losses = 0.0
    counts: Counter[str] = Counter()
    classifications: Counter[str] = Counter()
    blockers: Counter[str] = Counter()
    temporal_scopes: Counter[str] = Counter()
    source_ids: list[str] = []
    for record in selected:
        classification = classify_selected_match(record, policy)
        reason = str(classification["reason_code"])
        counts[reason] += 1
        classifications[str(
            classification.get("classification")
            or classification.get("competition")
            or "UNRESOLVED"
        )] += 1
        temporal_scope = classification.get("temporal_scope")
        if temporal_scope:
            temporal_scopes[str(temporal_scope)] += 1
        weight = classification.get("weight")
        if weight is None:
            blockers[reason] += 1
        elif won(record):
            weighted_wins += float(weight)
        else:
            weighted_losses += float(weight)
        source_id = _value(
            record, "id", "matchId", "match_id", "eventId", "event_id"
        )
        if source_id not in (None, ""):
            source_ids.append(str(source_id))

    weighted_matches = weighted_wins + weighted_losses
    blocked = bool(blockers)
    return {
        **base,
        "weighted_wins": None if blocked else round(weighted_wins, 3),
        "weighted_losses": None if blocked else round(weighted_losses, 3),
        "weighted_matches": None if blocked else round(weighted_matches, 3),
        "weighted_win_rate_pct": (
            None
            if blocked or weighted_matches <= 0
            else round(100.0 * weighted_wins / weighted_matches, 1)
        ),
        "competition_evidence": {
            "version": version,
            "config_hash": config_hash,
            "status": "BLOCKED" if blocked else "APPLIED",
            "eligible_for_performance": not blocked and weighted_matches > 0,
            "raw_matches": raw_matches,
            "laver_excluded": counts["LAVER_EXCLUDED_FROM_PERFORMANCE"],
            "davis_weighted": counts["DAVIS_TIE_COMPETITIVE_PRE_MATCH"],
            "davis_preserved": counts["DAVIS_CURRENT_PRODUCTION_TREATMENT_PRESERVED"],
            "non_ranking_excluded": classifications["NON_RANKING"],
            "ranking_eligible_included": classifications["RANKING_ELIGIBLE"],
            "davis_exception_included": classifications["DAVIS_EXCEPTION"],
            "next_gen_exception_included": classifications["NEXT_GEN_EXCEPTION"],
            "olympics_exception_included": classifications["OLYMPICS_EXCEPTION"],
            "classification_counts": dict(sorted(classifications.items())),
            "unresolved": sum(blockers.values()),
            "reason_counts": dict(sorted(counts.items())),
            "blocker_reason_counts": dict(sorted(blockers.items())),
            "temporal_scope_counts": dict(sorted(temporal_scopes.items())),
            "grandfathered_pre_t0": temporal_scopes["PRE_T0_GRANDFATHERED"],
            "preserved_v1_interval": temporal_scopes["V1_INTERVAL_CHANGE_102"],
            "prospective_post_t0": temporal_scopes["POST_T0_CHANGE_102"],
            "prospective_post_t1": temporal_scopes["POST_T1_CHANGE_105"],
            "source_match_ids": source_ids,
        },
    }


def record_rate(
    record: Mapping[str, Any] | None,
) -> tuple[float | None, float | None]:
    """Return decision rate/sample, preferring prospective weighted values."""
    if not isinstance(record, Mapping):
        return None, None
    evidence = record.get("competition_evidence")
    if isinstance(evidence, Mapping):
        if evidence.get("eligible_for_performance") is not True:
            return None, record.get("weighted_matches")
        return record.get("weighted_win_rate_pct"), record.get("weighted_matches")
    matches = record.get("matches")
    wins = record.get("wins")
    try:
        if float(matches) <= 0:
            return None, None
        return 100.0 * float(wins) / float(matches), float(matches)
    except (TypeError, ValueError):
        return None, None


def evidence_is_compatible(record: Mapping[str, Any] | None, policy: Mapping[str, Any] | None = None) -> bool:
    evidence = record.get("competition_evidence") if isinstance(record, Mapping) else None
    _change, version, config_hash = _policy_contract(policy)
    return (
        isinstance(evidence, Mapping)
        and evidence.get("version") == version
        and evidence.get("config_hash") == config_hash
        and evidence.get("eligible_for_performance") is True
    )


def annotate_feature(
    feature: dict[str, Any] | None,
    sources: Iterable[Mapping[str, Any] | None],
    *,
    active: bool,
    policy: Mapping[str, Any] | None = None,
) -> None:
    """Attach factor-local eligibility without removing factual feature data."""
    if not active or not isinstance(feature, dict):
        return
    _change, version, config_hash = _policy_contract(policy)
    source_list = list(sources)
    eligible = bool(source_list) and all(
        evidence_is_compatible(source, policy) for source in source_list
    )
    feature["competition_evidence"] = {
        "version": version,
        "config_hash": config_hash,
        "eligible_for_performance": eligible,
        "reason_code": (
            "MATCH_LEVEL_COMPETITION_EVIDENCE_APPLIED"
            if eligible
            else "COMPETITION_EVIDENCE_NOT_SEPARABLE"
        ),
    }


def feature_is_eligible(feature: Any, *, active: bool, policy: Mapping[str, Any] | None = None) -> bool:
    if not active:
        return True
    evidence = feature.get("competition_evidence") if isinstance(feature, Mapping) else None
    _change, version, config_hash = _policy_contract(policy)
    return (
        isinstance(evidence, Mapping)
        and evidence.get("version") == version
        and evidence.get("config_hash") == config_hash
        and evidence.get("eligible_for_performance") is True
    )


def policy_metadata(activation: Mapping[str, Any]) -> dict[str, Any]:
    """Build immutable provenance copied to new payload/snapshot/PAPER."""
    result = dict(activation)
    if is_laver_only(result):
        result["weights"] = {
            "individual_reference": 1.0,
            "davis_current_production_treatment": 1.0,
            "laver": 0.0,
        }
        result["policy_mode"] = "LAVER_ONLY"
    elif is_ranking_eligible_v2(result):
        result["weights"] = {
            "ranking_eligible": 1.0,
            "davis_exception": 0.5,
            "next_gen_exception": 0.5,
            "olympics_exception": 0.5,
            "non_ranking": 0.0,
            "unresolved": None,
        }
        result["policy_mode"] = "ATP_RANKING_ELIGIBLE_50"
        result["registry_version"] = RANKING_REGISTRY_VERSION
        result["registry_sha256"] = RANKING_REGISTRY_SHA256
        result["registry_factual_taxonomy_reused"] = True
        result["temporal_application"] = "PER_MATCH_T1_DELTA"
        result["pre_t0_policy_version"] = LAVER_ONLY_POLICY_VERSION
        result["intermediate_policy_version"] = RANKING_ELIGIBLE_POLICY_VERSION
        result["post_t1_policy_version"] = RANKING_ELIGIBLE_V2_POLICY_VERSION
        result["v1_effective_from_utc"] = RANKING_ELIGIBLE_V1_EFFECTIVE_FROM_UTC
        result["historical_reclassification"] = False
    elif is_ranking_eligible(result):
        result["weights"] = {
            "ranking_eligible": 1.0,
            "davis_exception": 1.0,
            "next_gen_exception": 1.0,
            "olympics_exception": 1.0,
            "non_ranking": 0.0,
            "unresolved": None,
        }
        result["policy_mode"] = "ATP_RANKING_ELIGIBLE"
        result["registry_version"] = RANKING_REGISTRY_VERSION
        result["registry_sha256"] = RANKING_REGISTRY_SHA256
        result["temporal_application"] = "PER_MATCH_T0_DELTA"
        result["pre_t0_policy_version"] = LAVER_ONLY_POLICY_VERSION
        result["post_t0_policy_version"] = RANKING_ELIGIBLE_POLICY_VERSION
        result["historical_reclassification"] = False
    else:
        result["weights"] = {
            "individual_reference": 1.0,
            "davis_competitive": 0.5,
            "laver": 0.0,
            "davis_decided": None,
            "davis_unknown": None,
        }
        result["policy_mode"] = "DAVIS_LAVER"
    result["same_sample_before_weighting"] = True
    result["fatigue_load_unweighted"] = True
    result["integral_laver_exclusion_claimed"] = (
        is_active_laver_only(result) or is_active_ranking_eligible(result)
    )
    result["integral_non_ranking_exclusion_claimed"] = (
        is_active_ranking_eligible(result)
    )
    result["known_blockers"] = list(INSEPARABLE_SOURCE_BLOCKERS)
    result["separability_contract"] = "FACTOR_LOCAL_MATCH_LEVEL_PROVENANCE"
    return result


def direct_consumers_from_payload(payload: Mapping[str, Any]) -> set[str]:
    """Identify direct report consumers only when their factual source exists."""
    consumers: set[str] = set()
    rich_a = payload.get("rich_stats_a")
    rich_b = payload.get("rich_stats_b")
    scenarios_present = any(
        isinstance((rich or {}).get("scenarios"), Mapping)
        and bool((rich or {}).get("scenarios"))
        for rich in (rich_a, rich_b)
        if isinstance(rich, Mapping)
    )
    if scenarios_present or payload.get("deciding_set_stats_a") or payload.get(
        "deciding_set_stats_b"
    ):
        consumers.add("recuperacao_sets")
    if scenarios_present:
        consumers.add("comeback_set1")
    if payload.get("handedness_matchup_a") or payload.get(
        "handedness_matchup_b"
    ):
        consumers.add("matchup_maos")
    if payload.get("tournament_record_a") or payload.get("tournament_record_b"):
        consumers.add("historico_torneio")
    return consumers


def guard_features(
    features: Mapping[str, Any],
    *,
    active: bool,
    tour: str | None = None,
    direct_consumers: Iterable[str] = (),
    policy: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Audit factor-local provenance while preserving all factual features."""
    output = dict(features)
    if not active or (tour is not None and str(tour).casefold() != "atp"):
        return output, []
    blockers = []
    audited_keys = (
        RESULT_DERIVED_FEATURE_KEYS.intersection(output)
        | DIRECT_UNSEPARABLE_CONSUMERS.intersection(direct_consumers)
    )
    for key in sorted(audited_keys):
        if not feature_is_eligible(output.get(key), active=True, policy=policy):
            blockers.append({
                "feature": key,
                "impact": "DECISION_FACTOR_BLOCKED",
                "reason_code": "COMPETITION_EVIDENCE_NOT_SEPARABLE",
            })
    return output, blockers


def factor_impact_matrix(
    features: Mapping[str, Any],
    *,
    active: bool,
    tour: str | None,
    direct_consumers: Iterable[str] = (),
    policy: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return the auditable separability/impact matrix for this payload."""
    _, blockers = guard_features(
        features,
        active=active,
        tour=tour,
        direct_consumers=direct_consumers,
        policy=policy,
    )
    blocked = {item["feature"]: item for item in blockers}
    matrix = []
    audited_keys = (
        RESULT_DERIVED_FEATURE_KEYS.intersection(features)
        | DIRECT_UNSEPARABLE_CONSUMERS.intersection(direct_consumers)
    )
    for key in sorted(audited_keys):
        if key in blocked:
            matrix.append({
                **blocked[key],
                "separability": "UNAVAILABLE",
                "report_factual_display": "PRESERVED",
            })
        else:
            matrix.append({
                "feature": key,
                "separability": "MATCH_LEVEL",
                "impact": "DECISION_FACTOR_ELIGIBLE",
                "reason_code": "MATCH_LEVEL_COMPETITION_EVIDENCE_APPLIED",
                "report_factual_display": "PRESERVED",
            })
    return matrix



def canonical_cutover_gate(
    identity: Mapping[str, Any],
    *,
    activation: Mapping[str, Any],
    tour: str | None,
    tournament_id: Any,
    player_ids: Iterable[Any],
    persisted_snapshot: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Decide policy eligibility from canonical identity before new decisions.

    Schedule, odds and A/B orientation are intentionally absent from this
    comparison. They may change on rerun without creating a new match instance.
    """
    canonical_id = str(identity.get("canonical_match_instance_id") or "")
    if activation.get("active") is not True or str(tour or "").casefold() != "atp":
        return {"status": "POLICY_NOT_APPLICABLE", "apply_policy": False}
    if not canonical_id or identity.get("identity_persisted") is not True:
        return {
            "status": "CANONICAL_IDENTITY_UNAVAILABLE",
            "apply_policy": False,
            "reason_code": "COMPETITION_POLICY_REQUIRES_CANONICAL_IDENTITY",
        }
    if not isinstance(persisted_snapshot, Mapping):
        return {
            "status": "NEW_CANONICAL_MATCH",
            "apply_policy": True,
            "canonical_match_instance_id": canonical_id,
        }

    persisted_id = str(
        persisted_snapshot.get("canonical_match_instance_id")
        or persisted_snapshot.get("key")
        or ""
    )
    current_players = frozenset(
        str(value) for value in player_ids if value not in (None, "")
    )
    persisted_players = frozenset(
        str((persisted_snapshot.get(side) or {}).get("id"))
        for side in ("player_a", "player_b")
        if (persisted_snapshot.get(side) or {}).get("id") not in (None, "")
    )
    context_matches = (
        persisted_id == canonical_id
        and current_players == persisted_players
        and str(tour or "").casefold()
        == str(persisted_snapshot.get("tour") or "").casefold()
        and str(tournament_id) == str(persisted_snapshot.get("tournament_id"))
    )
    if context_matches:
        persisted_policy = persisted_snapshot.get("competition_evidence_policy")
        recovery = persisted_snapshot.get("delivery_recovery")
        _change, version, config_hash = _policy_contract(activation)
        same_policy = (
            isinstance(persisted_policy, Mapping)
            and persisted_policy.get("version") == version
            and persisted_policy.get("config_hash") == config_hash
        )
        if same_policy and isinstance(recovery, Mapping):
            return {
                "status": "RECOVER_FROZEN_FIRST_DELIVERY",
                "apply_policy": False,
                "recover_frozen_delivery": True,
                "canonical_match_instance_id": canonical_id,
                "persisted_report_id": persisted_snapshot.get("report_id"),
                "reason_code": "POST_CUTOVER_DELIVERY_RECOVERY",
            }
        return {
            "status": "PRESERVE_EXISTING_CANONICAL_DECISION",
            "apply_policy": False,
            "skip_new_decision": True,
            "canonical_match_instance_id": canonical_id,
            "persisted_report_id": persisted_snapshot.get("report_id"),
            "reason_code": "CANONICAL_MATCH_ALREADY_HAS_PREGAME_SNAPSHOT",
        }
    return {
        "status": "CANONICAL_CONTEXT_COLLISION",
        "apply_policy": False,
        "fail_closed": True,
        "canonical_match_instance_id": canonical_id,
        "reason_code": "CANONICAL_MATCH_INSTANCE_CONTEXT_CONFLICT",
    }


def derived_cache_scope(
    base_key: str, activation: Mapping[str, Any]
) -> str:
    """Version derived caches without invalidating raw factual caches."""
    if activation.get("active") is True:
        _change, version, config_hash = _policy_contract(activation)
        return f"{base_key}:{version}:{config_hash}"
    return base_key
