"""Reconstrói a vista Market Memory exclusivamente a partir de dados locais."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import market_memory_report


if __name__ == "__main__":
    report = market_memory_report.build_and_write()
    print(json.dumps({
        "events": len(report["events"]),
        "observations": report["observation_count"],
        "output": str(market_memory_report.DEFAULT_OUTPUT_PATH),
        "external_calls": 0,
    }, ensure_ascii=False, sort_keys=True))
