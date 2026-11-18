import json

import pytest

from src.contextual_rating_ab_v1 import (
    append_observations,
    build_observation,
    load_contract,
)


def test_contract_rejects_any_operational_effect(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({
        "experiment_id": "contextual-rating-ab-v1",
        "mode": "PROSPECTIVE_SHADOW_AB_ONLY",
        "market_used": False,
        "production_effect": True,
        "paper_eligible": False,
        "green_eligible": False,
        "promotion_authorized": False,
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="isolation invariant"):
        load_contract(path)


def test_ab_observation_is_deterministic_append_only(tmp_path):
    baseline = {
        "observation_id": "base-1",
        "canonical_match_instance_id": "match-1",
        "tour": "atp",
        "commence_time_utc": "2026-11-20T10:00:00+00:00",
        "players": {"a": {"name": "A"}, "b": {"name": "B"}},
    }
    comparison = {
        "experiment_id": "contextual-rating-ab-v1",
        "configuration_fingerprint": "abc",
        "predictions": [],
        "market_used": False,
        "production_effect": False,
    }
    row = build_observation(
        baseline_observation=baseline, baseline_probability_a=0.6,
        comparison=comparison, analyzed_at_utc="2026-11-18T10:00:00+00:00",
    )
    assert row["paper_eligible"] is False
    assert row["green_eligible"] is False
    path = tmp_path / "ledger.jsonl"
    assert append_observations([row, row], path) == 1
    assert append_observations([row], path) == 0
