import json
from pathlib import Path

from openpyxl import Workbook

from scripts.build_system_history_workbook import _write_contextual_history_sheets
from src.contextual_history_export import build_contextual_history_export


def _write(path: Path, row: dict) -> None:
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")


def test_contextual_ledgers_are_flattened_without_rewriting_prediction(tmp_path):
    paths = {name: tmp_path / f"{name}.jsonl" for name in (
        "observations", "market", "outcomes", "handicap", "moneyline", "h2h",
    )}
    _write(paths["observations"], {
        "observation_id": "obs-1", "canonical_match_instance_id": "match-1",
        "analyzed_at_utc": "2026-11-12T10:00:00Z",
        "commence_time_utc": "2026-11-13T10:00:00Z", "tour": "atp",
        "tier": "ATP 500", "players": {
            "a": {"name": "Alpha"}, "b": {"name": "Beta"},
        }, "competition": {"tournament_name": "Test Open", "round_stage": "QF"},
        "contextual_shadow": {
            "probability_model_a": 0.62, "probability_model_b": 0.38,
            "fair_odd_model_a": {"central": 1.61},
            "fair_odd_model_b": {"central": 2.63},
            "family_coverage": {"pct": 80, "observed": 4, "total": 5},
            "families": [{"key": "recent_form", "label": "Forma recente",
                "data_state": "OBSERVED", "probability_model_a": 0.64}],
            "status": "READY_FOR_PROSPECTIVE_SHADOW", "market_used": False,
        },
    })
    _write(paths["market"], {"observation_id": "obs-1", "odds": {"a": 1.8, "b": 2.1},
        "market_probability_devig": {"a": 0.54, "b": 0.46}})
    _write(paths["outcomes"], {"observation_id": "obs-1", "winner_side": "a"})
    _write(paths["handicap"], {"observation_id": "obs-1", "handicap_evidence": {
        "format": "bo3", "players": {"a": {"lines": {"-2.5": {
            "line": -2.5, "total": {"cover": 6, "push": 0, "miss": 4},
            "wins": {"cover": 6, "push": 0, "miss": 1},
            "losses": {"cover": 0, "push": 0, "miss": 3},
        }}}, "b": {"lines": {}}}}})
    _write(paths["moneyline"], {"observation_id": "obs-1", "moneyline_evidence": {
        "players": {"a": {"general": {"bo3": {"sample": 10, "wins": 6,
            "win_rate_pct": 60}}, "buckets": {}, "source": "test"}, "b": {}}}})
    _write(paths["h2h"], {"observation_id": "obs-1", "h2h_evidence": {"matches": [{
        "event_date": "2026-01-01", "tournament": "Test Open", "round": "R16",
        "surface": "hard", "winner_side": "a", "score": "6-4 6-4",
    }]}})

    payload = build_contextual_history_export(
        observations_path=paths["observations"], market_path=paths["market"],
        outcomes_path=paths["outcomes"], handicap_path=paths["handicap"],
        moneyline_path=paths["moneyline"], h2h_path=paths["h2h"],
    )
    assert payload["summary"] == {
        "observations": 1, "with_market": 1, "settled": 1,
        "family_rows": 1, "moneyline_rows": 1,
        "handicap_rows": 1, "h2h_matches": 1,
    }
    assert payload["games"][0]["probability_a_pct"] == 62.0
    assert payload["games"][0]["prediction_correct"] is True
    assert payload["handicaps"][0]["total_cover_pct"] == 60.0
    assert payload["h2h"][0]["winner"] == "Alpha"

    workbook = Workbook()
    _write_contextual_history_sheets(workbook, payload)
    for name in (
        "Contextual — resumo", "Contextual — jogos", "Contextual — famílias",
        "Contextual — Moneyline", "Contextual — handicaps", "Contextual — H2H",
    ):
        assert name in workbook.sheetnames
    assert workbook["Contextual — jogos"]["L2"].value == 0.62
    assert workbook["Contextual — H2H"]["I2"].value == "6-4 6-4"
