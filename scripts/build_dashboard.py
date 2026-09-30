"""Reconstrói o Fenzobot Control Dashboard exclusivamente a partir de dados locais."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import dashboard


if __name__ == "__main__":
    result = dashboard.build_and_write(root=ROOT)
    print(json.dumps({
        "status": "AVAILABLE",
        "output_json": str(ROOT / dashboard.DEFAULT_OUTPUT_PATH),
        "output_html": str(ROOT / dashboard.DEFAULT_HTML_PATH),
        "reports": result["global"]["total_reports"],
        "external_calls": 0,
        "llm_calls": 0,
        "semantic_fingerprint": result["semantic_fingerprint"],
    }, ensure_ascii=False, sort_keys=True))
