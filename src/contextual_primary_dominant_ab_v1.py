"""Prospective ATP-only shadow A/B for primary-family dominance.

The experiment never changes the operational probability.  It derives an
isolated candidate from the already frozen pre-match contextual observation
and writes it to a separate append-only ledger.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping


DEFAULT_MODEL_PATH = Path(
    "data/models/contextual-primary-dominant-ab-v1.json"
)
DEFAULT_LEDGER_PATH = Path(
    "data/contextual_primary_dominant_ab_observations-v1.jsonl"
)
BASELINE_LEDGER_PATH = Path(
    "data/contextual_shadow_observations-fenzobot-contextual-2026-11.jsonl"
)

FAMILY_ORDER = (
    "recent_form",
    "structural_strength",
    "surface_conditions",
    "matchup_h2h",
    "serve_return",
)
PRIMARY_FAMILIES = ("recent_form", "structural_strength")
SECONDARY_FAMILIES = (
    "surface_conditions", "matchup_h2h", "serve_return",
)


def _utc(value: Any) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _logit(probability: float) -> float:
    value = min(max(float(probability), 1e-9), 1.0 - 1e-9)
    return math.log(value / (1.0 - value))


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-float(value)))


def _fair_odd(probability: float) -> float:
    return round(1.0 / min(max(float(probability), 1e-9), 1.0), 4)


def load_contract(path: Path = DEFAULT_MODEL_PATH) -> dict[str, Any]:
    contract = json.loads(path.read_text(encoding="utf-8"))
    if (
        contract.get("experiment_id")
        != "contextual-primary-dominant-ab-v1"
        or contract.get("mode") != "PROSPECTIVE_SHADOW_AB_ONLY"
        or contract.get("universe") != "atp"
    ):
        raise ValueError("unexpected primary-dominant A/B contract")
    if any(contract.get(key) is not False for key in (
        "market_used", "production_effect", "paper_eligible",
        "green_eligible", "promotion_authorized",
    )):
        raise ValueError("primary-dominant A/B isolation invariant failed")
    candidate = contract.get("candidate") or {}
    if (
        float(candidate.get("logit_bonus") or 0.0) <= 0.0
        or float(contract.get("favorite_probability_ceiling") or 0.0)
        <= 0.5
    ):
        raise ValueError("invalid primary-dominant A/B candidate")
    _utc(contract.get("prospective_start_utc"))
    return contract


def predict_candidate(
    shadow: Mapping[str, Any], contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a frozen candidate and a complete eligibility trace."""
    universe = str(shadow.get("universe") or "").casefold()
    probability_a = float(shadow["probability_model_a"])
    family_rows = {
        str(item.get("key") or ""): item
        for item in shadow.get("families") or []
    }
    missing_trace = [
        family for family in FAMILY_ORDER
        if family not in family_rows
        or family_rows[family].get("probability_model_a") is None
        or family_rows[family].get("logit_contribution") is None
    ]
    raw = {
        family: (
            _logit(float(family_rows[family]["probability_model_a"]))
            if family in family_rows
            and family_rows[family].get("probability_model_a") is not None
            else 0.0
        )
        for family in FAMILY_ORDER
    }
    realized = {
        family: float(
            family_rows.get(family, {}).get("logit_contribution") or 0.0
        )
        for family in FAMILY_ORDER
    }
    active = all(abs(raw[family]) > 1e-12 for family in FAMILY_ORDER)
    directions = {
        1 if value > 0.0 else -1
        for value in raw.values() if abs(value) > 1e-12
    }
    unanimous = active and len(directions) == 1
    family_sign = next(iter(directions)) if unanimous else 0
    favorite_sign = 1 if probability_a > 0.5 else -1 if probability_a < 0.5 else 0
    favorite_probability = max(probability_a, 1.0 - probability_a)
    primary_magnitude = sum(abs(realized[key]) for key in PRIMARY_FAMILIES)
    secondary_magnitude = sum(
        abs(realized[key]) for key in SECONDARY_FAMILIES
    )
    primary_dominant = primary_magnitude > secondary_magnitude

    reasons = []
    if universe != "atp":
        reasons.append("UNSUPPORTED_UNIVERSE")
    if missing_trace:
        reasons.append("REQUIRED_FAMILY_TRACE_UNAVAILABLE")
    if not unanimous:
        reasons.append("FIVE_FAMILY_UNANIMITY_NOT_MET")
    if family_sign != favorite_sign:
        reasons.append("FAMILY_DIRECTION_DIFFERS_FROM_BASELINE_FAVORITE")
    if favorite_probability > float(contract["favorite_probability_ceiling"]):
        reasons.append("BASELINE_OUTSIDE_LOW_CONSENSUS_RANGE")
    if not primary_dominant:
        reasons.append("PRIMARY_BLOCK_NOT_DOMINANT")
    eligible = not reasons

    candidate_probability_a = None
    if eligible:
        candidate_probability_a = _sigmoid(
            _logit(probability_a)
            + favorite_sign * float(contract["candidate"]["logit_bonus"])
        )
    return {
        "experiment_id": contract["experiment_id"],
        "configuration_fingerprint": contract["configuration_fingerprint"],
        "candidate_id": contract["candidate"]["candidate_id"],
        "universe": universe,
        "status": "ELIGIBLE" if eligible else "NOT_ELIGIBLE",
        "eligible": eligible,
        "reason_codes": reasons,
        "baseline": {
            "probability_a": round(probability_a, 8),
            "probability_b": round(1.0 - probability_a, 8),
            "fair_odd_a": _fair_odd(probability_a),
            "fair_odd_b": _fair_odd(1.0 - probability_a),
        },
        "candidate": (
            {
                "probability_a": round(candidate_probability_a, 8),
                "probability_b": round(1.0 - candidate_probability_a, 8),
                "fair_odd_a": _fair_odd(candidate_probability_a),
                "fair_odd_b": _fair_odd(1.0 - candidate_probability_a),
                "favorite_probability_shift_pp": round(
                    100.0 * (
                        max(candidate_probability_a, 1.0 - candidate_probability_a)
                        - favorite_probability
                    ),
                    4,
                ),
            }
            if candidate_probability_a is not None else None
        ),
        "eligibility_trace": {
            "all_five_families_active": active,
            "all_five_families_unanimous": unanimous,
            "family_direction": (
                "a" if family_sign > 0 else "b" if family_sign < 0 else None
            ),
            "baseline_favorite_direction": (
                "a" if favorite_sign > 0 else "b" if favorite_sign < 0 else None
            ),
            "baseline_favorite_probability": round(favorite_probability, 8),
            "favorite_probability_ceiling": float(
                contract["favorite_probability_ceiling"]
            ),
            "primary_magnitude": round(primary_magnitude, 8),
            "secondary_magnitude": round(secondary_magnitude, 8),
            "primary_dominant": primary_dominant,
            "family_directional_logits": raw,
            "calibrated_realized_family_contributions": realized,
            "missing_trace_families": missing_trace,
        },
        "market_used": False,
        "production_effect": False,
        "paper_eligible": False,
        "green_eligible": False,
        "promotion_authorized": False,
    }


