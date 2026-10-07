"""Refresh derived views offline; never settle, acquire data, or alter decisions."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src import dashboard, green_strong_validation, market_memory_report, paper_trading


def _valid_manual_candidate(document: object) -> bool:
    """Only promote the modern aggregate; legacy writers cannot erase it."""
    if not isinstance(document, dict) or document.get("schema_version") != 2:
        return False
    summary = document.get("summary")
    source = document.get("source")
    required_summary = (
        "total_entries", "settled", "pending", "wins", "losses", "pushes",
        "units", "settled_stake_units", "pending_stake_units",
    )
    required_columns = {"market", "side", "odd", "stake", "result", "profit"}
    return (
        isinstance(summary, dict)
        and all(key in summary for key in required_summary)
        and isinstance(source, dict)
        and required_columns.issubset(set((source.get("operational_columns") or {}).keys()))
        and bool(source.get("synced_at_utc"))
    )


def _sync_timestamp(document: object) -> str:
    if not isinstance(document, dict):
        return ""
    source = document.get("source")
    return str(source.get("synced_at_utc") or "") if isinstance(source, dict) else ""


def promote_manual_paper_aggregate(root: Path) -> str:
    """Promote only a verified Sheet aggregate into the dashboard/report source."""
    root = Path(root)
    inbox_path = root / paper_trading.LEGACY_MANUAL_22BET_PATH
    authoritative_path = root / paper_trading.DEFAULT_MANUAL_22BET_PATH
    try:
        candidate = json.loads(inbox_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return "INPUT_UNAVAILABLE"
    try:
        current = json.loads(authoritative_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        current = None
    if not _valid_manual_candidate(candidate):
        return "REJECTED_LEGACY_OR_INCOMPLETE"
    if _valid_manual_candidate(current) and _sync_timestamp(candidate) <= _sync_timestamp(current):
        return "RETAINED_CURRENT"
    dashboard._atomic_write_text(
        authoritative_path, json.dumps(candidate, ensure_ascii=False, sort_keys=True) + "\n",
    )
    return "PROMOTED"


def refresh(root: Path = Path('.')) -> dict:
    root = Path(root)
    statuses = {"attempted_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "market_memory": "UNAVAILABLE", "green_strong": "UNAVAILABLE"}
    statuses["manual_paper_authoritative"] = promote_manual_paper_aggregate(root)
    try:
        memory = market_memory_report.build_and_write(
            ledger_root=root / 'data/market_ledger', snapshots_path=root / 'data/calibration_snapshots.json',
            paper_path=root / 'data/paper_trades.json',
            output_path=root / 'data/market_ledger/derived/market-memory-v1.json')
        statuses['market_memory'] = 'AVAILABLE'
    except Exception as exc:
        statuses['market_memory'] = type(exc).__name__
        memory = None
    if memory is not None:
        try:
            green_strong_validation.build_and_write(
                memory_report=memory,
                manual_path=root / paper_trading.DEFAULT_MANUAL_22BET_PATH,
                output_path=root / 'data/validation/green-strong-v1.json')
            statuses['green_strong'] = 'AVAILABLE'
        except Exception as exc:
            statuses['green_strong'] = type(exc).__name__
    try:
        dashboard._atomic_write_text(root / 'data/dashboard/refresh-status-v1.json',
                                     json.dumps(statuses, sort_keys=True) + '\n')
    except OSError:
        pass
    statuses['dashboard'] = dashboard.build_and_write_best_effort(root=root)['status']
    return statuses


if __name__ == '__main__':
    print(json.dumps(refresh(), ensure_ascii=False, sort_keys=True))
