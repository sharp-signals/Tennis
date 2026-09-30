"""Controlled paginated depth probe for getPlayerPastMatches."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.historical_replay import _assert_zero_llm
from src import fetch_data
from src.historical_acquisition import HistoricalAcquirer
from src.historical_warehouse import HistoricalWarehouse


CHANGE_ID = "CHANGE-2026-09-01-022"
PROBE_PLAYERS = {
    "atp": {"player_id": 68074, "player_name": "Carlos Alcaraz"},
    "wta": {"player_id": 45854, "player_name": "Iga Świątek"},
}


def _weighted_coverage(pages: list[dict[str, Any]]) -> float | None:
    records = sum(int(page.get("records_returned") or 0) for page in pages)
    odds = sum(int(page.get("odds_records") or 0) for page in pages)
    return round(100 * odds / records, 1) if records else None


def _coverage_depth_reading(pages: list[dict[str, Any]]) -> dict[str, Any]:
    if len(pages) < 4:
        return {
            "criterion": "drop >= 20 percentage points between first and last three observed pages",
            "first_pages_odds_coverage_pct": _weighted_coverage(pages[:3]),
            "last_pages_odds_coverage_pct": _weighted_coverage(pages[-3:]),
            "change_percentage_points": None,
            "material_deterioration_observed": None,
        }
    first = _weighted_coverage(pages[:3])
    last = _weighted_coverage(pages[-3:])
    change = round((last or 0.0) - (first or 0.0), 1)
    return {
        "criterion": "drop >= 20 percentage points between first and last three observed pages",
        "first_pages_odds_coverage_pct": first,
        "last_pages_odds_coverage_pct": last,
        "change_percentage_points": change,
        "material_deterioration_observed": change <= -20.0,
    }


def _summarize_player(
    result: dict[str, Any], *, player_name: str, warehouse_size_before: int,
    warehouse_size_after: int,
) -> dict[str, Any]:
    pages = result.get("pages") or []
    records = sum(int(page.get("records_returned") or 0) for page in pages)
    odds = sum(int(page.get("odds_records") or 0) for page in pages)
    dates = [
        value for page in pages
        for value in (page.get("earliest_date"), page.get("latest_date")) if value
    ]
    return {
        "tour": result["tour"],
        "player_id": result["player_id"],
        "player_name": player_name,
        "pages_requested": result.get("pages_requested", len(pages)),
        "pages_observed": len(pages),
        "pages_from_cache": sum(int(bool(page.get("cache_hit"))) for page in pages),
        "calls_made": result.get("calls_made", 0),
        "raw_records": records,
        "total_unique_matches": result.get("unique_matches", 0),
        "duplicates": result.get("duplicates", 0),
        "oldest_match_observed": min(dates) if dates else None,
        "newest_match_observed": max(dates) if dates else None,
        "estimated_matches_per_page": round(records / len(pages), 2) if pages else None,
        "odds_records": odds,
        "odds_coverage_pct": round(100 * odds / records, 1) if records else None,
        "bookmaker_identified_count": sum(int(page.get("bookmaker_identified_count") or 0) for page in pages),
        "odds_timestamp_count": sum(int(page.get("odds_timestamp_count") or 0) for page in pages),
        "ranking_fields_count": sum(int(page.get("ranking_fields_count") or 0) for page in pages),
        "missing_dates": sum(int(page.get("missing_dates") or 0) for page in pages),
        "malformed_records": result.get("malformed_records", 0),
        "provider_end_reached": bool(result.get("source_exhausted")),
        "stop_reason": result.get("stop_reason"),
        "warehouse_size_increase_bytes": max(0, warehouse_size_after - warehouse_size_before),
        "odds_coverage_depth": _coverage_depth_reading(pages),
        "pages": pages,
        "error": result.get("error"),
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Historical Depth Probe", "",
        f"CHANGE: {report['change_id']}",
        f"Generated: {report['generated_at_utc']}",
        f"Status: **{report['status']}**", "",
    ]
    if report["status"] != "completed":
        return "\n".join(lines + [report.get("reason", "")]) + "\n"
    summary = report["summary"]
    lines += [
        f"Calls made: **{summary['calls_made']}**; cache hits: **{summary['cache_hits']}**; "
        f"unique matches: **{summary['total_unique_matches']}**.", "",
    ]
    for player in report["players"]:
        lines += [
            f"## {player['tour']} — {player['player_name']} ({player['player_id']})", "",
            f"- pages requested/observed/calls/cache: {player['pages_requested']} / "
            f"{player['pages_observed']} / {player['calls_made']} / {player['pages_from_cache']}",
            f"- unique/raw/duplicates: {player['total_unique_matches']} / {player['raw_records']} / {player['duplicates']}",
            f"- observed range: {player['oldest_match_observed']} → {player['newest_match_observed']}",
            f"- provider end reached: {player['provider_end_reached']}; stop: {player['stop_reason']}",
            f"- odds coverage: {player['odds_records']}/{player['raw_records']} ({player['odds_coverage_pct']}%)",
            f"- bookmaker/timestamp/ranking fields: {player['bookmaker_identified_count']} / "
            f"{player['odds_timestamp_count']} / {player['ranking_fields_count']}",
            f"- malformed/missing dates: {player['malformed_records']} / {player['missing_dates']}", "",
            "| Page | HTTP | Records | Unique | Duplicates | Oldest | Odds | Coverage | Cache | Next |",
            "|---:|---:|---:|---:|---:|---|---:|---:|---|---|",
        ]
        for page in player["pages"]:
            lines.append(
                f"| {page['page']} | {page['http_status']} | {page['records_returned']} | "
                f"{page['unique_match_ids']} | {page['duplicates']} | {page['earliest_date']} | "
                f"{page['odds_records']} | {page['odds_coverage_pct']}% | {page['cache_hit']} | "
                f"{page['has_next_page']} |"
            )
        lines.append("")
    lines += [
        "## Interpretation boundary", "",
        "This probe measures provider depth and field coverage only. It makes no performance claim, "
        "does not promote historical odds, and does not run pilot/backfill/replay.", "",
    ]
    return "\n".join(lines)


def run_depth_probe(
    *, warehouse_path: Path, output_dir: Path,
    max_pages_per_player: int = 12, max_calls: int = 24,
    resume: bool = True,
) -> dict[str, Any]:
    _assert_zero_llm()
    output_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "change_id": CHANGE_ID,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "max_pages_per_player": int(max_pages_per_player),
        "max_calls": int(max_calls),
        "players": [],
    }
    if not fetch_data.RAPIDAPI_KEY:
        report.update({
            "status": "not_run",
            "reason": "RAPIDAPI_KEY is not available; no depth result was fabricated.",
            "summary": {"calls_made": 0, "cache_hits": 0, "total_unique_matches": 0},
        })
    else:
        fetch_data.RAPIDAPI_MAX_CALLS_PER_RUN = min(
            fetch_data.RAPIDAPI_MAX_CALLS_PER_RUN, int(max_calls),
        )
        warehouse = HistoricalWarehouse(warehouse_path)
        acquirer = HistoricalAcquirer(warehouse)
        initial_size = warehouse.size_bytes()
        for tour, player in PROBE_PLAYERS.items():
            size_before = warehouse.size_bytes()
            result = acquirer.acquire_player_past_match_pages(
                tour, player["player_id"], resume=resume,
                max_pages=max_pages_per_player, max_calls=max_calls,
            )
            report["players"].append(_summarize_player(
                result, player_name=player["player_name"],
                warehouse_size_before=size_before,
                warehouse_size_after=warehouse.size_bytes(),
            ))
        total_unique = sum(player["total_unique_matches"] for player in report["players"])
        report.update({
            "status": "completed",
            "summary": {
                "calls_made": acquirer.metrics.calls_made,
                "cache_hits": acquirer.metrics.cache_hits,
                "pages_requested": sum(player["pages_requested"] for player in report["players"]),
                "pages_from_cache": sum(player["pages_from_cache"] for player in report["players"]),
                "total_unique_matches": total_unique,
                "warehouse_size_before_bytes": initial_size,
                "warehouse_size_after_bytes": warehouse.size_bytes(),
                "warehouse_size_increase_bytes": max(0, warehouse.size_bytes() - initial_size),
            },
        })
        fetch_data.persist_rapidapi_usage(status="success", matches=total_unique)
    (output_dir / "historical-depth-probe.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (output_dir / "historical-depth-probe.md").write_text(
        render_markdown(report), encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--warehouse", type=Path,
        default=Path(os.environ.get(
            "HISTORICAL_WAREHOUSE_PATH",
            "data/historical_warehouse/sharp_history.sqlite3",
        )),
    )
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/historical-depth-probe"))
    parser.add_argument("--max-pages-per-player", type=int, default=12)
    parser.add_argument("--max-calls", type=int, default=24)
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()
    print(json.dumps(run_depth_probe(
        warehouse_path=args.warehouse,
        output_dir=args.output_dir,
        max_pages_per_player=args.max_pages_per_player,
        max_calls=args.max_calls,
        resume=args.resume,
    ), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
