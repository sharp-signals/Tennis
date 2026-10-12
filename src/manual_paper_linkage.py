"""Compact public index used to link manual PAPER rows to generated reports.

The index contains only information that is already public in the report
dashboard.  It deliberately does not contain manual selections, stakes,
results or notes from the private Google Sheet.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urljoin


SCHEMA_VERSION = 1
DEFAULT_OUTPUT_PATH = Path("data/validation/manual-paper-linkage-index-v1.json")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _split_title(title: Any) -> tuple[str | None, str | None]:
    parts = str(title or "").split(" vs ", 1)
    if len(parts) != 2 or not all(part.strip() for part in parts):
        return None, None
    return parts[0].strip(), parts[1].strip()


def build_index(
    dashboard: Mapping[str, Any], snapshots: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    snapshots = snapshots or []
    snapshot_by_report = {
        str(row.get("report_id")): row
        for row in snapshots
        if row.get("report_id") and row.get("key")
    }
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for day in dashboard.get("days") or []:
        day = _mapping(day)
        report_date = str(day.get("date") or "")
        reports = [row for row in day.get("reports") or [] if isinstance(row, Mapping)]
        for matchup_value in day.get("matchups") or []:
            matchup = _mapping(matchup_value)
            title = str(matchup.get("title") or "").strip()
            player_a, player_b = _split_title(title)
            if not report_date or not player_a or not player_b:
                continue
            identity = (report_date, title.casefold())
            if identity in seen:
                continue
            seen.add(identity)

            versions = []
            for index in matchup.get("version_indexes") or []:
                if isinstance(index, int) and 0 <= index < len(reports):
                    versions.append(reports[index])
            representative = next(
                (row for row in versions if row.get("linkage") == "EXACT_REPORT_ID"),
                versions[0] if versions else {},
            )
            snapshot = snapshot_by_report.get(str(representative.get("report_id") or ""))
            record = {
                "report_date": report_date,
                "player_a": player_a,
                "player_b": player_b,
                "report_match_key": matchup.get("match_key"),
                "linkage_source": matchup.get("match_key_source"),
                "report_url": urljoin(
                    "https://sharp-signals.github.io/Tennis/dashboard/",
                    str(representative.get("url") or ""),
                ) if representative.get("url") else None,
                "snapshot_key": snapshot.get("key") if snapshot else None,
                "commence_time_utc": (
                    snapshot.get("commence_time_utc") if snapshot
                    else matchup.get("scheduled_start_utc")
                ),
            }
            records.append(record)

    records.sort(key=lambda row: (
        str(row.get("report_date") or ""),
        str(row.get("player_a") or "").casefold(),
        str(row.get("player_b") or "").casefold(),
    ))
    material = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "schema_version": SCHEMA_VERSION,
        "privacy_contract": "PUBLIC_REPORT_IDENTITY_ONLY_NO_MANUAL_SELECTIONS",
        "record_count": len(records),
        "fingerprint_sha256": hashlib.sha256(material.encode("utf-8")).hexdigest(),
        "records": records,
    }


def write_index(document: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep this below GitHub Contents API's 1 MB inline-content boundary.
    # Apps Script consumes the file through that endpoint and therefore needs
    # the response body to contain Base64 data rather than a download URL.
    content = json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ) + "\n"
    path.write_text(content, encoding="utf-8")
