import hashlib
import json
from pathlib import Path

import pytest

from src.contextual_primary_dominant_ab_v1 import (
    build_observation,
    collect_from_baseline_ledger,
    load_contract,
    predict_candidate,
)


def test_committed_contract_is_valid():
    contract = load_contract()
    assert contract["universe"] == "atp"
    assert contract["production_effect"] is False
    claimed = contract.pop("configuration_fingerprint")
    material = json.dumps(
        contract, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()
    assert claimed == hashlib.sha256(material).hexdigest()


def _contract():
    return {
        "experiment_id": "contextual-primary-dominant-ab-v1",
        "mode": "PROSPECTIVE_SHADOW_AB_ONLY",
        "universe": "atp",
        "prospective_start_utc": "2026-11-26T00:00:00+00:00",
        "baseline_release_id": "FENZOBOT_CONTEXTUAL_2026_11",
        "baseline_configuration_fingerprint": "baseline-current",
        "configuration_fingerprint": "experiment-one",
        "favorite_probability_ceiling": 0.625,
        "candidate": {
            "candidate_id": "candidate-one",
            "logit_bonus": 0.25889783,
        },
        "market_used": False,
        "production_effect": False,
        "paper_eligible": False,
        "green_eligible": False,
        "promotion_authorized": False,
    }


def _shadow(*, universe="atp", secondary_dominant=False):
    realized = [0.12, 0.10, 0.03, 0.03, 0.03]
    if secondary_dominant:
        realized = [0.04, 0.04, 0.08, 0.08, 0.08]
    keys = (
        "recent_form", "structural_strength", "surface_conditions",
        "matchup_h2h", "serve_return",
    )
    return {
        "universe": universe,
        "configuration_fingerprint": "baseline-current",
        "probability_model_a": 0.602,
        "families": [
            {
                "key": key,
                "probability_model_a": 0.54,
                "logit_contribution": value,
            }
            for key, value in zip(keys, realized)
        ],
    }


def _baseline(*, shadow=None, analyzed="2027-01-02T10:00:00+00:00"):
    return {
        "observation_id": "baseline-one",
        "canonical_match_instance_id": "match-one",
        "tour": "atp",
        "commence_time_utc": "2027-01-03T10:00:00+00:00",
        "analyzed_at_utc": analyzed,
        "players": {"a": {"name": "A"}, "b": {"name": "B"}},
        "contextual_shadow": shadow or _shadow(),
    }


def test_candidate_changes_only_the_eligible_atp_shadow_probability():
    result = predict_candidate(_shadow(), _contract())
    assert result["status"] == "ELIGIBLE"
    assert result["baseline"]["probability_a"] == 0.602
    assert result["candidate"]["probability_a"] == pytest.approx(0.6621082)
    assert result["candidate"]["fair_odd_a"] == pytest.approx(1.5103)
    assert result["production_effect"] is False
    assert result["market_used"] is False


def test_secondary_dominance_is_recorded_but_never_adjusted():
    result = predict_candidate(
        _shadow(secondary_dominant=True), _contract()
    )
    assert result["status"] == "NOT_ELIGIBLE"
    assert "PRIMARY_BLOCK_NOT_DOMINANT" in result["reason_codes"]
    assert result["candidate"] is None


def test_only_post_start_atp_baselines_enter_the_experiment():
    contract = _contract()
    assert build_observation(
        _baseline(analyzed="2026-11-25T23:59:59+00:00"), contract
    ) is None
    wta = _baseline(shadow=_shadow(universe="wta"))
    wta["tour"] = "wta"
    assert build_observation(wta, contract) is None
    assert build_observation(_baseline(), contract)["experiment"]["eligible"]


def test_collection_is_append_only_and_deduplicated(tmp_path: Path):
    baseline_path = tmp_path / "baseline.jsonl"
    output_path = tmp_path / "experiment.jsonl"
    baseline_path.write_text(
        json.dumps(_baseline()) + "\n", encoding="utf-8"
    )
    first = collect_from_baseline_ledger(
        _contract(), baseline_path=baseline_path, output_path=output_path,
    )
    second = collect_from_baseline_ledger(
        _contract(), baseline_path=baseline_path, output_path=output_path,
    )
    assert first["observations_added"] == 1
    assert first["status_counts"] == {"ELIGIBLE": 1}
    assert second["observations_added"] == 0
    assert len(output_path.read_text(encoding="utf-8").splitlines()) == 1


def test_contract_rejects_any_operational_authorization(tmp_path: Path):
    contract = _contract()
    contract["paper_eligible"] = True
    path = tmp_path / "model.json"
    path.write_text(json.dumps(contract), encoding="utf-8")
    with pytest.raises(ValueError, match="isolation invariant"):
        load_contract(path)
