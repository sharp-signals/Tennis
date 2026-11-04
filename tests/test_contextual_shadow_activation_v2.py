import json
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.audit_contextual_shadow_v2 import audit_ledger
from src.contextual_shadow_activation_v2 import activation_state
from src.contextual_shadow_runtime_v2 import load_contract, predict_contextual_shadow_v2
from src.contextual_shadow_store_v2 import build_observation
from tests.test_contextual_shadow_runtime_v2 import MODEL, _row


def test_activation_is_fail_closed_by_default():
    state = activation_state({})
    assert state["active"] is False
    assert state["reason_code"] == "ACTIVATION_NOT_CONFIGURED"


def test_only_explicit_observe_value_activates():
    assert activation_state({"CONTEXTUAL_SHADOW_V2_MODE": "observe"})["active"]
    invalid = activation_state({"CONTEXTUAL_SHADOW_V2_MODE": "enabled"})
    assert invalid["active"] is False
    assert invalid["reason_code"] == "INVALID_ACTIVATION_VALUE"


def _observation():
    shadow = predict_contextual_shadow_v2(
        _row(), load_contract(MODEL), universe="atp",
    )
    return build_observation({
        "canonical_match_instance_id": "atp:test:audit-v2",
        "event_key": "atp:test:audit-v2",
        "tour": "atp",
        "tier": "ATP 250",
        "commence_time_utc": "2026-11-05T10:00:00+00:00",
        "analyzed_at_utc": "2026-11-04T10:00:00+00:00",
        "player_a_id": 1,
        "player_b_id": 2,
        "player_a": "Alpha",
        "player_b": "Beta",
        "contextual_shadow_v2": shadow,
    })


def test_audit_accepts_isolated_observation_and_waits_for_empty_ledger():
    with TemporaryDirectory(dir=Path.cwd()) as tmp:
        ledger = Path(tmp) / "observations.jsonl"
        waiting = audit_ledger(ledger, MODEL)
        assert waiting["status"] == "WAITING_FOR_DATA"
        ledger.write_text(
            json.dumps(_observation(), ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        healthy = audit_ledger(ledger, MODEL)
        assert healthy["status"] == "HEALTHY"
        assert healthy["rows"] == 1


def test_audit_rejects_market_or_production_contamination():
    with TemporaryDirectory(dir=Path.cwd()) as tmp:
        ledger = Path(tmp) / "observations.jsonl"
        row = _observation()
        row["contextual_shadow"]["market_used"] = True
        row["contextual_shadow"]["production_effect"] = True
        ledger.write_text(json.dumps(row) + "\n", encoding="utf-8")
        result = audit_ledger(ledger, MODEL)
        assert result["status"] == "CONTRACT_VIOLATION"
        codes = {item["code"] for item in result["violations"]}
        assert "MARKET_ISOLATION_VIOLATION" in codes
        assert "PRODUCTION_ISOLATION_VIOLATION" in codes
