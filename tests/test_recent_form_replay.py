from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pandas as pd

from src.recent_form_replay import (
    build_recent_form_replay_rows,
    evaluate_recent_form_replay,
    replay_recent_form,
)
from scripts.replay_recent_form_candidates import _source_health, build_report


def _match(day, winner, loser, winner_rank, loser_rank, surface="Hard", score="6-4 6-4"):
    return {
        "tourney_date": day.strftime("%Y%m%d"),
        "winner_name": winner,
        "loser_name": loser,
        "winner_rank": winner_rank,
        "loser_rank": loser_rank,
        "surface": surface,
        "score": score,
    }


def test_replay_never_uses_same_day_or_future_results():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    frame = pd.DataFrame([
        _match(start, "A", "X", 50, 10),
        _match(start + timedelta(days=1), "B", "Y", 60, 200),
        _match(start + timedelta(days=2), "A", "B", 45, 55),
        _match(start + timedelta(days=2), "B", "A", 55, 45),
        _match(start + timedelta(days=3), "A", "B", 44, 56),
    ])

    rows = build_recent_form_replay_rows(
        frame, universe="atp", half_life_candidates=(None,),
    )

    day_three = [row for row in rows if row["event_date"] == "2026-01-03"]
    assert len(day_three) == 2
    for row in day_three:
        candidate = row["candidates"]["uniform_90d"]
        assert candidate["winner"]["sample"] == 1
        assert candidate["loser"]["sample"] == 1
    following = [row for row in rows if row["event_date"] == "2026-01-04"][0]
    assert following["candidates"]["uniform_90d"]["winner"]["sample"] == 3


def test_quality_win_and_bad_loss_point_towards_actual_winner():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    frame = pd.DataFrame([
        _match(start, "A", "Elite", 80, 10),
        _match(start, "Weak", "B", 150, 50),
        _match(start + timedelta(days=5), "A", "B", 70, 55),
    ])

    rows = build_recent_form_replay_rows(
        frame, universe="atp", half_life_candidates=(30,),
    )
    target = rows[-1]["candidates"]["half_life_30d"]

    assert target["winner_minus_loser"]["ranking_surprise_balance_v1"] > 0
    assert target["winner_minus_loser"]["result_balance"] > 0


def test_retirement_is_not_added_to_prior_competitive_history():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    frame = pd.DataFrame([
        _match(start, "A", "B", 20, 30, score="6-4 2-1 RET"),
        _match(start + timedelta(days=2), "A", "B", 20, 30),
    ])

    rows = build_recent_form_replay_rows(
        frame, universe="atp", half_life_candidates=(None,),
    )

    assert len(rows) == 1
    target = rows[0]["candidates"]["uniform_90d"]
    assert target["winner"]["sample"] == 0
    assert target["loser"]["sample"] == 0


def test_evaluation_selects_candidate_on_validation_not_holdout():
    rows = []
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for offset in range(10):
        candidates = {}
        for name, validation_margin, holdout_margin in (
            ("fast", 1.0, -1.0), ("slow", -1.0, 1.0),
        ):
            margin = validation_margin if offset < 8 else holdout_margin
            candidates[name] = {
                "winner_minus_loser": {
                    "result_balance": margin,
                    "ranking_surprise_balance_v1": margin,
                    "win_opponent_strength": margin,
                    "loss_opponent_strength": margin,
                    "game_margin_balance": margin,
                    "same_surface_result_balance": margin,
                }
            }
        rows.append({
            "event_date": (start + timedelta(days=offset)).date().isoformat(),
            "candidates": candidates,
        })

    report = evaluate_recent_form_replay(rows)

    assert report["features"]["result_balance"]["selected_on_validation"] == "fast"
    assert report["features"]["result_balance"]["selected_holdout"]["correct"] == 0


