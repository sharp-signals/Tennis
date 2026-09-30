"""Prospective history boundary for CHANGE-2026-09-30-067.

The boundary is deliberately inactive until a coordinated cut-over writes an
``ACTIVE`` activation manifest.  Historical records are described outside the
records themselves; no migration flags are injected into snapshots, PAPER or
Market Ledger rows.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


CHANGE_ID = "CHANGE-2026-09-30-067"
SCHEMA_VERSION = 1
DEFAULT_MANIFEST_PATH = Path("data/governance/forward-only-activation-v1.json")
PREPARATION_STATUS = "EXTERNAL_ACTIVATION_PENDING"
ACTIVE_STATUS = "ACTIVE"


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _utc(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _nested(record: Mapping[str, Any], *path: str) -> Any:
    value: Any = record
    for part in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(part)
    return value


def record_key(collection: str, record: Mapping[str, Any]) -> str:
    if collection == "snapshots":
        return str(record.get("key") or "")
    if collection == "paper":
        return str(record.get("key") or "")
    if collection == "market_ledger":
        return str(record.get("observation_id") or "")
    return str(record.get("key") or record.get("id") or "")


def _record_parts(collection: str, record: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    if collection == "paper":
        pregame = record.get("pregame")
        return (
            pregame if isinstance(pregame, Mapping) else {},
            (pregame or {}).get("players") if isinstance((pregame or {}).get("players"), Mapping) else {},
        )
    if collection == "market_ledger":
        event = record.get("event")
        event = event if isinstance(event, Mapping) else {}
        return event, {"a": event.get("player_a"), "b": event.get("player_b")}
    return record, {"a": record.get("player_a"), "b": record.get("player_b")}


def canonical_identity(collection: str, record: Mapping[str, Any]) -> str:
    envelope, _ = _record_parts(collection, record)
    return str(
        record.get("canonical_match_instance_id")
        or envelope.get("canonical_match_instance_id")
        or _nested(record, "identity", "canonical_match_instance_id")
        or ""
    )


def weak_aliases(collection: str, record: Mapping[str, Any]) -> set[str]:
    """Provider/presentation identifiers scoped by available event context.

    Provider IDs are reusable.  A bare ``match:77`` must therefore never
    contaminate a future event in another tour or with a different bilateral
    context.  When the full structural instance is available it is the
    namespace; otherwise the factual tour/provider evidence is used.  Truly
    context-free aliases remain explicitly ``unscoped`` and fail closed on a
    collision.
    """
    envelope, _ = _record_parts(collection, record)
    aliases: set[str] = set()
    structural = structural_identity_token(collection, record)
    tour = str(record.get("tour") or envelope.get("tour") or "").strip().casefold()
    provider = str(
        record.get("provider")
        or envelope.get("provider")
        or _nested(record, "capture", "provider")
        or _nested(record, "capture", "bookmaker")
        or ""
    ).strip().casefold()
    if structural:
        namespace = structural
    elif tour or provider:
        namespace = "scope:" + canonical_sha256({"tour": tour, "provider": provider})[:20]
    else:
        namespace = "unscoped"
    values = {
        "event": record.get("event_key") or envelope.get("event_key"),
        "legacy": record.get("legacy_key") or envelope.get("legacy_event_key"),
        "match": record.get("match_id") or envelope.get("match_id"),
        "provider": envelope.get("provider_event_id"),
    }
    for kind, value in values.items():
        if value not in (None, ""):
            aliases.add(f"{kind}:{namespace}:{value}")
    return aliases


def structural_identity_token(collection: str, record: Mapping[str, Any]) -> str:
    """Bilateral event context shared by snapshots, PAPER and ledger rows."""
    envelope, players = _record_parts(collection, record)
    tour = str(record.get("tour") or envelope.get("tour") or "").strip().casefold()
    start = str(
        record.get("commence_time_utc")
        or envelope.get("commence_time_utc")
        or envelope.get("scheduled_start_utc")
        or ""
    ).strip()
    player_tokens = []
    for side in ("a", "b"):
        player = players.get(side) if isinstance(players, Mapping) else None
        player = player if isinstance(player, Mapping) else {}
        identity = str(player.get("id") or "").strip()
        name = " ".join(str(player.get("name") or "").casefold().split())
        player_tokens.append(identity or name)
    tournament = str(
        record.get("tournament_id")
        or envelope.get("tournament_id")
        or record.get("tournament")
        or envelope.get("tournament")
        or ""
    ).strip().casefold()
    if not (tour and start and all(player_tokens)):
        return ""
    material = {
        "tour": tour,
        "scheduled_start_utc": start,
        "players": sorted(player_tokens),
        "tournament": tournament,
    }
    return f"instance:{canonical_sha256(material)}"


def identity_tokens(collection: str, record: Mapping[str, Any]) -> set[str]:
    """Return only strong or structurally-bound anti-duplication evidence."""
    tokens: set[str] = set()
    primary = record_key(collection, record)
    if primary:
        tokens.add(f"{collection}:key:{primary}")
    canonical = canonical_identity(collection, record)
    if canonical:
        tokens.add(f"canonical:{canonical}")
    structural = structural_identity_token(collection, record)
    if structural:
        tokens.add(structural)
    return tokens


def event_and_capture_times(
    collection: str, record: Mapping[str, Any],
) -> tuple[datetime | None, datetime | None]:
    if collection == "snapshots":
        return _utc(record.get("commence_time_utc")), _utc(record.get("analyzed_at_utc"))
    if collection == "paper":
        pregame = record.get("pregame") or {}
        return _utc(pregame.get("commence_time_utc")), _utc(pregame.get("analyzed_at_utc"))
    if collection == "market_ledger":
        return (
            _utc(_nested(record, "event", "scheduled_start_utc")),
            _utc(_nested(record, "capture", "captured_at_utc")),
        )
    return None, None


@dataclass(frozen=True)
class Boundary:
    active: bool
    effective_from_utc: datetime | None = None
    manifest: Mapping[str, Any] | None = None
    reason_code: str = "EXTERNAL_ACTIVATION_PENDING"
    fail_closed: bool = False
    path: Path | None = None

    def protected_tokens(self, collection: str) -> set[str]:
        protected = (self.manifest or {}).get("protected") or {}
        section = protected.get(collection) if isinstance(protected, Mapping) else None
        values = section.get("identity_tokens") if isinstance(section, Mapping) else []
        return {str(value) for value in values or [] if value}

    def all_protected_tokens(self) -> set[str]:
        return set().union(*(self.protected_tokens(name) for name in (
            "snapshots", "paper", "market_ledger",
        )))

    def protected_weak_aliases(self) -> dict[str, set[str]]:
        result: dict[str, set[str]] = {}
        protected = (self.manifest or {}).get("protected") or {}
        for collection in ("snapshots", "paper", "market_ledger"):
            section = protected.get(collection) if isinstance(protected, Mapping) else None
            aliases = section.get("weak_alias_contexts") if isinstance(section, Mapping) else None
            if not isinstance(aliases, Mapping):
                continue
            for alias, canonical_ids in aliases.items():
                values = canonical_ids if isinstance(canonical_ids, list) else []
                result.setdefault(str(alias), set()).update(str(value) for value in values)
        return result

    def protection_reason(self, collection: str, record: Mapping[str, Any]) -> str | None:
        if identity_tokens(collection, record) & self.all_protected_tokens():
            return "PROTECTED_IDENTITY_ALIAS"
        aliases = weak_aliases(collection, record)
        protected_aliases = self.protected_weak_aliases()
        overlap = aliases & set(protected_aliases)
        if not overlap:
            return None
        canonical = canonical_identity(collection, record)
        # A reused provider ID is allowed only when both sides have explicit,
        # different canonical instances. Missing evidence remains fail-closed.
        if canonical and all(
            contexts and "" not in contexts and canonical not in contexts
            for alias in overlap
            for contexts in [protected_aliases[alias]]
        ):
            return None
        return "PROTECTED_IDENTITY_AMBIGUOUS"

    def is_protected(self, collection: str, record: Mapping[str, Any]) -> bool:
        return self.protection_reason(collection, record) is not None

    def new_record_eligibility(
        self, collection: str, record: Mapping[str, Any],
    ) -> tuple[bool, str]:
        if self.fail_closed:
            return False, self.reason_code
        if not self.active:
            return True, self.reason_code
        protected_reason = self.protection_reason(collection, record)
        if protected_reason:
            return False, protected_reason
        event_time, capture_time = event_and_capture_times(collection, record)
        if event_time is None:
            return False, "EVENT_TIME_UNAVAILABLE"
        if capture_time is None:
            return False, "CAPTURE_TIME_UNAVAILABLE"
        assert self.effective_from_utc is not None
        if event_time <= self.effective_from_utc:
            return False, "EVENT_NOT_AFTER_FORWARD_ONLY_BOUNDARY"
        if capture_time < self.effective_from_utc:
            return False, "CAPTURE_BEFORE_FORWARD_ONLY_BOUNDARY"
        if capture_time >= event_time:
            return False, "CAPTURE_NOT_EX_ANTE"
        return True, "FORWARD_ONLY_ELIGIBLE"


def manifest_path(path: Path | None = None) -> Path:
    if path is not None:
        return Path(path)
    configured = os.environ.get("FENZOBOT_FORWARD_ONLY_MANIFEST", "").strip()
    return Path(configured) if configured else DEFAULT_MANIFEST_PATH


def activation_lock_path(path: Path) -> Path:
    return path.with_name(f"{path.stem}.lock.json")


def _tracked_activation_exists(path: Path) -> bool:
    """Git history is the final continuity witness if both live files vanish."""
    resolved = path.resolve()
    for root in (resolved.parent, *resolved.parents):
        if not (root / ".git").exists():
            continue
        try:
            relative = resolved.relative_to(root).as_posix()
            value = subprocess.check_output(
                ["git", "rev-list", "--all", "--", relative], cwd=root,
                text=True, stderr=subprocess.DEVNULL,
            )
        except (OSError, ValueError, subprocess.CalledProcessError):
            return False
        return bool(value.strip())
    return False


def _ratified_activation_lock(path: Path) -> Mapping[str, Any] | None:
    """Return the first lock committed in the current history.

    The live manifest and lock may be internally consistent after both are
    replaced.  The first committed lock is therefore the immutable witness of
    the ratified T0 and inventory hash.  Before the first activation commit
    there is deliberately no anchor yet.
    """
    resolved = path.resolve()
    for root in (resolved.parent, *resolved.parents):
        if not (root / ".git").exists():
            continue
        try:
            relative = resolved.relative_to(root).as_posix()
            history = subprocess.check_output(
                [
                    "git", "log", "--reverse", "--diff-filter=A",
                    "--format=%H", "HEAD", "--", relative,
                ],
                cwd=root, text=True, stderr=subprocess.DEVNULL,
            ).splitlines()
            if not history:
                return None
            raw = subprocess.check_output(
                ["git", "show", f"{history[0]}:{relative}"],
                cwd=root, text=True, stderr=subprocess.DEVNULL,
            )
            value = json.loads(raw)
        except (
            OSError, ValueError, UnicodeError, json.JSONDecodeError,
            subprocess.CalledProcessError,
        ):
            return None
        return value if isinstance(value, Mapping) else None
    return None


def _active_manifest_error(document: Mapping[str, Any]) -> str | None:
    protected = document.get("protected")
    if not isinstance(protected, Mapping):
        return "ACTIVATION_INVENTORY_MISSING"
    for collection in ("snapshots", "paper", "market_ledger"):
        section = protected.get(collection)
        if not isinstance(section, Mapping):
            return f"ACTIVATION_INVENTORY_{collection.upper()}_MISSING"
        if not isinstance(section.get("records"), list):
            return f"ACTIVATION_INVENTORY_{collection.upper()}_INVALID"
        if not isinstance(section.get("identity_tokens"), list):
            return f"ACTIVATION_INVENTORY_{collection.upper()}_INVALID"
        if not isinstance(section.get("weak_alias_contexts"), Mapping):
            return f"ACTIVATION_INVENTORY_{collection.upper()}_INVALID"
        if section.get("count") != len(section["records"]):
            return f"ACTIVATION_INVENTORY_{collection.upper()}_COUNT_MISMATCH"
        if any(
            not isinstance(item, Mapping) or not item.get("identity") or not item.get("sha256")
            for item in section["records"]
        ):
            return f"ACTIVATION_INVENTORY_{collection.upper()}_INVALID"
    reports = protected.get("published_reports")
    if not isinstance(reports, Mapping) or not isinstance(reports.get("files"), list):
        return "ACTIVATION_REPORT_INVENTORY_INVALID"
    if reports.get("count") != len(reports["files"]):
        return "ACTIVATION_REPORT_INVENTORY_COUNT_MISMATCH"
    if any(
        not isinstance(item, Mapping) or not item.get("path") or not item.get("sha256")
        for item in reports["files"]
    ):
        return "ACTIVATION_REPORT_INVENTORY_INVALID"
    if not isinstance(protected.get("exclusions"), list):
        return "ACTIVATION_EXCLUSION_INVENTORY_INVALID"
    references = protected.get("historic_aggregate_references")
    if not isinstance(references, list):
        return "ACTIVATION_PROJECTION_INVENTORY_INVALID"
    if any(
        not isinstance(item, Mapping)
        or not item.get("path")
        or not item.get("sha256_at_t0")
        or str(item.get("kind") or "").upper() not in {"JSON", "XLSX"}
        for item in references
    ):
        return "ACTIVATION_PROJECTION_INVENTORY_INVALID"
    return None


def _invalid(reason: str, path: Path) -> Boundary:
    return Boundary(active=False, reason_code=reason, fail_closed=True, path=path)


def load_boundary(path: Path | None = None) -> Boundary:
    target = manifest_path(path)
    lock_path = activation_lock_path(target)
    previously_activated = lock_path.exists() or _tracked_activation_exists(lock_path)
    try:
        document = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if previously_activated:
            return _invalid("ACTIVATION_MANIFEST_MISSING_AFTER_ACTIVATION", target)
        return Boundary(active=False, path=target)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return _invalid("ACTIVATION_MANIFEST_INVALID", target)
    if not isinstance(document, Mapping):
        return _invalid("ACTIVATION_MANIFEST_INVALID", target)
    if document.get("schema_version") != SCHEMA_VERSION or document.get("change_id") != CHANGE_ID:
        return _invalid("ACTIVATION_MANIFEST_CONTRACT_MISMATCH", target)
    if document.get("status") == PREPARATION_STATUS and not previously_activated:
        return Boundary(active=False, path=target)
    if document.get("status") != ACTIVE_STATUS:
        return _invalid("ACTIVATION_STATUS_INVALID", target)
    effective = _utc(document.get("effective_from_utc"))
    if effective is None:
        return _invalid("ACTIVATION_T0_INVALID", target)
    inventory_error = _active_manifest_error(document)
    if inventory_error:
        return _invalid(inventory_error, target)
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _invalid("ACTIVATION_LOCK_MISSING", target)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return _invalid("ACTIVATION_LOCK_INVALID", target)
    if not isinstance(lock, Mapping):
        return _invalid("ACTIVATION_LOCK_INVALID", target)
    if (
        lock.get("change_id") != CHANGE_ID
        or lock.get("effective_from_utc") != document.get("effective_from_utc")
        or lock.get("manifest_sha256") != canonical_sha256(document)
    ):
        return _invalid("ACTIVATION_LOCK_MISMATCH", target)
    ratified = _ratified_activation_lock(lock_path)
    if ratified is not None:
        immutable_fields = (
            "schema_version", "change_id", "effective_from_utc",
            "manifest_sha256", "code_commit", "data_base_commit",
        )
        if any(lock.get(field) != ratified.get(field) for field in immutable_fields):
            return _invalid("ACTIVATION_RATIFIED_ANCHOR_MISMATCH", target)
    return Boundary(
        active=True,
        effective_from_utc=effective,
        manifest=document,
        reason_code="ACTIVE",
        path=target,
    )


def load_boundary_for_store(
    store_path: Path,
    manifest: Path | None = None,
) -> Boundary:
    """Keep isolated fixtures isolated while production stores use the boundary."""
    if manifest is not None or os.environ.get("FENZOBOT_FORWARD_ONLY_MANIFEST"):
        return load_boundary(manifest)
    try:
        resolved = Path(store_path).resolve()
        production_data = (Path.cwd() / "data").resolve()
        resolved.relative_to(production_data)
    except (OSError, ValueError):
        return Boundary(active=False, reason_code="ISOLATED_STORE_NO_ACTIVATION")
    return load_boundary()


def settlement_eligibility(
    collection: str,
    record: Mapping[str, Any],
    *,
    boundary: Boundary,
) -> tuple[bool, str]:
    if not boundary.active:
        if boundary.fail_closed:
            return False, boundary.reason_code
        return True, boundary.reason_code
    protected_reason = boundary.protection_reason(collection, record)
    if protected_reason:
        return False, "PROTECTED_AT_T0" if protected_reason == "PROTECTED_IDENTITY_ALIAS" else protected_reason
    return boundary.new_record_eligibility(collection, record)
