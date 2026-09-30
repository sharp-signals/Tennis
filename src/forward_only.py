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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


CHANGE_ID = "CHANGE-2026-09-30-067"
SCHEMA_VERSION = 1
DEFAULT_MANIFEST_PATH = Path("data/governance/forward-only-activation-v1.json")


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


def identity_tokens(collection: str, record: Mapping[str, Any]) -> set[str]:
    """Return conservative aliases without relying on presentation names alone."""
    tokens: set[str] = set()
    primary = record_key(collection, record)
    if primary:
        tokens.add(f"key:{primary}")
    pregame = record.get("pregame") if isinstance(record.get("pregame"), Mapping) else {}
    event = record.get("event") if isinstance(record.get("event"), Mapping) else {}
    canonical = (
        record.get("canonical_match_instance_id")
        or pregame.get("canonical_match_instance_id")
        or _nested(record, "identity", "canonical_match_instance_id")
    )
    if canonical:
        tokens.add(f"canonical:{canonical}")
    event_key = record.get("event_key") or pregame.get("event_key") or event.get("event_key")
    if event_key:
        tokens.add(f"event:{event_key}")
    legacy = record.get("legacy_key") or pregame.get("legacy_key") or event.get("legacy_event_key")
    if legacy:
        tokens.add(f"legacy:{legacy}")
    # Provider IDs are reusable, so bind them to stable context before using
    # them as anti-duplication evidence.
    match_id = record.get("match_id") or pregame.get("match_id") or event.get("match_id")
    tour = record.get("tour") or pregame.get("tour") or event.get("tour")
    start = (
        record.get("commence_time_utc")
        or pregame.get("commence_time_utc")
        or event.get("scheduled_start_utc")
    )
    if match_id not in (None, "") and start:
        tokens.add(f"provider:{str(tour or '').casefold()}:{match_id}:{start}")
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

    def protected_tokens(self, collection: str) -> set[str]:
        protected = (self.manifest or {}).get("protected") or {}
        section = protected.get(collection) if isinstance(protected, Mapping) else None
        values = section.get("identity_tokens") if isinstance(section, Mapping) else []
        return {str(value) for value in values or [] if value}

    def is_protected(self, collection: str, record: Mapping[str, Any]) -> bool:
        return bool(identity_tokens(collection, record) & self.protected_tokens(collection))

    def new_record_eligibility(
        self, collection: str, record: Mapping[str, Any],
    ) -> tuple[bool, str]:
        if not self.active:
            return True, self.reason_code
        if self.is_protected(collection, record):
            return False, "PROTECTED_IDENTITY_ALIAS"
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


def load_boundary(path: Path | None = None) -> Boundary:
    target = manifest_path(path)
    try:
        document = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Boundary(active=False)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return Boundary(active=False, reason_code="ACTIVATION_MANIFEST_INVALID")
    if not isinstance(document, Mapping):
        return Boundary(active=False, reason_code="ACTIVATION_MANIFEST_INVALID")
    if document.get("schema_version") != SCHEMA_VERSION or document.get("change_id") != CHANGE_ID:
        return Boundary(active=False, reason_code="ACTIVATION_MANIFEST_CONTRACT_MISMATCH")
    if document.get("status") != "ACTIVE":
        return Boundary(active=False)
    effective = _utc(document.get("effective_from_utc"))
    if effective is None:
        return Boundary(active=False, reason_code="ACTIVATION_T0_INVALID")
    return Boundary(
        active=True,
        effective_from_utc=effective,
        manifest=document,
        reason_code="ACTIVE",
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
        return True, boundary.reason_code
    if boundary.is_protected(collection, record):
        return False, "PROTECTED_AT_T0"
    return boundary.new_record_eligibility(collection, record)
