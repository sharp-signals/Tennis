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
    MODEL_VERSION,
    build_report_view_model,
    load_report_contract,
    render_index_html,
    render_report_html,
)
from src.contextual_shadow_handicap_v2 import EVIDENCE_PATH  # noqa: E402
from src.contextual_shadow_h2h_evidence_v1 import (  # noqa: E402
    EVIDENCE_PATH as H2H_EVIDENCE_PATH,
)
from src.contextual_shadow_moneyline_v1 import (  # noqa: E402
    EVIDENCE_PATH as MONEYLINE_EVIDENCE_PATH,
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
    handicap_evidence_path: Path | None = None,
    moneyline_evidence_path: Path | None = None,
    h2h_evidence_path: Path | None = None,
    max_observations: int = 50,
    expected_model_version: str = MODEL_VERSION,
    report_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report_contract = report_contract or load_report_contract()
    observations = read_jsonl(observations_path)
    market_history: dict[str, list[dict[str, Any]]] = {}
    for row in read_jsonl(market_path):
        key = str(row.get("observation_id") or "")
        if not key:
            continue
        market_history.setdefault(key, []).append(row)
    markets: dict[str, dict[str, Any]] = {}
    for key, rows in market_history.items():
        rows.sort(key=lambda row: str(row.get("captured_at_utc") or ""))
        latest = dict(rows[-1])
        if len(rows) > 1:
            latest["previous_quote"] = {
                "captured_at_utc": rows[-2].get("captured_at_utc"),
                "odds": dict(rows[-2].get("odds") or {}),
            }
        latest["quote_snapshots"] = len(rows)
        markets[key] = latest
    outcomes = {
        str(row.get("observation_id")): row for row in read_jsonl(outcomes_path)
        if row.get("observation_id")
    }
    if handicap_evidence_path is None:
        handicap_evidence_path = (
            EVIDENCE_PATH if observations_path == OBSERVATIONS_PATH
            else observations_path.with_name(EVIDENCE_PATH.name)
        )
    handicap_evidence = {
        str(row.get("observation_id")): row
        for row in read_jsonl(handicap_evidence_path)
        if row.get("observation_id")
    }
    if moneyline_evidence_path is None:
        moneyline_evidence_path = (
            MONEYLINE_EVIDENCE_PATH if observations_path == OBSERVATIONS_PATH
            else observations_path.with_name(MONEYLINE_EVIDENCE_PATH.name)
        )
    moneyline_evidence = {
        str(row.get("observation_id")): row
        for row in read_jsonl(moneyline_evidence_path)
        if row.get("observation_id")
    }
    if h2h_evidence_path is None:
        h2h_evidence_path = (
            H2H_EVIDENCE_PATH if observations_path == OBSERVATIONS_PATH
            else observations_path.with_name(H2H_EVIDENCE_PATH.name)
        )
    h2h_evidence = {
        str(row.get("observation_id")): row
        for row in read_jsonl(h2h_evidence_path)
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
            handicap_evidence.get(str(row.get("observation_id"))),
            moneyline_evidence.get(str(row.get("observation_id"))),
            h2h_evidence.get(str(row.get("observation_id"))),
            contract=report_contract,
            expected_model_version=expected_model_version,
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
        "model_version": expected_model_version,
        "reports_built": len(views),
        "with_market": sum(view["market"]["available"] for view in views),
        "with_outcome": sum(view["outcome"]["available"] for view in views),
        "with_handicap_evidence": sum(
            view["market_review"].get("handicap") is not None for view in views
        ),
        "with_moneyline_evidence": sum(
            any(
                (player.get("moneyline_history") or {}).get("general", {}).get("sample")
                for player in view["players"].values()
            ) for view in views
        ),
        "with_h2h_evidence": sum(
            bool(view.get("h2h_evidence_available")) for view in views
        ),
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
