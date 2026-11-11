"""Frozen pre-match Moneyline history for contextual SHADOW reports."""

from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from . import fetch_data


EVIDENCE_PATH = Path("data/contextual_shadow_moneyline_evidence-v1.jsonl")
EVIDENCE_VERSION = "contextual-shadow-moneyline-evidence-v1.0"
MODEL_VERSION = "contextual-family-shadow-v2"


def _summary(value: Mapping[str, Any] | None) -> dict[str, Any]:
    value = value or {}
    sample = int(value.get("n") or 0)
    wins = int(value.get("wins") or 0)
    return {
        "sample": sample,
        "wins": wins,
        "win_rate_pct": round(100.0 * wins / sample, 1) if sample else None,
    }


def _compact_history(value: Mapping[str, Any] | None) -> dict[str, Any]:
    value = value or {}
    buckets = {}
    for label, item in (value.get("buckets") or {}).items():
        buckets[str(label)] = {
            "all": _summary(item),
            "bo3": _summary((item.get("by_format") or {}).get("bo3")),
            "bo5": _summary((item.get("by_format") or {}).get("bo5")),
        }
    general = {key: {"sample": 0, "wins": 0} for key in ("all", "bo3", "bo5")}
    for item in buckets.values():
        for key in general:
            general[key]["sample"] += int(item[key]["sample"] or 0)
            general[key]["wins"] += int(item[key]["wins"] or 0)
    for item in general.values():
        item["win_rate_pct"] = (
            round(100.0 * item["wins"] / item["sample"], 1)
            if item["sample"] else None
        )
    return {
        "general": general,
        "buckets": buckets,
        "odds_columns": list(value.get("odds_columns") or []),
        "source": value.get("source"),
        "odds_basis": value.get("odds_basis"),
    }


def build_frozen_moneyline_evidence(
    history: pd.DataFrame,
    *,
    observation_id: str,
    configuration_fingerprint: str,
    player_a: str,
    player_b: str,
    cutoff: date,
    captured_at_utc: str,
    model_version: str = MODEL_VERSION,
) -> dict[str, Any]:
    """Freeze all historical odds bands strictly known before the fixture."""
    evidence = {
        "cutoff": cutoff.isoformat(),
        "players": {
            "a": _compact_history(fetch_data.compute_historical_moneyline_margins(
                history, player_a, before=cutoff,
            )),
            "b": _compact_history(fetch_data.compute_historical_moneyline_margins(
                history, player_b, before=cutoff,
            )),
        },
    }
    evidence_hash = hashlib.sha256(json.dumps(
        evidence, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    return {
        "schema_version": 1,
        "evidence_version": EVIDENCE_VERSION,
        "observation_id": observation_id,
        "model_version": model_version,
        "configuration_fingerprint": configuration_fingerprint,
        "captured_at_utc": captured_at_utc,
        "evidence_hash": evidence_hash,
        "production_effect": False,
        "moneyline_evidence": evidence,
    }


def append_frozen_moneyline_evidence(
    rows: Iterable[Mapping[str, Any]], path: Path = EVIDENCE_PATH,
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: set[str] = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                existing.add(str(json.loads(line).get("observation_id") or ""))
            except (ValueError, AttributeError):
                continue
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
                    row, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":"),
                ) + "\n")
    return len(additions)


def select_moneyline_history(
    evidence_record: Mapping[str, Any] | None, *, side: str,
    observed_odd: float | None, match_format: str,
) -> dict[str, Any] | None:
    evidence = (evidence_record or {}).get("moneyline_evidence") or {}
    player = (evidence.get("players") or {}).get(side) or {}
    if not player:
        return None
    format_key = match_format.casefold() if match_format.casefold() in {"bo3", "bo5"} else "all"
    general = (player.get("general") or {}).get(format_key) or {}
    selected_label = None
    selected = None
    if observed_odd is not None:
        for label, item in (player.get("buckets") or {}).items():
            try:
                low, high = (float(part) for part in str(label).split("-", 1))
            except (TypeError, ValueError):
                continue
            if low <= observed_odd <= high:
                selected_label = label
                selected = item.get(format_key) or {}
                break
    return {
        "general": dict(general),
        "current_band": dict(selected or {}),
        "current_band_label": selected_label,
        "format": format_key.upper(),
        "source": player.get("source"),
        "odds_basis": player.get("odds_basis"),
    }