def build_observation(
    baseline_observation: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Build one prospective ATP record without rewriting the baseline."""
    if str(baseline_observation.get("tour") or "").casefold() != "atp":
        return None
    if _utc(baseline_observation.get("analyzed_at_utc")) < _utc(
        contract["prospective_start_utc"]
    ):
        return None
    shadow = baseline_observation.get("contextual_shadow") or {}
    if (
        shadow.get("configuration_fingerprint")
        != contract.get("baseline_configuration_fingerprint")
    ):
        return None
    experiment = predict_candidate(shadow, contract)
    canonical = str(baseline_observation["canonical_match_instance_id"])
    material = "|".join((
        canonical,
        str(contract["experiment_id"]),
        str(contract["configuration_fingerprint"]),
    ))
    return {
        "schema_version": 1,
        "observation_id": hashlib.sha256(material.encode()).hexdigest()[:32],
        "canonical_match_instance_id": canonical,
        "baseline_observation_id": baseline_observation["observation_id"],
        "tour": "atp",
        "commence_time_utc": baseline_observation.get("commence_time_utc"),
        "analyzed_at_utc": baseline_observation.get("analyzed_at_utc"),
        "players": dict(baseline_observation.get("players") or {}),
        "baseline_release_id": contract["baseline_release_id"],
        "baseline_configuration_fingerprint": contract[
            "baseline_configuration_fingerprint"
        ],
        "experiment": experiment,
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
    for raw in rows:
        row = dict(raw)
        key = str(row.get("observation_id") or "")
        if key and key not in existing:
            additions.append(row)
            existing.add(key)
    if additions:
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            for row in additions:
                handle.write(json.dumps(
                    row, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":"),
                ) + "\n")
    return len(additions)


def collect_from_baseline_ledger(
    contract: Mapping[str, Any], *,
    baseline_path: Path = BASELINE_LEDGER_PATH,
    output_path: Path = DEFAULT_LEDGER_PATH,
) -> dict[str, Any]:
    """Append unseen prospective records and report the frozen cohort."""
    rows = []
    if baseline_path.exists():
        for line in baseline_path.read_text(encoding="utf-8").splitlines():
            try:
                baseline = json.loads(line)
            except (ValueError, AttributeError):
                continue
            try:
                observation = build_observation(baseline, contract)
            except (KeyError, TypeError, ValueError):
                observation = None
            if observation is not None:
                rows.append(observation)
    added = append_observations(rows, output_path)
    status_counts = Counter(
        str((row.get("experiment") or {}).get("status") or "UNKNOWN")
        for row in rows
    )
    return {
        "status": "ACTIVE",
        "observations_built": len(rows),
        "observations_added": added,
        "status_counts": dict(sorted(status_counts.items())),
    }
