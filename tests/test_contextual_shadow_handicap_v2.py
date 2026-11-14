import json
from pathlib import Path
import tempfile

import pandas as pd

from src.contextual_shadow_handicap_v2 import (
    EVIDENCE_VERSION,
    append_frozen_handicap_evidence,
    build_frozen_handicap_evidence,
    build_market_review,
)


def _match(day, winner, loser, score, *, best_of=3):
    return {
        "tourney_date": day,
        "winner_name": winner,
        "loser_name": loser,
        "surface": "Hard",
        "score": score,
        "best_of": best_of,
    }


def _ready_line(line):
    return {
        "line": line,
        "total": {"cover": 40, "push": 0, "miss": 40},
        "wins": {"cover": 36, "push": 0, "miss": 4},
        "losses": {"cover": 4, "push": 0, "miss": 36},
    }


def _evidence(lines):
    return {
        "evidence_version": EVIDENCE_VERSION,
        "handicap_evidence": {
            "format": "bo3",
            "players": {
                "a": {"lines": {f"{line:+g}": _ready_line(line) for line in lines}},
                "b": {"lines": {}},
            },
        },
    }


def test_evidence_is_chronological_and_keeps_conditional_coverage():
    frame = pd.DataFrame([
        _match("20260101", "Alpha", "Other", "6-4 6-4"),
        _match("20260102", "Other", "Alpha", "6-4 6-4"),
        _match("20260103", "Beta", "Other", "6-4 6-4"),
        _match("20260110", "Alpha", "Future", "6-0 6-0"),
    ])
    record = build_frozen_handicap_evidence(
        frame,
        observation_id="obs-1",
        configuration_fingerprint="fingerprint",
        player_a="alpha",
        player_b="beta",
        cutoff=pd.Timestamp("2026-01-05").date(),
        match_format="bo3",
        captured_at_utc="2026-01-04T12:00:00Z",
    )
    alpha = record["handicap_evidence"]["players"]["a"]
    line = alpha["lines"]["-3.5"]
    assert alpha["sample"] == 2
    assert line["total"] == {"cover": 1, "push": 0, "miss": 1}
    assert line["wins"] == {"cover": 1, "push": 0, "miss": 0}
    assert line["losses"] == {"cover": 0, "push": 0, "miss": 1}


def test_append_is_first_snapshot_wins_and_idempotent():
    row = {
        "observation_id": "obs-1",
        "evidence_hash": "first",
    }
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "evidence.jsonl"
        assert append_frozen_handicap_evidence([row], path) == 1
        assert append_frozen_handicap_evidence([
            {**row, "evidence_hash": "second"},
        ], path) == 0
        stored = json.loads(path.read_text(encoding="utf-8"))
        assert stored["evidence_hash"] == "first"


def test_negative_handicap_has_own_price_and_conditional_coverage():
    review = build_market_review(
        probabilities={"a": 0.75, "b": 0.25},
        intervals={"a": [0.70, 0.80], "b": [0.20, 0.30]},
        odds={"a": 1.50, "b": 2.70},
        evidence_record=_evidence([-2.5, -3.0, -3.5]),
    )
    assert review["candidate_side"] == "a"
    assert review["moneyline"] is None
    assert review["handicap"]["type"] == "negative"
    assert review["handicap"]["lines"][0]["price"]["status"] == "READY"
    assert review["handicap"]["lines"][0]["win_cover_pct"] == 90.0
    assert review["handicap"]["lines"][0]["push"] == 0


def test_all_relevant_half_point_lines_are_kept_with_five_consecutive_highlights():
    lines = [-(value / 2) for value in range(1, 13)]
    review = build_market_review(
        probabilities={"a": 0.75, "b": 0.25},
        intervals={"a": [0.70, 0.80], "b": [0.20, 0.30]},
        odds={"a": 1.45, "b": 2.90},
        evidence_record=_evidence(lines),
    )
    rendered = review["handicap"]["lines"]
    assert len(rendered) == 12
    highlighted = [
        float(item["line"]) for item in rendered if item["highlighted"]
    ]
    assert highlighted == [-2.0, -2.5, -3.0, -3.5, -4.0]
    assert {item["line"] for item in rendered} == {
        f"{-value / 2:+g}" for value in range(1, 13)
    }


