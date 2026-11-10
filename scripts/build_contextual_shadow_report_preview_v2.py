"""Build private HTML previews from immutable contextual SHADOW ledgers."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.contextual_shadow_report_v2 import (  # noqa: E402
    build_report_view_model,
    render_index_html,
    render_report_html,
)
from src.contextual_shadow_settlement_v2 import (  # noqa: E402
    MARKET_PATH,
    OBSERVATIONS_PATH,
    OUTCOMES_PATH,
    read_jsonl,
)


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def build_previews(
    *,
    output_dir: Path,
    observations_path: Path = OBSERVATIONS_PATH,
    market_path: Path = MARKET_PATH,
    outcomes_path: Path = OUTCOMES_PATH,
    max_observations: int = 50,
) -> dict[str, Any]:
    observations = read_jsonl(observations_path)
    markets = {
        str(row.get("observation_id")): row for row in read_jsonl(market_path)
        if row.get("observation_id")
    }
    outcomes = {
        str(row.get("observation_id")): row for row in read_jsonl(outcomes_path)
        if row.get("observation_id")
    }
    observations.sort(key=lambda row: str(row.get("analyzed_at_utc") or ""), reverse=True)
    if max_observations > 0:
        observations = observations[:max_observations]
    views = [
        build_report_view_model(
            row,
            markets.get(str(row.get("observation_id"))),
            outcomes.get(str(row.get("observation_id"))),
        )
        for row in observations
    ]
    output_dir.mkdir(parents=True, exist_ok=True)
    for view in views:
        _write_atomic(
            output_dir / f"report-{view['observation_id']}.html",
            render_report_html(view),
        )
    _write_atomic(output_dir / "index.html", render_index_html(views))
    summary = {
        "schema_version": 1,
        "status": "COMPLETED",
        "mode": "SHADOW_PREVIEW_ONLY",
        "reports_built": len(views),
        "with_market": sum(view["market"]["available"] for view in views),
        "with_outcome": sum(view["outcome"]["available"] for view in views),
        "output_dir": str(output_dir),
        "isolation": {
            "predictions_rewritten": False,
            "market_used_for_prediction": False,
            "paper_created": False,
            "green_created": False,
            "notifications_sent": False,
            "operational_reports_published": False,
        },
    }
    _write_atomic(
        output_dir / "summary.json",
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-observations", type=int, default=50)
    args = parser.parse_args()
    print(json.dumps(
        build_previews(
            output_dir=args.output_dir,
            max_observations=max(0, args.max_observations),
        ),
        ensure_ascii=False,
        sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
