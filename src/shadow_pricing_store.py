"""Append-only observations for versioned SHADOW pricing validation."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = 1
DEFAULT_PATH = Path("data/shadow_pricing_observations-v1.jsonl")


def _time(value: Any) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except (TypeError, ValueError):
        return None


def build_observation(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    pricing = payload.get("pricing") if isinstance(payload.get("pricing"), Mapping) else {}
    canonical = payload.get("canonical_match_instance_id")
    analyzed = _time(payload.get("analyzed_at_utc"))
    starts = _time(payload.get("commence_time_utc"))
    if not canonical or not analyzed or not starts or analyzed >= starts:
        return None
    players = pricing.get("players") if isinstance(pricing.get("players"), Mapping) else {}
    orientation = {
        side: {"player_id": payload.get(f"player_{side}_id"),
               "player_name": payload.get(f"player_{side}"),
               "market_odd": (players.get(side) or {}).get("market_odd")}
        for side in ("a", "b")
    }
    if not all(orientation[s]["player_id"] for s in orientation):
        return None
    material = "|".join(map(str, (canonical, pricing.get("model_version"),
                                     pricing.get("configuration_fingerprint"),
                                     payload.get("analyzed_at_utc"))))
    return {
        "schema_version": SCHEMA_VERSION,
        "observation_id": hashlib.sha256(material.encode()).hexdigest()[:32],
        "canonical_match_instance_id": canonical,
        "event_key": payload.get("event_key") or canonical,
        "tour": payload.get("tour"), "tier": payload.get("tier"),
        "commence_time_utc": payload.get("commence_time_utc"),
        "analyzed_at_utc": payload.get("analyzed_at_utc"),
        "model_version": pricing.get("model_version"),
        "configuration_fingerprint": pricing.get("configuration_fingerprint"),
        "source": {"github_run_id": payload.get("github_run_id"),
                   "code_revision": payload.get("code_revision") or payload.get("github_sha"),
                   "odds_provenance": payload.get("odds_provenance") or {
                       "captured_at_utc": payload.get("odds_captured_at_utc"),
                       "bookmaker": payload.get("odds_bookmaker"),
                       "endpoint": payload.get("odds_endpoint")}},
        "orientation": orientation,
        "pricing": pricing,
        "decision": payload.get("prelive_decision"),
    }


def append_observations(rows: Iterable[Mapping[str, Any]], path: Path = DEFAULT_PATH) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: set[str] = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                existing.add(str(json.loads(line).get("observation_id")))
            except (ValueError, AttributeError):
                continue
    additions = []
    for raw in rows:
        observation_id = str(raw.get("observation_id") or "")
        if not observation_id or observation_id in existing:
            continue
        additions.append(dict(raw))
        existing.add(observation_id)
    if additions:
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            for row in additions:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    return len(additions)


def read_observations(path: Path = DEFAULT_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    result = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("schema_version") == SCHEMA_VERSION:
            result.append(row)
    return result


def first_valid_by_match_and_version(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Select the first strictly pre-game observation for each model version."""
    selected: dict[tuple[str, str, str], dict[str, Any]] = {}
    for raw in rows:
        row = dict(raw)
        analyzed, starts = _time(row.get("analyzed_at_utc")), _time(row.get("commence_time_utc"))
        orientation = row.get("orientation") if isinstance(row.get("orientation"), Mapping) else {}
        if not analyzed or not starts or analyzed >= starts:
            continue
        if not all(isinstance(orientation.get(s), Mapping) and orientation[s].get("player_id") for s in ("a", "b")):
            continue
        key = (str(row.get("canonical_match_instance_id") or ""),
               str(row.get("model_version") or ""),
               str(row.get("configuration_fingerprint") or ""))
        if not all(key):
            continue
        current = selected.get(key)
        if current is None or analyzed < _time(current.get("analyzed_at_utc")):
            selected[key] = row
    return sorted(selected.values(), key=lambda row: str(row.get("analyzed_at_utc")))
