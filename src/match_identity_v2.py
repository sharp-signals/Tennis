"""Canonical match-instance identity v2.

CHANGE-2026-09-21-049 introduces a prospective, stateful mint-once registry.
Provider identifiers, scheduling and presentation metadata are evidence only;
they never become the canonical identifier itself.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = 2
CHANGE_ID = "CHANGE-2026-09-21-049"
DEFAULT_REGISTRY_PATH = Path("data/match_identity/registry-v2.json")
DEFAULT_EVENTS_PATH = Path("data/match_identity/events-v2.jsonl")

CANONICAL_STRONG = "CANONICAL_STRONG"
CANONICAL_RESOLVED = "CANONICAL_RESOLVED"
IDENTITY_PROVISIONAL = "IDENTITY_PROVISIONAL"
IDENTITY_INSUFFICIENT = "IDENTITY_INSUFFICIENT"
IDENTITY_CONFLICT = "IDENTITY_CONFLICT"
CANONICAL_STATES = {CANONICAL_STRONG, CANONICAL_RESOLVED}
EVENT_VALIDATION_PLAYER_IDS = "PLAYER_IDS"
EVENT_VALIDATION_STRUCTURAL_MATCH_ID = "STRUCTURAL_MATCH_ID"
EVENT_VALIDATION_EXACT_NAMES = "EXACT_NAMES"
_STRONG_EVENT_VALIDATION_BASES = {
    EVENT_VALIDATION_PLAYER_IDS,
    EVENT_VALIDATION_STRUCTURAL_MATCH_ID,
}

ALIAS_EVENT_ID = "EVENT_ID"
ALIAS_MATCH_ID = "MATCH_ID"
ALIAS_ACTIVE = "ACTIVE"
ALIAS_CONFLICTED = "CONFLICTED"
ALIAS_RETIRED = "RETIRED"

_LOCK = threading.RLock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _empty_registry() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "change_id": CHANGE_ID,
        "activation": {
            "mode": "PROSPECTIVE_FIRST_POST_MERGE_OBSERVATION",
            "first_observed_at_utc": None,
            "runtime_sha": None,
            "github_run_id": None,
        },
        "instances": [],
        "aliases": [],
        "updated_at_utc": None,
    }


def _read_registry(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _empty_registry()
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"identity_registry_unreadable:{type(exc).__name__}") from exc
    if (
        not isinstance(value, Mapping)
        or value.get("schema_version") != SCHEMA_VERSION
        or not isinstance(value.get("instances"), list)
        or not isinstance(value.get("aliases"), list)
    ):
        raise ValueError("identity_registry_schema_invalid")
    return copy.deepcopy(dict(value))


def read_registry(path: Path = DEFAULT_REGISTRY_PATH) -> dict[str, Any]:
    """Return a defensive copy of the operational registry."""
    with _LOCK:
        return _read_registry(path)


def _write_registry(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def _append_events(path: Path, events: list[Mapping[str, Any]]) -> None:
    if not events:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(dict(event), ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _value(observation: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = observation.get(key)
        if value not in (None, ""):
            return value
    return None


def _player(observation: Mapping[str, Any], side: str) -> tuple[Any, str]:
    number = "1" if side == "a" else "2"
    nested = observation.get(f"player{number}")
    nested = nested if isinstance(nested, Mapping) else {}
    player_id = _value(observation, f"player_{side}_id", f"player{number}Id")
    if player_id in (None, ""):
        player_id = nested.get("id")
    name = str(_value(observation, f"player_{side}") or nested.get("name") or "").strip()
    return player_id, name


def _canonical_player_ids(observation: Mapping[str, Any]) -> tuple[str, str] | None:
    player_a_id, _ = _player(observation, "a")
    player_b_id, _ = _player(observation, "b")
    if player_a_id in (None, "") or player_b_id in (None, ""):
        return None
    return tuple(sorted((str(player_a_id), str(player_b_id))))


def _is_doubles(observation: Mapping[str, Any]) -> bool:
    _, name_a = _player(observation, "a")
    _, name_b = _player(observation, "b")
    return "/" in name_a or "/" in name_b


def legacy_key(observation: Mapping[str, Any]) -> str | None:
    tour = str(_value(observation, "tour", "_tour") or "").strip().lower()
    match_id = _value(observation, "match_id", "id")
    return f"{tour}:{match_id}" if tour and match_id not in (None, "") else None


def _structure(observation: Mapping[str, Any]) -> dict[str, Any] | None:
    tour = str(_value(observation, "tour", "_tour") or "").strip().lower()
    tournament_id = _value(observation, "tournament_id", "tournamentId")
    players = _canonical_player_ids(observation)
    if not tour or tournament_id in (None, "") or players is None:
        return None
    return {
        "tour": tour,
        "tournament_id": str(tournament_id),
        "player_ids": list(players),
    }


def _structure_matches(instance: Mapping[str, Any], structure: Mapping[str, Any]) -> bool:
    return (
        str(instance.get("tour") or "").lower() == structure["tour"]
        and str(instance.get("tournament_id")) == structure["tournament_id"]
        and list(instance.get("player_ids") or []) == structure["player_ids"]
    )


def _fingerprint(structure: Mapping[str, Any], evidence: Mapping[str, Any]) -> str:
    material = {"structure": dict(structure), "evidence": dict(evidence)}
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _event(
    event_type: str,
    *,
    observed_at: str,
    result: Mapping[str, Any],
    runtime: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "change_id": CHANGE_ID,
        "event_type": event_type,
        "observed_at_utc": observed_at,
        "canonical_match_instance_id": result.get("canonical_match_instance_id"),
        "identity_status": result.get("identity_status"),
        "reason_code": result.get("identity_reason_code"),
        "legacy_key": result.get("legacy_key"),
        "evidence_fingerprint": (result.get("identity_evidence") or {}).get("fingerprint"),
        "runtime_sha": runtime.get("runtime_sha"),
        "github_run_id": runtime.get("github_run_id"),
    }


def _result(
    status: str,
    reason: str,
    *,
    canonical_id: str | None,
    legacy: str | None,
    structure: Mapping[str, Any] | None,
    evidence: Mapping[str, Any],
    persisted: bool,
) -> dict[str, Any]:
    audit_evidence = dict(evidence)
    if structure:
        audit_evidence["structure"] = copy.deepcopy(dict(structure))
        audit_evidence["fingerprint"] = _fingerprint(structure, evidence)
    return {
        "identity_schema_version": SCHEMA_VERSION,
        "canonical_match_instance_id": canonical_id,
        "identity_status": status,
        "identity_reason_code": reason,
        "legacy_key": legacy,
        "identity_evidence": audit_evidence,
        "identity_persisted": persisted,
    }


def is_canonical(result: Mapping[str, Any]) -> bool:
    return (
        result.get("identity_schema_version") == SCHEMA_VERSION
        and result.get("identity_status") in CANONICAL_STATES
        and bool(result.get("canonical_match_instance_id"))
        and result.get("identity_persisted") is True
    )


def event_id_is_strong_identity_evidence(provenance: Mapping[str, Any]) -> bool:
    """Require an event ID and an explicit structural validation basis.

    Pricing may independently accept a generic ``VERIFIED`` mapping produced
    from exact names. Canonical identity v2 is deliberately stricter: generic
    mapping status, textual aliases and names plus time are never strong.
    """
    if not isinstance(provenance, Mapping) or not provenance.get("event_id"):
        return False
    basis = str(
        provenance.get("event_identity_validation_basis") or ""
    ).strip().upper()
    return basis in _STRONG_EVENT_VALIDATION_BASES


def _aliases(
    registry: Mapping[str, Any], alias_type: str, alias_value: str,
    provider: str | None = None,
) -> list[dict[str, Any]]:
    return [
        row for row in registry.get("aliases", [])
        if isinstance(row, dict)
        and row.get("alias_type") == alias_type
        and str(row.get("alias_value")) == alias_value
        and (provider is None or str(row.get("provider")) == provider)
        and row.get("status") != ALIAS_RETIRED
    ]


def _instances(registry: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("canonical_match_instance_id")): row
        for row in registry.get("instances", [])
        if isinstance(row, dict) and row.get("canonical_match_instance_id")
    }


def _touch_instance(instances: Mapping[str, dict[str, Any]], canonical_id: str, observed_at: str) -> None:
    instance = instances.get(canonical_id)
    if instance is not None:
        instance["last_observed_at_utc"] = observed_at


def _instance_round_ids(instance: Mapping[str, Any]) -> set[str]:
    return {
        str(value) for value in instance.get("round_ids", [])
        if value not in (None, "")
    }


def _round_is_compatible(instance: Mapping[str, Any], round_value: str | None) -> bool:
    known = _instance_round_ids(instance)
    return not round_value or not known or round_value in known


def _bind_round(instance: dict[str, Any], round_value: str | None) -> bool:
    if not round_value:
        return False
    known = _instance_round_ids(instance)
    if round_value in known:
        return False
    if known:
        raise ValueError("round_evidence_conflict")
    instance["round_ids"] = [round_value]
    return True


def _active_event_aliases(
    registry: Mapping[str, Any], canonical_id: str, provider: str,
) -> list[dict[str, Any]]:
    return [
        row for row in registry.get("aliases", [])
        if isinstance(row, dict)
        and row.get("alias_type") == ALIAS_EVENT_ID
        and row.get("canonical_match_instance_id") == canonical_id
        and row.get("status") == ALIAS_ACTIVE
        and str(row.get("provider")) == provider
    ]


def _strong_evidence_is_compatible(
    registry: Mapping[str, Any], instance: Mapping[str, Any], *,
    canonical_id: str, provider: str, event_value: str | None,
    event_id_validated: bool, round_value: str | None,
) -> bool:
    if not _round_is_compatible(instance, round_value):
        return False
    if event_value and event_id_validated:
        existing_events = _active_event_aliases(registry, canonical_id, provider)
        if existing_events and all(
            str(row.get("alias_value")) != event_value for row in existing_events
        ):
            return False
    return True


def _bind_alias(
    registry: dict[str, Any], *, alias_type: str, alias_value: str,
    canonical_id: str, provider: str, observed_at: str, fingerprint: str,
) -> bool:
    for row in registry["aliases"]:
        if (
            row.get("alias_type") == alias_type
            and str(row.get("alias_value")) == alias_value
            and str(row.get("provider")) == provider
            and row.get("canonical_match_instance_id") == canonical_id
        ):
            row["last_observed_at_utc"] = observed_at
            return False
    registry["aliases"].append({
        "provider": provider,
        "alias_type": alias_type,
        "alias_value": alias_value,
        "canonical_match_instance_id": canonical_id,
        "first_observed_at_utc": observed_at,
        "last_observed_at_utc": observed_at,
        "status": ALIAS_ACTIVE,
        "evidence_fingerprint": fingerprint,
    })
    return True


def _mark_alias_conflict(rows: list[dict[str, Any]], observed_at: str) -> None:
    for row in rows:
        row["status"] = ALIAS_CONFLICTED
        row["last_observed_at_utc"] = observed_at


def _resolve_locked(
    registry: dict[str, Any], observation: Mapping[str, Any], *,
    event_id: str | None, event_id_validated: bool, provider: str,
    observed_at: str, allow_mint: bool,
) -> tuple[dict[str, Any], bool, list[str]]:
    legacy = legacy_key(observation)
    structure = _structure(observation)
    round_id = _value(observation, "round_id", "roundId")
    match_id = _value(observation, "match_id", "id")
    evidence = {
        "provider": provider,
        "event_id": str(event_id) if event_id not in (None, "") else None,
        "event_id_bilaterally_validated": bool(event_id and event_id_validated),
        "match_id": str(match_id) if match_id not in (None, "") else None,
        "round_id": str(round_id) if round_id not in (None, "") else None,
        "scheduled_start_utc": _value(observation, "commence_time_utc", "date"),
        "orientation": {
            "a": _player(observation, "a")[0],
            "b": _player(observation, "b")[0],
        },
    }
    if _is_doubles(observation):
        return _result(
            IDENTITY_INSUFFICIENT, "UNSUPPORTED_DOUBLES_IDENTITY_V2",
            canonical_id=None, legacy=legacy, structure=structure,
            evidence=evidence, persisted=False,
        ), False, ["IDENTITY_INSUFFICIENT"]
    if structure is None:
        return _result(
            IDENTITY_INSUFFICIENT, "STRUCTURAL_MINIMUM_UNAVAILABLE",
            canonical_id=None, legacy=legacy, structure=None,
            evidence=evidence, persisted=False,
        ), False, ["IDENTITY_INSUFFICIENT"]

    instances = _instances(registry)
    event_value = str(event_id) if event_id not in (None, "") else None
    match_value = str(match_id) if match_id not in (None, "") else None
    round_value = str(round_id) if round_id not in (None, "") else None

    if event_value and event_id_validated:
        bindings = _aliases(registry, ALIAS_EVENT_ID, event_value, provider)
        compatible = {
            str(row.get("canonical_match_instance_id")) for row in bindings
            if row.get("status") == ALIAS_ACTIVE
            and str(row.get("canonical_match_instance_id")) in instances
            and _structure_matches(instances[str(row.get("canonical_match_instance_id"))], structure)
        }
        if bindings and (len(compatible) != 1 or len(compatible) != len({
            str(row.get("canonical_match_instance_id")) for row in bindings
            if row.get("status") == ALIAS_ACTIVE
        })):
            _mark_alias_conflict(bindings, observed_at)
            return _result(
                IDENTITY_CONFLICT, "EVENT_ID_STRUCTURAL_CONFLICT",
                canonical_id=None, legacy=legacy, structure=structure,
                evidence=evidence, persisted=False,
            ), True, ["ALIAS_CONFLICT", "IDENTITY_CONFLICT"]
        if len(compatible) == 1:
            canonical_id = next(iter(compatible))
            instance = instances[canonical_id]
            if not _round_is_compatible(instance, round_value):
                _mark_alias_conflict(bindings, observed_at)
                return _result(
                    IDENTITY_CONFLICT, "EVENT_ID_ROUND_EVIDENCE_CONFLICT",
                    canonical_id=None, legacy=legacy, structure=structure,
                    evidence=evidence, persisted=False,
                ), True, ["ALIAS_CONFLICT", "IDENTITY_CONFLICT"]
            _touch_instance(instances, canonical_id, observed_at)
            fingerprint = _fingerprint(structure, evidence)
            added = False
            round_added = _bind_round(instance, round_value)
            if match_value:
                added = _bind_alias(
                    registry, alias_type=ALIAS_MATCH_ID, alias_value=match_value,
                    canonical_id=canonical_id, provider=provider,
                    observed_at=observed_at, fingerprint=fingerprint,
                )
            result = _result(
                CANONICAL_RESOLVED, "EVENT_ID_ALIAS_MATCH",
                canonical_id=canonical_id, legacy=legacy, structure=structure,
                evidence=evidence, persisted=True,
            )
            return result, True, (
                (["ROUND_EVIDENCE_BOUND"] if round_added else [])
                + (["ALIAS_BOUND"] if added else [])
                + ["OBSERVATION_RESOLVED"]
            )

    # ROUND_ID is strong only inside the bilateral structural scope. It is
    # resolved before the weak MATCH_ID so a reused provider ID can never
    # override contradictory factual round evidence.
    if round_value:
        round_candidates = [
            row for row in instances.values()
            if _structure_matches(row, structure)
            and round_value in _instance_round_ids(row)
        ]
        if len(round_candidates) > 1:
            return _result(
                IDENTITY_CONFLICT, "ROUND_ID_MULTIPLE_COMPATIBLE_INSTANCES",
                canonical_id=None, legacy=legacy, structure=structure,
                evidence=evidence, persisted=False,
            ), False, ["IDENTITY_CONFLICT"]
        if len(round_candidates) == 1:
            candidate = round_candidates[0]
            canonical_id = str(candidate["canonical_match_instance_id"])
            if not _strong_evidence_is_compatible(
                registry, candidate, canonical_id=canonical_id, provider=provider,
                event_value=event_value, event_id_validated=event_id_validated,
                round_value=round_value,
            ):
                return _result(
                    IDENTITY_CONFLICT, "ROUND_EVENT_STRONG_EVIDENCE_CONFLICT",
                    canonical_id=None, legacy=legacy, structure=structure,
                    evidence=evidence, persisted=False,
                ), False, ["IDENTITY_CONFLICT"]
            fingerprint = _fingerprint(structure, evidence)
            event_added = False
            match_added = False
            if event_value and event_id_validated:
                event_added = _bind_alias(
                    registry, alias_type=ALIAS_EVENT_ID, alias_value=event_value,
                    canonical_id=canonical_id, provider=provider,
                    observed_at=observed_at, fingerprint=fingerprint,
                )
            if match_value:
                match_added = _bind_alias(
                    registry, alias_type=ALIAS_MATCH_ID, alias_value=match_value,
                    canonical_id=canonical_id, provider=provider,
                    observed_at=observed_at, fingerprint=fingerprint,
                )
            _touch_instance(instances, canonical_id, observed_at)
            return _result(
                CANONICAL_RESOLVED, "ROUND_ID_STRUCTURAL_MATCH",
                canonical_id=canonical_id, legacy=legacy, structure=structure,
                evidence=evidence, persisted=True,
            ), True, (
                (["ALIAS_BOUND"] if event_added or match_added else [])
                + ["OBSERVATION_RESOLVED"]
            )

    if match_value:
        bindings = _aliases(registry, ALIAS_MATCH_ID, match_value, provider)
        compatible = {
            str(row.get("canonical_match_instance_id")) for row in bindings
            if row.get("status") == ALIAS_ACTIVE
            and str(row.get("canonical_match_instance_id")) in instances
            and _structure_matches(instances[str(row.get("canonical_match_instance_id"))], structure)
            and _strong_evidence_is_compatible(
                registry,
                instances[str(row.get("canonical_match_instance_id"))],
                canonical_id=str(row.get("canonical_match_instance_id")),
                provider=provider,
                event_value=event_value,
                event_id_validated=event_id_validated,
                round_value=round_value,
            )
        }
        if len(compatible) > 1:
            _mark_alias_conflict(bindings, observed_at)
            return _result(
                IDENTITY_CONFLICT, "MATCH_ID_MULTIPLE_COMPATIBLE_INSTANCES",
                canonical_id=None, legacy=legacy, structure=structure,
                evidence=evidence, persisted=False,
            ), True, ["ALIAS_CONFLICT", "IDENTITY_CONFLICT"]
        if len(compatible) == 1:
            canonical_id = next(iter(compatible))
            instance = instances[canonical_id]
            fingerprint = _fingerprint(structure, evidence)
            added = False
            novel_strong_event = False
            if event_value and event_id_validated:
                existing_events = [
                    row for row in registry["aliases"]
                    if row.get("alias_type") == ALIAS_EVENT_ID
                    and row.get("canonical_match_instance_id") == canonical_id
                    and row.get("status") == ALIAS_ACTIVE
                    and str(row.get("provider")) == provider
                ]
                if not existing_events or any(str(row.get("alias_value")) == event_value for row in existing_events):
                    added = _bind_alias(
                        registry, alias_type=ALIAS_EVENT_ID, alias_value=event_value,
                        canonical_id=canonical_id, provider=provider,
                        observed_at=observed_at, fingerprint=fingerprint,
                    )
                else:
                    # MATCH_ID is weak and reusable. A new validated EVENT_ID
                    # for the same pair/tournament is evidence of a distinct
                    # instance, not permission to overwrite or quarantine the
                    # earlier binding. Continue to the strong mint path.
                    novel_strong_event = True
            if not novel_strong_event:
                round_added = _bind_round(instance, round_value)
                _touch_instance(instances, canonical_id, observed_at)
                result = _result(
                    CANONICAL_RESOLVED, "MATCH_ID_ALIAS_WITH_STRUCTURAL_MATCH",
                    canonical_id=canonical_id, legacy=legacy, structure=structure,
                    evidence=evidence, persisted=True,
                )
                return result, True, (
                    (["ROUND_EVIDENCE_BOUND"] if round_added else [])
                    + (["ALIAS_BOUND"] if added else [])
                    + ["OBSERVATION_RESOLVED"]
                )

    structural_instances = [
        row for row in instances.values() if _structure_matches(row, structure)
    ]
    if event_value and event_id_validated and len(structural_instances) == 1:
        candidate = structural_instances[0]
        canonical_id = str(candidate["canonical_match_instance_id"])
        existing_events = _active_event_aliases(registry, canonical_id, provider)
        if not existing_events and _round_is_compatible(candidate, round_value):
            _touch_instance(instances, canonical_id, observed_at)
            fingerprint = _fingerprint(structure, evidence)
            round_added = _bind_round(candidate, round_value)
            _bind_alias(
                registry, alias_type=ALIAS_EVENT_ID, alias_value=event_value,
                canonical_id=canonical_id, provider=provider,
                observed_at=observed_at, fingerprint=fingerprint,
            )
            if match_value:
                _bind_alias(
                    registry, alias_type=ALIAS_MATCH_ID, alias_value=match_value,
                    canonical_id=canonical_id, provider=provider,
                    observed_at=observed_at, fingerprint=fingerprint,
                )
            return _result(
                CANONICAL_RESOLVED, "EVENT_ID_ENRICHES_UNIQUE_STRUCTURAL_INSTANCE",
                canonical_id=canonical_id, legacy=legacy, structure=structure,
                evidence=evidence, persisted=True,
            ), True, (
                (["ROUND_EVIDENCE_BOUND"] if round_added else [])
                + ["ALIAS_BOUND", "OBSERVATION_RESOLVED"]
            )

    strong = bool(event_value and event_id_validated) or round_id not in (None, "")
    if not allow_mint:
        return _result(
            IDENTITY_PROVISIONAL, "NO_EXISTING_CANONICAL_INSTANCE",
            canonical_id=None, legacy=legacy, structure=structure,
            evidence=evidence, persisted=False,
        ), False, ["IDENTITY_PROVISIONAL"]
    if not strong:
        reason = "EVENT_ID_UNVERIFIED" if event_value else "STRONG_DISCRIMINATOR_UNAVAILABLE"
        return _result(
            IDENTITY_PROVISIONAL, reason,
            canonical_id=None, legacy=legacy, structure=structure,
            evidence=evidence, persisted=False,
        ), False, ["IDENTITY_PROVISIONAL"]

    canonical_id = "mi2_" + uuid.uuid4().hex
    fingerprint = _fingerprint(structure, evidence)
    registry["instances"].append({
        "canonical_match_instance_id": canonical_id,
        "created_at_utc": observed_at,
        "last_observed_at_utc": observed_at,
        "status": "ACTIVE",
        **copy.deepcopy(structure),
        "strong_discriminator": "EVENT_ID" if event_value and event_id_validated else "ROUND_ID",
        "round_ids": [round_value] if round_value else [],
        "evidence_fingerprint": fingerprint,
    })
    event_types = ["INSTANCE_MINTED"]
    if event_value and event_id_validated:
        _bind_alias(
            registry, alias_type=ALIAS_EVENT_ID, alias_value=event_value,
            canonical_id=canonical_id, provider=provider,
            observed_at=observed_at, fingerprint=fingerprint,
        )
        event_types.append("ALIAS_BOUND")
    if match_value:
        _bind_alias(
            registry, alias_type=ALIAS_MATCH_ID, alias_value=match_value,
            canonical_id=canonical_id, provider=provider,
            observed_at=observed_at, fingerprint=fingerprint,
        )
        event_types.append("ALIAS_BOUND")
    result = _result(
        CANONICAL_STRONG,
        "MINTED_WITH_VALIDATED_EVENT_ID" if event_value and event_id_validated else "MINTED_WITH_FACTUAL_ROUND_ID",
        canonical_id=canonical_id, legacy=legacy, structure=structure,
        evidence=evidence, persisted=True,
    )
    return result, True, event_types


def resolve_observation(
    observation: Mapping[str, Any], *, event_id: Any = None,
    event_id_validated: bool = False, provider: str = "RapidAPI",
    observed_at_utc: str | None = None,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    events_path: Path = DEFAULT_EVENTS_PATH,
    runtime_metadata: Mapping[str, Any] | None = None,
    allow_mint: bool = True,
) -> dict[str, Any]:
    """Resolve or mint one instance, atomically and fail-closed on persistence errors."""
    observed_at = observed_at_utc or _utc_now()
    runtime = {
        "runtime_sha": (runtime_metadata or {}).get("runtime_sha") or os.environ.get("GITHUB_SHA"),
        "github_run_id": (runtime_metadata or {}).get("github_run_id") or os.environ.get("GITHUB_RUN_ID"),
    }
    with _LOCK:
        previous_registry: dict[str, Any] | None = None
        registry_written = False
        registry_existed = False
        rollback_path: Path | None = None
        try:
            previous_registry = _read_registry(registry_path)
            registry = copy.deepcopy(previous_registry)
            result, changed, event_types = _resolve_locked(
                registry, observation, event_id=str(event_id) if event_id not in (None, "") else None,
                event_id_validated=event_id_validated, provider=provider,
                observed_at=observed_at, allow_mint=allow_mint,
            )
            activation = registry.setdefault("activation", {})
            activation_changed = not activation.get("first_observed_at_utc")
            if activation_changed:
                activation.update({
                    "mode": "PROSPECTIVE_FIRST_POST_MERGE_OBSERVATION",
                    "first_observed_at_utc": observed_at,
                    **runtime,
                })
            if changed or activation_changed:
                registry["updated_at_utc"] = observed_at
                registry_existed = registry_path.exists()
                if registry_existed:
                    rollback_path = registry_path.with_name(
                        f".{registry_path.name}.{os.getpid()}."
                        f"{threading.get_ident()}.rollback"
                    )
                    _write_registry(rollback_path, previous_registry)
                _write_registry(registry_path, registry)
                registry_written = True
            events = [
                _event(kind, observed_at=observed_at, result=result, runtime=runtime)
                for kind in event_types
            ]
            _append_events(events_path, events)
            if rollback_path is not None:
                rollback_path.unlink(missing_ok=True)
            if result.get("canonical_match_instance_id"):
                result["identity_persisted"] = True
            return result
        except Exception as exc:
            # The registry is the usable projection and the JSONL is its
            # audit proof. If append fails after a successful projection
            # write, restore the pre-call projection before returning a
            # non-canonical result. A machine crash at the exact boundary
            # between these local fsync operations remains documented risk.
            if registry_written and previous_registry is not None:
                try:
                    if rollback_path is not None and rollback_path.exists():
                        os.replace(rollback_path, registry_path)
                    elif not registry_existed:
                        registry_path.unlink(missing_ok=True)
                except Exception:
                    pass
            if rollback_path is not None:
                try:
                    rollback_path.unlink(missing_ok=True)
                except OSError:
                    pass
            return _result(
                IDENTITY_INSUFFICIENT,
                f"IDENTITY_REGISTRY_PERSISTENCE_FAILED:{type(exc).__name__}",
                canonical_id=None, legacy=legacy_key(observation),
                structure=_structure(observation),
                evidence={"provider": provider}, persisted=False,
            )


def resolve_existing(
    observation: Mapping[str, Any], expected_canonical_id: str, *,
    event_id: Any = None, event_id_validated: bool = False,
    provider: str = "RapidAPI", registry_path: Path = DEFAULT_REGISTRY_PATH,
) -> dict[str, Any]:
    """Read-only settlement resolution; never mints or appends audit events."""
    try:
        registry = read_registry(registry_path)
    except ValueError as exc:
        return {
            "status": IDENTITY_INSUFFICIENT,
            "reason_code": str(exc),
            "canonical_match_instance_id": None,
        }
    structure = _structure(observation)
    if structure is None:
        return {
            "status": IDENTITY_INSUFFICIENT,
            "reason_code": "STRUCTURAL_MINIMUM_UNAVAILABLE",
            "canonical_match_instance_id": None,
        }
    instances = _instances(registry)
    expected = instances.get(str(expected_canonical_id))
    if expected is None or not _structure_matches(expected, structure):
        return {
            "status": IDENTITY_CONFLICT,
            "reason_code": "EXPECTED_CANONICAL_STRUCTURE_MISMATCH",
            "canonical_match_instance_id": None,
        }
    round_id = _value(observation, "round_id", "roundId")
    round_value = str(round_id) if round_id not in (None, "") else None
    if round_value and not _round_is_compatible(expected, round_value):
        return {
            "status": IDENTITY_CONFLICT,
            "reason_code": "SETTLEMENT_ROUND_EVIDENCE_CONFLICT",
            "canonical_match_instance_id": None,
        }
    if event_id not in (None, "") and event_id_validated:
        event_bindings = _aliases(registry, ALIAS_EVENT_ID, str(event_id), provider)
        event_candidates = {
            str(row.get("canonical_match_instance_id"))
            for row in event_bindings
            if row.get("status") == ALIAS_ACTIVE
        }
        compatible_events = {
            candidate for candidate in event_candidates
            if candidate in instances and _structure_matches(instances[candidate], structure)
        }
        if compatible_events == {str(expected_canonical_id)}:
            return {
                "status": CANONICAL_RESOLVED,
                "reason_code": "SETTLEMENT_EVENT_ALIAS_MATCH",
                "canonical_match_instance_id": str(expected_canonical_id),
            }
        if event_bindings:
            return {
                "status": IDENTITY_CONFLICT,
                "reason_code": "SETTLEMENT_EVENT_ALIAS_CONFLICT",
                "canonical_match_instance_id": None,
            }
        round_candidates = {
            str(row.get("canonical_match_instance_id"))
            for row in instances.values()
            if _structure_matches(row, structure)
            and round_value
            and round_value in _instance_round_ids(row)
        }
        if round_candidates == {str(expected_canonical_id)}:
            return {
                "status": CANONICAL_RESOLVED,
                "reason_code": "SETTLEMENT_ROUND_MATCH",
                "canonical_match_instance_id": str(expected_canonical_id),
            }
        if len(round_candidates) > 1:
            return {
                "status": IDENTITY_CONFLICT,
                "reason_code": "SETTLEMENT_ROUND_IDENTITY_AMBIGUOUS",
                "canonical_match_instance_id": None,
            }
        expected_events = [
            row for row in registry.get("aliases", [])
            if isinstance(row, Mapping)
            and row.get("alias_type") == ALIAS_EVENT_ID
            and row.get("canonical_match_instance_id") == str(expected_canonical_id)
            and row.get("status") == ALIAS_ACTIVE
            and str(row.get("provider")) == provider
        ]
        structural_instances = [
            row for row in instances.values() if _structure_matches(row, structure)
        ]
        if not expected_events and len(structural_instances) == 1:
            return {
                "status": CANONICAL_RESOLVED,
                "reason_code": "SETTLEMENT_NEW_EVENT_UNIQUE_STRUCTURE",
                "canonical_match_instance_id": str(expected_canonical_id),
            }
        return {
            "status": IDENTITY_INSUFFICIENT,
            "reason_code": "SETTLEMENT_EVENT_ALIAS_UNBOUND",
            "canonical_match_instance_id": None,
        }
    if round_value:
        round_candidates = {
            str(row.get("canonical_match_instance_id"))
            for row in instances.values()
            if _structure_matches(row, structure)
            and round_value in _instance_round_ids(row)
        }
        if round_candidates == {str(expected_canonical_id)}:
            return {
                "status": CANONICAL_RESOLVED,
                "reason_code": "SETTLEMENT_ROUND_MATCH",
                "canonical_match_instance_id": str(expected_canonical_id),
            }
        if len(round_candidates) > 1:
            return {
                "status": IDENTITY_CONFLICT,
                "reason_code": "SETTLEMENT_ROUND_IDENTITY_AMBIGUOUS",
                "canonical_match_instance_id": None,
            }
    alias_candidates: set[str] = set()
    match_id = _value(observation, "match_id", "id")
    if match_id not in (None, ""):
        alias_candidates.update(
            str(row.get("canonical_match_instance_id"))
            for row in _aliases(registry, ALIAS_MATCH_ID, str(match_id), provider)
            if row.get("status") == ALIAS_ACTIVE
        )
    compatible = {
        candidate for candidate in alias_candidates
        if candidate in instances and _structure_matches(instances[candidate], structure)
    }
    if compatible == {str(expected_canonical_id)}:
        return {
            "status": CANONICAL_RESOLVED,
            "reason_code": "SETTLEMENT_ALIAS_MATCH",
            "canonical_match_instance_id": str(expected_canonical_id),
        }
    return {
        "status": IDENTITY_CONFLICT if compatible else IDENTITY_INSUFFICIENT,
        "reason_code": "SETTLEMENT_IDENTITY_AMBIGUOUS" if len(compatible) > 1 else "SETTLEMENT_STRONG_ALIAS_UNAVAILABLE",
        "canonical_match_instance_id": None,
    }