def test_underdog_reference_lines_are_five_consecutive_half_games():
    lines = [value / 2 for value in range(1, 13)]
    review = build_market_review(
        probabilities={"a": 0.48, "b": 0.52},
        intervals={"a": [0.43, 0.53], "b": [0.47, 0.57]},
        odds={"a": 2.30, "b": 1.60},
        evidence_record=_evidence(lines),
    )
    highlighted = [
        float(item["line"])
        for item in review["handicap"]["lines"] if item["highlighted"]
    ]
    assert highlighted == [1.5, 2.0, 2.5, 3.0, 3.5]


def test_moneyline_review_uses_frozen_fair_odd_when_provided():
    review = build_market_review(
        probabilities={"a": 0.536, "b": 0.464},
        intervals={"a": [0.50, 0.57], "b": [0.43, 0.50]},
        odds={"a": 1.97, "b": 1.92},
        evidence_record=_evidence([0.5, 1.0, 1.5, 2.0, 2.5]),
        fair_odds={"a": 1.864, "b": 2.155},
    )
    assert review["candidate_side"] == "a"
    assert review["moneyline"]["fair_odd"] == 1.86


def test_positive_handicap_highlights_total_coverage():
    review = build_market_review(
        probabilities={"a": 0.48, "b": 0.52},
        intervals={"a": [0.43, 0.53], "b": [0.47, 0.57]},
        odds={"a": 2.30, "b": 1.60},
        evidence_record=_evidence([2.0, 2.5, 3.0]),
    )
    assert review["candidate_side"] == "a"
    assert review["moneyline"]["observed_odd"] == 2.30
    assert review["handicap"]["type"] == "positive"
    assert review["handicap"]["lines"][0]["cover_pct"] == 50.0


def test_handicap_side_follows_model_even_when_moneyline_value_is_other_side():
    review = build_market_review(
        probabilities={"a": 0.57, "b": 0.43},
        intervals={"a": [0.52, 0.61], "b": [0.39, 0.48]},
        odds={"a": 1.48, "b": 2.62},
        evidence_record=_evidence([-2.0, -2.5, -3.0, -3.5]),
        handicap_side="a",
    )
    assert review["candidate_side"] == "b"
    assert review["handicap"]["side"] == "a"
    assert review["handicap"]["type"] == "negative"


def test_line_without_both_result_states_is_not_declared_ready():
    one_sided = _evidence([-3.0])
    one_sided["handicap_evidence"]["players"]["a"]["lines"]["-3"][
        "losses"
    ] = {"cover": 0, "push": 0, "miss": 0}
    review = build_market_review(
        probabilities={"a": 0.75, "b": 0.25},
        intervals={"a": [0.70, 0.80], "b": [0.20, 0.30]},
        odds={"a": 1.45, "b": 2.90},
        evidence_record=one_sided,
    )
    line = next(
        row for row in review["handicap"]["lines"] if row["line"] == "-3"
    )
    assert line["price"]["status"] == "INSUFFICIENT_SAMPLE"
    assert line["price"]["fair_odd"] is None


def test_low_sample_line_keeps_central_and_conservative_reference():
    evidence = _evidence([4.5])
    counts = evidence["handicap_evidence"]["players"]["a"]["lines"]["+4.5"]
    counts["total"] = {"cover": 17, "push": 0, "miss": 8}
    counts["wins"] = {"cover": 10, "push": 0, "miss": 0}
    counts["losses"] = {"cover": 7, "push": 0, "miss": 8}
    review = build_market_review(
        probabilities={"a": 0.30, "b": 0.70},
        intervals={"a": [0.25, 0.35], "b": [0.65, 0.75]},
        odds={"a": 3.00, "b": 1.40},
        evidence_record=evidence,
        handicap_side="a",
    )
    line = next(
        row for row in review["handicap"]["lines"] if row["line"] == "+4.5"
    )
    price = line["price"]
    assert price["status"] == "REFERENCE_LOW_SAMPLE"
    assert price["reference_available"] is True
    assert price["central"]["cover_probability_pct"] == 62.7
    assert price["central"]["minimum_odd"] == 1.70
    assert price["conservative"]["cover_probability_pct"] == 60.0
    assert price["conservative"]["minimum_odd"] == 1.70


def test_no_market_never_formulates_review():
    assert build_market_review(
        probabilities={"a": 0.6, "b": 0.4},
        intervals={"a": [0.55, 0.65], "b": [0.35, 0.45]},
        odds={},
        evidence_record=None,
    ) == {"status": "MARKET_UNAVAILABLE", "candidate_side": None}
