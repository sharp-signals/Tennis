"""Reconstrói a vista Market Memory exclusivamente a partir de dados locais."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import dashboard, green_strong_validation, market_memory_report


if __name__ == "__main__":
    report = market_memory_report.build_and_write()
    green = green_strong_validation.build_and_write(memory_report=report)
    dashboard_status = dashboard.build_and_write_best_effort(root=ROOT)
    print(json.dumps({
        "events": len(report["events"]),
        "observations": report["observation_count"],
        "output": str(market_memory_report.DEFAULT_OUTPUT_PATH),
        "external_calls": 0,
        "green_strong_candidates": green["metrics"]["sample_size"],
        "dashboard_status": dashboard_status["status"],
    }, ensure_ascii=False, sort_keys=True))