def test_chronological_partitions_follow_target_volume_without_splitting_dates():
    rows = []
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for offset, count in enumerate((20, 1, 1, 1, 1, 1, 1)):
        for _ in range(count):
            rows.append({
                "event_date": (start + timedelta(days=offset)).date().isoformat(),
                "candidates": {
                    "uniform": {
                        "winner_minus_loser": {feature: 1.0 for feature in (
                            "result_balance", "ranking_surprise_balance_v1",
                            "win_opponent_strength", "loss_opponent_strength",
                            "game_margin_balance",
                            "same_surface_result_balance",
                        )}
                    }
                },
            })

    report = evaluate_recent_form_replay(rows)

    assert sum(report["split_targets"].values()) == len(rows)
    assert report["split_targets"]["train"] == 20
    assert report["split_targets"]["validation"] > 0
    assert report["split_targets"]["holdout"] > 0


def test_replay_is_observational_and_never_claims_market_or_production_use():
    frame = pd.DataFrame([])
    report = replay_recent_form(frame, universe="wta")

    assert report["market_used"] is False
    assert report["production_effect"] is False
    assert report["result"]["status"] == "INSUFFICIENT"


def test_v2_separates_strength_of_wins_losses_and_competitiveness():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    frame = pd.DataFrame([
        _match(start, "A", "Top", 60, 10, score="7-6 7-6"),
        _match(start, "Low", "A", 120, 60, score="7-6 7-6"),
        _match(start, "B", "Low2", 50, 150, score="6-4 6-4"),
        _match(start, "Top2", "B", 10, 50, score="6-0 6-0"),
        _match(start + timedelta(days=5), "A", "B", 55, 45),
    ])

    target = build_recent_form_replay_rows(
        frame, universe="atp", half_life_candidates=(None,),
    )[-1]["candidates"]["uniform_90d"]

    # A venceu oposição mais forte; B perdeu contra oposição mais forte, pelo
    # que cada componente é preservada separadamente em vez de ser somada.
    assert target["winner_minus_loser"]["win_opponent_strength"] > 0
    assert target["winner_minus_loser"]["loss_opponent_strength"] < 0
    assert target["winner_minus_loser"]["game_margin_balance"] > 0


def test_quality_replay_source_health_rejects_rankless_fallback():
    today = datetime.now(timezone.utc)
    frame = pd.DataFrame([
        _match(today, "A", "B", None, None),
    ])
    frame.attrs["history_source"] = "rankless-fallback"

    health = _source_health(frame, universe="atp")

    assert health["healthy_for_quality_replay"] is False
    assert health["bilateral_rank_coverage_pct"] == 0.0


def test_quality_replay_source_health_accepts_fresh_rich_history():
    today = datetime.now(timezone.utc)
    frame = pd.DataFrame([
        _match(today, "A", "B", 10, 20),
    ])
    frame.attrs["history_source"] = "tennismylife"

    health = _source_health(frame, universe="wta")

    assert health["healthy_for_quality_replay"] is True
    assert health["bilateral_rank_coverage_pct"] == 100.0


def test_report_defaults_to_primary_tours_and_does_not_fetch_challenger():
    today = datetime.now(timezone.utc)
    frames = {
        "atp": pd.DataFrame([_match(today, "A", "B", 10, 20)]),
        "wta": pd.DataFrame([_match(today, "C", "D", 30, 40)]),
    }
    for frame in frames.values():
        frame.attrs["history_source"] = "tennismylife"
    calls = []

    def fake_history(tour, **kwargs):
        calls.append((tour, kwargs))
        return frames[tour]

    with patch(
        "scripts.replay_recent_form_candidates.fetch_data.get_history",
        side_effect=fake_history,
    ), patch(
        "scripts.replay_recent_form_candidates.replay_recent_form",
        side_effect=lambda frame, universe: {"universe": universe},
    ):
        report = build_report()

    assert calls == [("atp", {}), ("wta", {})]
    assert report["primary_decision_scope"] == ["atp", "wta"]
    assert report["challenger_role"] == "OBSERVATIONAL_ONLY"
    assert set(report["reports"]) == {"atp", "wta"}
