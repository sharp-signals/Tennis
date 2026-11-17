import json
import math
from pathlib import Path

from src.contextual_family_combination_v11 import MODEL_VERSION
from src.contextual_family_replay import h2h_reliability_curve


MODEL = Path("data/models/contextual-family-combination-v11.json")


def test_h2h_reliability_curve_rewards_clearer_larger_samples_continuously():
    one_match = h2h_reliability_curve(1.0, 1)
    three_two = h2h_reliability_curve(0.2, 5)
    seven_three = h2h_reliability_curve(0.4, 10)
    assert 0 < one_match < seven_three
    assert 0 < three_two < seven_three
    assert math.isclose(
        h2h_reliability_curve(-0.4, 10), -seven_three,
        rel_tol=1e-12, abs_tol=1e-12,
    )


def test_v11_changes_only_atp_h2h_and_preserves_chronological_audit():
    contract = json.loads(MODEL.read_text(encoding="utf-8"))
    assert contract["model_version"] == MODEL_VERSION
    atp = contract["universes"]["atp"]
    wta = contract["universes"]["wta"]
    assert atp["family_profiles"]["matchup_h2h"] == "h2h_reliability_curve_v3"
    assert wta["family_profiles"]["matchup_h2h"] == "h2h_global_shrunk_v1"
    assert atp["holdout"]["material_h2h"]["sample"] >= 100
    assert atp["holdout"]["paired_gain_vs_v10"]["log_loss_gain"] >= 0.0
    assert (
        atp["holdout"]["material_h2h"]["paired_gain_vs_v10"]["log_loss_gain"]
        > atp["holdout"]["paired_gain_vs_v10"]["log_loss_gain"]
    )
