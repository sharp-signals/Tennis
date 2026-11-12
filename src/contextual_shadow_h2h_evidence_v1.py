"""Append-only factual H2H detail linked to a frozen contextual prediction."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


EVIDENCE_PATH = Path("data/contextual_shadow_h2h_evidence-v1.jsonl")
EVIDENCE_VERSION = "contextual-shadow-h2h-evidence-v1.0"
MODEL_VERSION = "contextual-family-shadow-v2"


def build_frozen_h2h_evidence(
    observation: Mapping[str, Any], *, captured_at_utc: str,
    model_version: str = MODEL_VERSION,
) -> dict[str, Any] | None:
    """Extract display-only H2H facts without rewriting the prediction."""
    shadow = observation.get("contextual_shadow") or {}
    family = next(
        (
            row for row in shadow.get("families") or []
            if row.get("key") == "matchup_h2h"
        ),
        None,
    )
    if not isinstance(family, Mapping):
        return None
    source = dict(family.get("context_audit") or {})
    if not source:
        return None
    evidence = {
        "source": source.get("source"),
        "raw_matches": source.get("raw_matches"),
        "eligible_matches": source.get("eligible_matches"),
        "eligible_a_wins": source.get("eligible_a_wins"),
        "eligible_surface_matches": source.get("eligible_surface_matches"),
        "eligible_surface_a_wins": source.get("eligible_surface_a_wins"),
        "excluded_non_competitive": source.get("excluded_non_competitive"),
        "matches": [
            dict(row) for row in source.get("matches") or []
            if isinstance(row, Mapping)
        ],
    }
    encoded = json.dumps(
        evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return {
        "schema_version": 1,
        "evidence_version": EVIDENCE_VERSION,
        "observation_id": str(observation.get("observation_id") or ""),
        "model_version": model_version,
        "configuration_fingerprint": shadow.get("configuration_fingerprint"),
        "captured_at_utc": captured_at_utc,
        "evidence_hash": hashlib.sha256(encoded).hexdigest(),
        "production_effect": False,
        "h2h_evidence": evidence,
    }


def append_frozen_h2h_evidence(
    rows: Iterable[Mapping[str, Any]], path: Path = EVIDENCE_PATH,
) -> int:
    """Append one factual H2H record per frozen observation."""
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
