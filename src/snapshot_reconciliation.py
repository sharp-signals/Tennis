"""Deterministic, offline reconciliation of reports and immutable snapshots."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from . import snapshot_identity


SCHEMA_VERSION = 1
CHANGE_ID = "CHANGE-2026-09-21-047"
METRIC_ID = "SNAPSHOT_COVERAGE_RECONCILIATION_V1"
WINDOW_DAYS = 7


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _date(value: Any) -> date | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        return None


def _report_days(reports: Iterable[Mapping[str, Any]]) -> list[date]:
    return [parsed for parsed in (_date(row.get("date")) for row in reports) if parsed]


def _run_identities(
    runs: Iterable[Mapping[str, Any]], start: date, end: date,
) -> list[dict[str, Any]]:
    unique: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {}
    for run in runs:
        run_day = _date(run.get("timestamp"))
        if run_day is None or not start <= run_day <= end:
            continue
        matches = _mapping(run.get("event_identity")).get("matches")
        if not isinstance(matches, list):
            continue
        for row in matches:
            if not isinstance(row, Mapping):
                continue
            tour = snapshot_identity.normalize_name(row.get("tour"))
            match_id = row.get("match_key")
            players = row.get("players") if isinstance(row.get("players"), list) else []
            pair = tuple(sorted(snapshot_identity.normalize_name(name) for name in players if name))
            if not tour or match_id in (None, "") or len(pair) != 2 or not all(pair):
                signature = (f"{tour}:{match_id}", pair)
                unique.setdefault(signature, {
                    "key": f"{tour}:{match_id}", "candidate": None,
                    "reason_code": "SNAPSHOT_IDENTITY_INSUFFICIENT",
                })
                continue
            key = f"{tour}:{match_id}"
            signature = (key, pair)
            unique.setdefault(signature, {
                "key": key,
                "candidate": {"tour": tour, "player_a": players[0], "player_b": players[1]},
            })
    return list(unique.values())


def build(
    *,
    reports: list[Mapping[str, Any]] | None,
    days: list[Mapping[str, Any]],
    snapshots: list[Mapping[str, Any]],
    runs: list[Mapping[str, Any]] | None,
    generated_at_utc: str,
    window_days: int = WINDOW_DAYS,
) -> dict[str, Any]:
    report_rows = list(reports or [])
    available_days = _report_days(report_rows)
    end = max(available_days, default=_date(generated_at_utc) or datetime.now(timezone.utc).date())
    start = end - timedelta(days=max(1, int(window_days)) - 1)
    window_reports = [
        row for row in report_rows
        if start <= (_date(row.get("date")) or date.min) <= end
    ]
    window_day_rows = [row for row in days if start <= (_date(row.get("date")) or date.min) <= end]
    versions = len(window_reports)
    matchups = sum(int(_mapping(row.get("counts")).get("matchups") or 0) for row in window_day_rows)
    linked_exact_versions = sum(row.get("linkage") == "EXACT_REPORT_ID" for row in window_reports)
    # Linkage buckets are mutually exclusive. An exact report may also carry
    # self-described HTML metadata, but it remains EXACT_REPORT_ID here.
    self_described_versions = sum(
        row.get("linkage") == "SELF_DESCRIBED_REPORT" for row in window_reports
    )
    report_collision_versions = sum(
        row.get("linkage") == "SNAPSHOT_IDENTITY_COLLISION" for row in window_reports
    )

    snapshot_by_key = {
        str(row.get("key")): row for row in snapshots
        if isinstance(row, Mapping) and row.get("key") not in (None, "")
    }
    identities = _run_identities(runs or [], start, end)
    identity_reasons: Counter[str] = Counter()
    for identity in identities:
        candidate = identity.get("candidate")
        persisted = snapshot_by_key.get(str(identity.get("key")))
        if candidate is None:
            identity_reasons[str(identity.get("reason_code"))] += 1
        elif persisted is None:
            identity_reasons["SNAPSHOT_KEY_NOT_PERSISTED"] += 1
        else:
            comparison = snapshot_identity.compare(candidate, persisted)
            identity_reasons[str(comparison.get("reason_code"))] += 1

    eligible = len(identities)
    collisions = identity_reasons["PROVIDER_MATCH_ID_REUSED"]
    identity_matches = identity_reasons["SNAPSHOT_IDENTITY_MATCH"]
    insufficient = identity_reasons["SNAPSHOT_IDENTITY_INSUFFICIENT"]
    missing = identity_reasons["SNAPSHOT_KEY_NOT_PERSISTED"]
    duplicate_versions = max(0, versions - matchups)
    observed_without_telemetry = max(0, matchups - eligible)
    if duplicate_versions:
        identity_reasons["DUPLICATE_REPORT_VERSION"] = duplicate_versions
    if observed_without_telemetry:
        identity_reasons["OBSERVED_MATCHUP_WITHOUT_IDENTITY_TELEMETRY"] = observed_without_telemetry

    created = [
        row for row in snapshots
        if start <= (_date(row.get("analyzed_at_utc")) or date.min) <= end
    ]
    settled = sum(
        _mapping(row.get("outcome")).get("winner_side") in {"a", "b"}
        for row in created
    )
    eligible_without_snapshot = collisions + insufficient + missing
    coverage = round(100 * identity_matches / eligible, 2) if eligible else None
    settlement_coverage = round(100 * settled / len(created), 2) if created else None
    status = "DEGRADED" if collisions or insufficient or missing else "AVAILABLE"
    if reports is None or runs is None:
        status = "UNAVAILABLE"

    return {
        "schema_version": SCHEMA_VERSION,
        "change_id": CHANGE_ID,
        "metric_id": METRIC_ID,
        "status": status,
        "window": {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "days": (end - start).days + 1,
        },
        "counts": {
            "matchups_observed": matchups if reports is not None else None,
            "report_versions": versions if reports is not None else None,
            "duplicate_report_versions": duplicate_versions if reports is not None else None,
            "linked_exact_versions": linked_exact_versions if reports is not None else None,
            "self_described_versions": self_described_versions if reports is not None else None,
            "collision_marked_report_versions": report_collision_versions if reports is not None else None,
            "eligible_run_identities": eligible if runs is not None else None,
            "snapshot_identity_matches": identity_matches if runs is not None else None,
            "eligible_without_snapshot": eligible_without_snapshot if runs is not None else None,
            "provider_match_id_collisions": collisions if runs is not None else None,
            "snapshots_created": len(created),
            "snapshots_settled": settled,
        },
        "conversion": {
            "eligible_to_snapshot_pct": coverage,
            "created_to_settled_pct": settlement_coverage,
        },
        "absence_reason_codes": dict(sorted(identity_reasons.items())),
        "integrity": {
            "eligible_identities_reconciled": eligible == identity_matches + collisions + insufficient + missing,
            "versions_reconciled": versions == matchups + duplicate_versions,
            "no_backfill": True,
            "identity_contract": "LEGACY_KEY_PLUS_BILATERAL_PLAYERS_AND_CONTEXT_CONTAINMENT",
            "time_tolerance_hours": snapshot_identity.TIME_TOLERANCE_HOURS,
        },
    }
