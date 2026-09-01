"""Small, reproducible RapidAPI historical capability audit (never a backfill)."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src import fetch_data
from src.config import RAPIDAPI_BASE
from src.historical_acquisition import AUDIT_ENDPOINTS, HistoricalAcquirer
from src.historical_warehouse import HistoricalWarehouse


DOCUMENTED_SAMPLES = {"atp": 68074, "wta": 45854}


def _records(payload: Any) -> list[Any]:
    data = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return list(data.values())
    return []


def _summarize(name: str, tour: str, payload: Any, cache_hit: bool) -> dict[str, Any]:
    records = _records(payload)
    dates, odds, timestamps, bookmakers = [], 0, 0, set()
    pagination = False
    if isinstance(payload, dict):
        pagination = any(key in payload for key in ("hasNextPage", "nextPage", "page", "totalPages"))
    for item in records:
        if not isinstance(item, dict):
            continue
        date = item.get("date") or item.get("startTime") or item.get("tourney_date")
        if date:
            dates.append(str(date))
        if item.get("odd1") is not None or item.get("odd2") is not None:
            odds += 1
        if item.get("oddsTimestamp") or item.get("provider_timestamp"):
            timestamps += 1
        if item.get("bookmaker"):
            bookmakers.add(str(item["bookmaker"]))
    temporal_safe = name == "getPlayerPastMatches"
    limitations = []
    if name in {"getPlayerPerfBreakdown", "getVsAllStats"}:
        temporal_safe = False
        limitations.append("Agregado pode incluir jogos posteriores; persistível para auditoria, não usado diretamente no replay.")
    if name == "getSinglesRanking":
        temporal_safe = False
        limitations.append("Ranking atual; proibido como ranking histórico.")
    if odds and not timestamps:
        limitations.append("Odds sem timestamp/semântica; guardadas como UNAVAILABLE para replay ex ante.")
    return {
        "endpoint": name, "tour": tour.upper(), "access_status": "ok", "cache_hit": cache_hit,
        "records": len(records), "records_per_call": len(records), "maximum_depth_observed": len(records),
        "provider_record_ids_observed": sum(
            1 for item in records if isinstance(item, dict) and any(item.get(key) is not None for key in ("id", "matchId", "fixtureId"))
        ),
        "earliest_observed": min(dates) if dates else None,
        "latest_observed": max(dates) if dates else None, "pagination_observed": pagination,
        "odds_records": odds, "bookmakers": sorted(bookmakers), "odds_timestamp_records": timestamps,
        "odds_temporal_role": "UNKNOWN" if odds else None,
        "safe_for_ex_ante_replay": temporal_safe,
        "limitations": limitations,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# RapidAPI Historical Capability Audit", "", f"Generated: {report['generated_at_utc']}", ""]
    if report.get("status") != "completed":
        return "\n".join(lines + [f"Status: **{report['status']}**", "", report.get("reason", "")]) + "\n"
    lines += [f"Calls made: **{report['calls_made']}**; cache hits: **{report['cache_hits']}**.", ""]
    for item in report["endpoints"]:
        lines += [
            f"## {item['endpoint']} — {item['tour']}", "",
            f"- status: {item['access_status']}", f"- records: {item.get('records', 0)}",
            f"- range observed: {item.get('earliest_observed')} → {item.get('latest_observed')}",
            f"- pagination observed: {item.get('pagination_observed')}",
            f"- odds/bookmakers/timestamps: {item.get('odds_records')} / {item.get('bookmakers')} / {item.get('odds_timestamp_records')}",
            f"- safe ex ante: {item.get('safe_for_ex_ante_replay')}",
            f"- limitations: {'; '.join(item.get('limitations') or []) or 'none observed in sample'}", "",
        ]
    lines += [
        "## Explicit non-discovery", "",
        "No separate historical-odds endpoint is documented in the current repository; this audit does not invent one.",
        "The observed maximum depth is sample-specific and is not a provider guarantee.", "",
    ]
    return "\n".join(lines)


def run_audit(*, warehouse_path: Path, output_dir: Path, max_calls: int = 8) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "sample_player_ids": DOCUMENTED_SAMPLES, "max_calls": max_calls,
        "endpoints": [],
    }
    if not fetch_data.RAPIDAPI_KEY:
        report.update({"status": "not_run", "reason": "RAPIDAPI_KEY is not available; no capability result was fabricated.", "calls_made": 0, "cache_hits": 0})
    else:
        fetch_data.RAPIDAPI_MAX_CALLS_PER_RUN = min(fetch_data.RAPIDAPI_MAX_CALLS_PER_RUN, max_calls)
        warehouse = HistoricalWarehouse(warehouse_path)
        acquirer = HistoricalAcquirer(warehouse)
        for tour, player_id in DOCUMENTED_SAMPLES.items():
            for name, template in AUDIT_ENDPOINTS.items():
                if acquirer.metrics.calls_made >= max_calls:
                    break
                url = template.format(base=RAPIDAPI_BASE, tour=tour, player_id=player_id)
                params = {"tour": tour, "player_id": player_id} if "{player_id}" in template else {"tour": tour}
                try:
                    payload, _, hit = acquirer.fetch_json(name, url, params)
                    report["endpoints"].append(_summarize(name, tour, payload, hit))
                except Exception as exc:
                    report["endpoints"].append({"endpoint": name, "tour": tour.upper(), "access_status": "error", "error": str(exc), "safe_for_ex_ante_replay": False})
        report.update({"status": "completed", "calls_made": acquirer.metrics.calls_made, "cache_hits": acquirer.metrics.cache_hits})
    (output_dir / "historical-capability-audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "historical-capability-audit.md").write_text(render_markdown(report), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--warehouse", type=Path, default=Path(os.environ.get("HISTORICAL_WAREHOUSE_PATH", "data/historical_warehouse/sharp_history.sqlite3")))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/historical-audit"))
    parser.add_argument("--max-calls", type=int, default=8)
    args = parser.parse_args()
    print(json.dumps(run_audit(warehouse_path=args.warehouse, output_dir=args.output_dir, max_calls=args.max_calls), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
