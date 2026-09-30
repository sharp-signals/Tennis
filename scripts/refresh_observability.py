"""Refresh derived views offline; never settle, acquire data, or alter decisions."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src import dashboard, green_strong_validation, market_memory_report


def refresh(root: Path = Path('.')) -> dict:
    root = Path(root)
    statuses = {"attempted_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "market_memory": "UNAVAILABLE", "green_strong": "UNAVAILABLE"}
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
                memory_report=memory, manual_path=root / 'data/manual_paper_22bet.json',
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
