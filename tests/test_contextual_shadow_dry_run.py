from src.contextual_shadow_dry_run import (
    link_snapshot, orient_snapshot_probability, probability_metrics, replay_index,
)


def _snapshot():
    return {
        "tour": "atp", "tier": "ATP 250",
        "commence_time_utc": "2026-01-10T10:00:00+00:00",
        "player_a": {"name": "Beta"}, "player_b": {"name": "Alpha"},
        "outcome": {"winner_side": "b"},
        "pricing": {
            "sharp_estimate_a": 0.35, "sharp_estimate_b": 0.65,
            "market_probability_a": 0.40, "market_probability_b": 0.60,
        },
    }


def test_link_is_pair_based_and_outcome_checked():
    row = {
        "event_date": "2026-01-05", "player_a": "alpha", "player_b": "beta",
        "target_a_win": True,
    }
    linked, reason = link_snapshot(_snapshot(), replay_index({"atp": [row]}))
    assert reason == "LINKED"
    assert linked == row


def test_snapshot_probability_is_reoriented_to_alphabetical_model_side():
    assert orient_snapshot_probability(_snapshot(), "sharp_estimate") == 0.65
    assert orient_snapshot_probability(_snapshot(), "market_probability") == 0.60


def test_probability_metrics_are_proper_scoring_rules():
    rows = [
        {"p": 0.8, "target_a_win": True},
        {"p": 0.2, "target_a_win": False},
    ]
    result = probability_metrics(rows, "p")
    assert result["sample"] == 2
    assert result["accuracy_pct"] == 100.0
    assert result["brier"] == 0.04
