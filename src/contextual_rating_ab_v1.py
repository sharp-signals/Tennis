"""Isolated runtime and append-only ledger for chronological-rating A/B."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .contextual_family_combination_v14 import (
    MODEL_VERSION as COMBINATION_VERSION,
    predict_contextual_combination_v14,
)


DEFAULT_MODEL_PATH = Path("data/models/contextual-rating-ab-v1.json")
DEFAULT_LEDGER_PATH = Path("data/contextual_rating_ab_observations-v1.jsonl")


def load_contract(path: Path = DEFAULT_MODEL_PATH) -> dict[str, Any]:
    contract = json.loads(path.read_text(encoding="utf-8"))
    if (
        contract.get("experiment_id") != "contextual-rating-ab-v1"
        or contract.get("mode") != "PROSPECTIVE_SHADOW_AB_ONLY"
    ):
        raise ValueError("unexpected contextual rating A/B contract")
    if any(contract.get(key) is not False for key in (
        "market_used", "production_effect", "paper_eligible",
        "green_eligible", "promotion_authorized",
    )):
        raise ValueError("contextual rating A/B isolation invariant failed")
    return contract


def predict_candidates(
    row: Mapping[str, Any], contract: Mapping[str, Any], *, universe: str,
) -> dict[str, Any]:
    universe = str(universe).casefold()
    predictions = []
    for candidate in contract.get("candidates", {}).get(universe, []):
        combination = {
            "model_version": COMBINATION_VERSION,
            "mode": "SHADOW_ONLY",
            "market_used": False,
            "production_effect": False,
            "promotion_authorized": False,
            "universes": {universe: candidate["combination"]},
        }
        probability_a = float(predict_contextual_combination_v14(
            [dict(row)], universe=universe, contract=combination,
        )["probabilities"][0])
        predictions.append({
            "candidate_id": candidate["candidate_id"],
            "probability_a": round(probability_a, 8),
            "probability_b": round(1.0 - probability_a, 8),
            "fair_odd_a": round(1.0 / probability_a, 4),
            "fair_odd_b": round(1.0 / (1.0 - probability_a), 4),
        })
    return {
        "experiment_id": contract["experiment_id"],
        "configuration_fingerprint": contract["configuration_fingerprint"],
        "universe": universe,
        "predictions": predictions,
        "market_used": False,
        "production_effect": False,
    }


def build_observation(
    *, baseline_observation: Mapping[str, Any], baseline_probability_a: float,
    comparison: Mapping[str, Any], analyzed_at_utc: str,
) -> dict[str, Any]:
    canonical = str(baseline_observation["canonical_match_instance_id"])
    material = "|".join((
        canonical, str(comparison["experiment_id"]),
        str(comparison["configuration_fingerprint"]),
    ))
    return {
        "schema_version": 1,
        "observation_id": hashlib.sha256(material.encode()).hexdigest()[:32],
        "canonical_match_instance_id": canonical,
        "baseline_observation_id": baseline_observation["observation_id"],
        "tour": baseline_observation["tour"],
        "commence_time_utc": baseline_observation["commence_time_utc"],
        "analyzed_at_utc": analyzed_at_utc,
        "players": dict(baseline_observation["players"]),
        "baseline": {
            "release_id": "FENZOBOT_CONTEXTUAL_2026_11",
            "probability_a": round(float(baseline_probability_a), 8),
            "probability_b": round(1.0 - float(baseline_probability_a), 8),
        },
        "experiment": dict(comparison),
        "market_used": False,
        "production_effect": False,
        "paper_eligible": False,
        "green_eligible": False,
    }


def existing_observation_ids(path: Path = DEFAULT_LEDGER_PATH) -> set[str]:
    if not path.exists():
        return set()
    output = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = str(json.loads(line).get("observation_id") or "")
        except (ValueError, AttributeError):
            continue
        if value:
            output.add(value)
    return output


def append_observations(
    rows: Iterable[Mapping[str, Any]], path: Path = DEFAULT_LEDGER_PATH,
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
                    row, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                ) + "\n")
    return len(additions)
