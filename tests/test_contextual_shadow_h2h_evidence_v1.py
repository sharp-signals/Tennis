import json
from pathlib import Path
from tempfile import TemporaryDirectory

from src.contextual_shadow_h2h_evidence_v1 import (
    append_frozen_h2h_evidence,
    build_frozen_h2h_evidence,
)


def _observation():
    return {
        "observation_id": "obs-h2h-1",
        "contextual_shadow": {
            "configuration_fingerprint": "fingerprint",
            "families": [{
                "key": "matchup_h2h",
                "context_audit": {
                    "source": "test",
                    "eligible_matches": 1,
                    "matches": [{
                        "event_date": "2026-10-01",
                        "tournament": "Indoor Open",
                        "surface": "I.hard",
                        "winner_side": "a",
                        "score": "6-4 6-3",
                        "round": "QF",
                    }],
                },
            }],
        },
    }


def test_h2h_evidence_is_append_only_and_independent_from_prediction():
    evidence = build_frozen_h2h_evidence(
        _observation(), captured_at_utc="2026-11-12T12:00:00+00:00",
    )
    assert evidence["production_effect"] is False
    assert evidence["h2h_evidence"]["matches"][0]["score"] == "6-4 6-3"
    with TemporaryDirectory(dir=Path.cwd()) as directory:
        path = Path(directory) / "h2h.jsonl"
        assert append_frozen_h2h_evidence([evidence], path) == 1
        assert append_frozen_h2h_evidence([evidence], path) == 0
        rows = [json.loads(line) for line in path.read_text(
            encoding="utf-8",
        ).splitlines()]
    assert len(rows) == 1
    assert rows[0]["observation_id"] == "obs-h2h-1"
