"""Refresh and validate the provider cache without running the tennis bot."""

from __future__ import annotations

import json

from src import fetch_data


def _summary(frame) -> dict:
    if frame is None or frame.empty:
        return {"status": "UNAVAILABLE", "rows": 0}
    remote = int(frame.attrs.get("history_provider_remote_files") or 0)
    cached = int(frame.attrs.get("history_provider_cached_files") or 0)
    return {
        "status": "FRESH" if remote > 0 else "LAST_KNOWN_GOOD",
        "rows": int(len(frame)),
        "remote_files": remote,
        "cached_files": cached,
        "scope": frame.attrs.get("history_scope"),
    }


def refresh() -> dict:
    frames = {
        "atp": fetch_data._load_tennismylife("atp"),
        "wta": fetch_data._load_tennismylife("wta"),
        "challenger": fetch_data._load_tennismylife(
            "atp", include_challenger=True,
        ),
    }
    report = {name: _summary(frame) for name, frame in frames.items()}
    unavailable = [name for name, value in report.items() if value["status"] == "UNAVAILABLE"]
    return {
        "status": "FAILED" if unavailable else (
            "FRESH" if all(value["status"] == "FRESH" for value in report.values())
            else "DEGRADED_LAST_KNOWN_GOOD"
        ),
        "paid_api_calls": 0,
        "bot_executed": False,
        "unavailable": unavailable,
        "universes": report,
    }


def main() -> int:
    report = refresh()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["status"] == "FAILED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
