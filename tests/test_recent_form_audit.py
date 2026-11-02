from datetime import datetime, timezone

import pandas as pd

from src.recent_form_audit import (
    audit_recent_form_coverage,
    normalize_recent_match_record,
)


AS_OF = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)


def _row(**overrides):
    base = {
        "tourney_date": "20261015",
        "tourney_name": "Example",
        "tier": "ATP 500",
        "surface": "Hard",
        "round": "R16",
        "best_of": 3,
        "winner_name": "A",
        "loser_name": "B",
        "winner_rank": 12,
        "loser_rank": 45,
        "score": "6-4 6-3",
        "_history_competition_scope": "main",
        "indoor": False,
    }
    base.update(overrides)
    return base


def test_audit_reports_core_and_full_context_coverage():
    frame = pd.DataFrame([
        _row(),
        _row(tourney_date="20261016", loser_rank=None, score=None),
    ])

    report = audit_recent_form_coverage(
        frame, universe="atp", as_of=AS_OF, source_label="test",
    )

    assert report["rows_window"] == 2
    assert report["coverage"]["result_identity"]["pct"] == 100.0
    assert report["coverage"]["historical_ranking_bilateral"]["pct"] == 50.0
    assert report["coverage"]["score_complete"]["pct"] == 50.0
    assert report["quality_readiness"]["core_result_and_ranking"]["count"] == 1
    assert report["quality_readiness"]["full_context"]["count"] == 1


def test_day_precision_excludes_cutoff_and_future_rows():
    frame = pd.DataFrame([
        _row(tourney_date="20261101"),
        _row(tourney_date="20261102"),
        _row(tourney_date="20261103"),
    ])

    report = audit_recent_form_coverage(frame, universe="atp", as_of=AS_OF)

    assert report["rows_window"] == 1
    assert report["rows_cutoff_or_future_excluded"] == 2
    assert report["safe_cutoff_exclusive"] == "2026-11-02"


def test_missing_rank_stays_missing_in_normalized_record():
    normalized = normalize_recent_match_record(
        _row(winner_rank="", loser_rank=80), universe="challenger",
    )

    assert normalized["winner_rank"] is None
    assert normalized["loser_rank"] == 80.0
    assert normalized["competition_scope"] == "main"


def test_retirement_is_classified_but_not_a_complete_score():
    frame = pd.DataFrame([_row(score="6-4 2-1 RET")])

    report = audit_recent_form_coverage(frame, universe="atp", as_of=AS_OF)

    assert report["coverage"]["completion_classification"]["count"] == 1
    assert report["coverage"]["score_complete"]["count"] == 0


def test_empty_window_is_explicit_not_zero_quality():
    frame = pd.DataFrame([_row(tourney_date="20200101")])

    report = audit_recent_form_coverage(frame, universe="wta", as_of=AS_OF)

    assert report["rows_window"] == 0
    assert report["quality_readiness"]["core_result_and_ranking"]["pct"] is None


def test_invalid_window_is_rejected():
    frame = pd.DataFrame([_row()])

    try:
        audit_recent_form_coverage(frame, universe="atp", as_of=AS_OF, window_days=0)
    except ValueError as exc:
        assert "positivo" in str(exc)
    else:
        raise AssertionError("window_days=0 devia ser rejeitado")
