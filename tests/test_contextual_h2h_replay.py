from __future__ import annotations

import pandas as pd

from src.contextual_h2h_replay import (
    build_contextual_h2h_replay_rows,
    summarize_contextual_h2h_rows,
)


def _frame(rows):
    return pd.DataFrame(rows)


def test_same_day_results_do_not_leak_into_each_other():
    rows = build_contextual_h2h_replay_rows(_frame([
        {"date": "2026-01-01", "winner_name": "A", "loser_name": "B", "surface": "Hard"},
        {"date": "2026-01-01", "winner_name": "B", "loser_name": "A", "surface": "Hard"},
        {"date": "2026-02-01", "winner_name": "A", "loser_name": "B", "surface": "Hard"},
    ]))
    assert [row["prior_matches"] for row in rows] == [0, 0, 2]


def test_context_and_recency_are_preserved_without_becoming_a_score():
    rows = build_contextual_h2h_replay_rows(_frame([
        {"date": "2020-01-01", "winner_name": "A", "loser_name": "B", "surface": "Clay"},
        {"date": "2025-07-01", "winner_name": "A", "loser_name": "B", "surface": "Hard", "Court": "Outdoor"},
        {"date": "2026-01-01", "winner_name": "B", "loser_name": "A", "surface": "Hard", "Court": "Outdoor"},
    ]))
    target = rows[-1]
    assert target["prior_matches"] == 2
    assert target["same_context_matches"] == 1
    assert target["recent_same_context_matches"] == 1
    assert target["recent_same_context_leader"] == "a"


def test_enriched_surface_context_is_used_directly():
    rows = build_contextual_h2h_replay_rows(_frame([
        {"date": "2025-01-01", "winner_name": "A", "loser_name": "B", "surface_context": "hard_indoor"},
        {"date": "2025-02-01", "winner_name": "A", "loser_name": "B", "surface_context": "hard_indoor"},
    ]))
    assert rows[-1]["same_context_matches"] == 1
    assert rows[-1]["same_context_leader"] == "a"


def test_summary_separates_single_h2h_from_repeated_evidence():
    rows = build_contextual_h2h_replay_rows(_frame([
        {"date": "2025-01-01", "winner_name": "A", "loser_name": "B", "surface": "Clay"},
        {"date": "2025-02-01", "winner_name": "A", "loser_name": "B", "surface": "Clay"},
        {"date": "2025-03-01", "winner_name": "A", "loser_name": "B", "surface": "Clay"},
        {"date": "2025-04-01", "winner_name": "A", "loser_name": "B", "surface": "Clay"},
        {"date": "2025-05-01", "winner_name": "A", "loser_name": "B", "surface": "Clay"},
    ]))
    summary = summarize_contextual_h2h_rows(rows)
    assert summary["bands"]["zero"]["targets"] == 1
    assert summary["bands"]["one"]["targets"] == 1
    assert summary["bands"]["two_to_three"]["targets"] == 2
    assert summary["bands"]["four_plus"]["targets"] == 1


def test_candidate_features_shrink_one_match_and_do_not_double_count_context():
    rows = build_contextual_h2h_replay_rows(_frame([
        {"date": "2025-01-01", "winner_name": "A", "loser_name": "B", "surface_context": "clay"},
        {"date": "2025-02-01", "winner_name": "A", "loser_name": "B", "surface_context": "clay"},
    ]))
    target = rows[-1]
    features = target["features"]
    assert features["contextual_h2h_global_shrunk_v1"] == 1 / 3
    assert (
        features["contextual_h2h_same_context_modifier_v1"]
        == features["contextual_h2h_global_shrunk_v1"]
    )


def test_absent_h2h_has_no_candidate_signal():
    row = build_contextual_h2h_replay_rows(_frame([
        {"date": "2025-01-01", "winner_name": "A", "loser_name": "B", "surface": "Clay"},
    ]))[0]
    assert all(value is None for value in row["features"].values())
