"""Append-only store isolated from all operational and PAPER ledgers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


DEFAULT_PATH = Path("data/contextual_shadow_observations-v2.jsonl")


def existing_observation_ids(path: Path = DEFAULT_PATH) -> set[str]:
    existing: set[str] = set()
    if not path.exists():
        return existing
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            key = str(json.loads(line).get("observation_id") or "")
        except (ValueError, AttributeError):
            continue
        if key:
            existing.add(key)
    return existing


def build_observation(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    shadow = payload.get("contextual_shadow_v2")
    canonical = payload.get("canonical_match_instance_id")
    if not canonical or not isinstance(shadow, Mapping):
        return None
    if shadow.get("model_version") != "contextual-family-shadow-v2":
        return None
    if shadow.get("market_used") is not False or shadow.get("production_effect") is not False:
        raise ValueError("contextual SHADOW v2 isolation contract violated")
    material = "|".join(map(str, (
        canonical,
        shadow.get("model_version"),
        shadow.get("configuration_fingerprint"),
    )))
    return {
        "schema_version": 2,
        "observation_id": hashlib.sha256(material.encode()).hexdigest()[:32],
        "canonical_match_instance_id": canonical,
        "event_key": payload.get("event_key") or canonical,
        "tour": payload.get("tour"),
        "tier": payload.get("tier"),
        "commence_time_utc": payload.get("commence_time_utc"),
        "analyzed_at_utc": payload.get("analyzed_at_utc"),
        "players": {
            "a": {"id": payload.get("player_a_id"), "name": payload.get("player_a")},
            "b": {"id": payload.get("player_b_id"), "name": payload.get("player_b")},
        },
        "competition": dict(payload.get("competition") or {}),
        "contextual_shadow": dict(shadow),
        "paper_eligible": False,
        "green_eligible": False,
    }


def append_observations(
    rows: Iterable[Mapping[str, Any]], path: Path = DEFAULT_PATH,
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = existing_observation_ids(path)
    additions = []
    for row in rows:
        key = str(row.get("observation_id") or "")
        if key and key not in existing:
            additions.append(dict(row))
            existing.add(key)
    if additions:
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            for row in additions:
                handle.write(json.dumps(
                    row,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ) + "\n")
    return len(additions)
