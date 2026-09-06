"""Dashboard estatico e derivado para observacao do Fenzobot.

O modulo le apenas artefactos locais, nunca chama APIs/LLM e nunca altera as
fontes. Ausencia ou corrupcao degrada somente o painel correspondente.
"""

from __future__ import annotations

import gzip
import hashlib
import html
import json
import math
import os
import re
import tempfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import quote

from . import calibration_store, paper_trading, run_metrics


CHANGE_ID = "CHANGE-2026-09-06-027"
SCHEMA_VERSION = 1
MODE = "READ_ONLY_DERIVED_DASHBOARD"
CLAIMS = "OBSERVATIONAL_ONLY"
DEFAULT_OUTPUT_PATH = Path("data/dashboard/fenzobot-dashboard-v1.json")
DEFAULT_HTML_PATH = Path("docs/dashboard/index.html")
REPORT_DATE_RE = re.compile(r"(?P<date>\d{4}-\d{2}-\d{2})(?:-[0-9a-f]{8,64})?$")
SUMMARY_FIELDS = (
    "total_entries",
    "settled",
    "pending",
    "wins",
    "losses",
    "pushes",
    "win_rate_pct",
    "units",
    "roi_pct",
    "yield_pct",
    "average_odd",
)


class _TitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._inside = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() == "title":
            self._inside = True

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "title":
            self._inside = False

    def handle_data(self, data: str) -> None:
        if self._inside:
            self.parts.append(data)

    @property
    def title(self) -> str | None:
        value = " ".join("".join(self.parts).split())
        return value or None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _finite_number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else number


def _read_json(path: Path) -> tuple[Any | None, dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, {"status": "MISSING", "updated_at_utc": None}
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, {
            "status": "INVALID",
            "updated_at_utc": None,
            "error": type(exc).__name__,
        }
    return value, {"status": "AVAILABLE", "updated_at_utc": None}


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _latest_timestamp(values: Iterable[Any]) -> str | None:
    valid = [parsed for parsed in (_parse_datetime(value) for value in values) if parsed]
    return max(valid).isoformat(timespec="seconds") if valid else None


def _safe_title(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            content = handle.read(65536)
        parser = _TitleParser()
        parser.feed(content)
        if parser.title:
            return parser.title
    except (OSError, UnicodeError):
        pass
    return path.stem.replace("-vs-", " vs ").replace("-", " ").strip() or "Relatório"


def _report_date(path: Path) -> str | None:
    match = REPORT_DATE_RE.search(path.stem)
    if not match:
        return None
    value = match.group("date")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None
    return value


def _report_color(snapshot: Mapping[str, Any] | None) -> str:
    flag = _mapping(_mapping(snapshot).get("analysis")).get("flag")
    return {"🟢": "GREEN", "🟡": "YELLOW", "🔴": "RED"}.get(flag, "UNAVAILABLE")


def _green_snapshot_keys(green: Mapping[str, Any]) -> set[str]:
    result = set()
    for row in _list(green.get("eligible_observations")):
        if isinstance(row, Mapping) and row.get("snapshot_key"):
            result.add(str(row["snapshot_key"]))
    return result


def _linked_snapshot(path: Path, snapshots_by_report: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Any] | None:
    stem = path.stem
    candidates = [
        snapshot
        for report_id, snapshot in snapshots_by_report.items()
        if report_id and stem.endswith(f"-{report_id}")
    ]
    return candidates[0] if len(candidates) == 1 else None


def _build_reports(
    reports_dir: Path,
    snapshots: list[Mapping[str, Any]],
    paper_entries: list[Mapping[str, Any]],
    green: Mapping[str, Any],
) -> tuple[list[dict[str, Any]] | None, dict[str, Any]]:
    if not reports_dir.exists() or not reports_dir.is_dir():
        return None, {"status": "MISSING", "updated_at_utc": None}
    try:
        files = sorted(path for path in reports_dir.glob("*.html") if not path.name.startswith("index-"))
    except OSError as exc:
        return None, {"status": "INVALID", "updated_at_utc": None, "error": type(exc).__name__}

    snapshots_by_report = {
        str(snapshot.get("report_id")): snapshot
        for snapshot in snapshots
        if snapshot.get("report_id")
    }
    paper_report_ids = {
        str(_mapping(entry.get("pregame")).get("report_id"))
        for entry in paper_entries
        if _mapping(entry.get("pregame")).get("report_id")
    }
    paper_snapshot_keys = {
        str(_mapping(entry.get("pregame")).get("snapshot_key"))
        for entry in paper_entries
        if _mapping(entry.get("pregame")).get("snapshot_key")
    }
    green_keys = _green_snapshot_keys(green)
    reports = []
    for path in files:
        snapshot = _linked_snapshot(path, snapshots_by_report)
        report_id = str(snapshot.get("report_id")) if snapshot else None
        snapshot_key = str(snapshot.get("key")) if snapshot and snapshot.get("key") else None
        report_day = _report_date(path)
        title = _safe_title(path)
        if snapshot:
            player_a = _mapping(snapshot.get("player_a")).get("name") or snapshot.get("player_a")
            player_b = _mapping(snapshot.get("player_b")).get("name") or snapshot.get("player_b")
            if player_a and player_b:
                title = f"{player_a} vs {player_b}"
        is_green = False
        if snapshot:
            membership = _mapping(
                _mapping(_mapping(snapshot.get("validation")).get("cohorts")).get("GREEN_STRONG_V1")
            )
            is_green = membership.get("eligible") is True or bool(snapshot_key and snapshot_key in green_keys)
        reports.append({
            "title": title,
            "date": report_day,
            "scheduled_start_utc": snapshot.get("commence_time_utc") if snapshot else None,
            "color": _report_color(snapshot),
            "green_strong": is_green,
            "paper_technical": bool(
                snapshot and (report_id in paper_report_ids or snapshot_key in paper_snapshot_keys)
            ),
            "linkage": "EXACT_REPORT_ID" if snapshot else "LEGACY_UNLINKED",
            "url": f"../relatorios/{quote(path.name)}",
        })
    return reports, {
        "status": "AVAILABLE",
        "updated_at_utc": max((item["date"] for item in reports if item["date"]), default=None),
    }


def _group_days(reports: list[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    if reports is None:
        return []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for report in reports:
        day = str(report.get("date") or "UNAVAILABLE")
        grouped.setdefault(day, []).append(dict(report))
    result = []
    for day, items in sorted(grouped.items(), reverse=True):
        colors = Counter(str(item.get("color") or "UNAVAILABLE") for item in items)
        result.append({
            "date": day,
            "counts": {
                "reports": len(items),
                "GREEN": colors["GREEN"],
                "YELLOW": colors["YELLOW"],
                "RED": colors["RED"],
                "UNAVAILABLE": colors["UNAVAILABLE"],
                "GREEN_STRONG": sum(item.get("green_strong") is True for item in items),
                "PAPER_TECHNICAL": sum(item.get("paper_technical") is True for item in items),
            },
            "reports": sorted(items, key=lambda item: (item.get("scheduled_start_utc") or "", item["title"])),
        })
    return result


def _copy_evaluation(value: Any) -> dict[str, Any]:
    source = _mapping(value)
    return {
        "sample_size": _finite_number(source.get("sample_size")),
        "accuracy_pct": _finite_number(source.get("accuracy_pct")),
        "brier_score": _finite_number(source.get("brier_score")),
        "log_loss": _finite_number(source.get("log_loss")),
    }


def _copy_summary(value: Any) -> dict[str, Any]:
    source = _mapping(value)
    return {field: _finite_number(source.get(field)) for field in SUMMARY_FIELDS}


def _copy_summary_collection(value: Any) -> dict[str, dict[str, Any]]:
    return {
        str(name): _copy_summary(summary)
        for name, summary in _mapping(value).items()
        if isinstance(summary, Mapping)
    }


def _paper_technical(
    paper_status: Mapping[str, Any],
    paper_path: Path,
    manual_path: Path,
) -> dict[str, Any]:
    if paper_status.get("status") != "AVAILABLE":
        return {"status": "UNAVAILABLE", **_copy_summary({}), "by_market": {}}
    try:
        history = paper_trading.compute_history(paper_path, manual_path)
    except Exception as exc:
        return {"status": "UNAVAILABLE", "error": type(exc).__name__, **_copy_summary({}), "by_market": {}}
    paper = _mapping(history.get("PAPER"))
    return {
        "status": "AVAILABLE",
        **_copy_summary(paper),
        "by_market": {
            str(name): (_copy_summary(value) if isinstance(value, Mapping) else None)
            for name, value in _mapping(paper.get("by_market")).items()
        },
    }


def _paper_22bet(document: Mapping[str, Any] | None) -> dict[str, Any]:
    if not document:
        return {"status": "UNAVAILABLE", **_copy_summary({}), "by_market": {}, "by_side": {}, "synced_at_utc": None}
    source = _mapping(document.get("source"))
    return {
        "status": "AVAILABLE",
        **_copy_summary(document.get("summary")),
        "by_market": _copy_summary_collection(document.get("by_market")),
        "by_side": _copy_summary_collection(document.get("by_side")),
        "synced_at_utc": source.get("synced_at_utc"),
        "reference_bookmaker": source.get("reference_bookmaker") or "22Bet",
    }


def _guerra_selection(green: Mapping[str, Any] | None) -> dict[str, Any]:
    source = _mapping(_mapping(green).get("guerra_selection_v1"))
    if source.get("status") != "AVAILABLE":
        return {
            "status": "UNAVAILABLE",
            "eligible_green_strong": _finite_number(source.get("eligible_green_strong")),
            "selected_candidates": None,
            "selection_rate_pct": None,
            "paper_entries": None,
            "summary": _copy_summary({}),
            "by_market": {},
            "underdog_pair_completeness": {},
        }
    pair = _mapping(source.get("underdog_pair_completeness"))
    pair_fields = (
        "underdog_selected_candidates",
        "complete_moneyline_positive_handicap_pairs",
        "moneyline_only",
        "positive_handicap_only",
        "incomplete_or_unrecognized",
    )
    return {
        "status": "AVAILABLE",
        "eligible_green_strong": _finite_number(source.get("eligible_green_strong")),
        "selected_candidates": _finite_number(source.get("selected_candidates")),
        "selection_rate_pct": _finite_number(source.get("selection_rate_pct")),
        "paper_entries": _finite_number(source.get("paper_entries")),
        "summary": _copy_summary(source.get("summary")),
        "by_market": _copy_summary_collection(source.get("by_market")),
        "by_side": _copy_summary_collection(source.get("by_side")),
        "underdog_pair_completeness": {field: _finite_number(pair.get(field)) for field in pair_fields},
    }


def _green_strong(document: Mapping[str, Any] | None) -> dict[str, Any]:
    if not document:
        return {
            "status": "UNAVAILABLE",
            "sample": {"candidates": None, "settled": None, "pending": None},
            "forecast": {},
            "proper_scoring": {},
            "market_movement": {},
        }
    metrics = _mapping(document.get("metrics"))
    candidates = _finite_number(metrics.get("sample_size"))
    settled = _finite_number(metrics.get("settled_sample_size"))
    pending = candidates - settled if isinstance(candidates, int) and isinstance(settled, int) else None
    market = _copy_evaluation(metrics.get("market"))
    fenzobot = _copy_evaluation(metrics.get("fenzobot"))
    paired = _mapping(metrics.get("paired_delta"))
    movement = _mapping(metrics.get("closing_movement"))
    return {
        "status": "AVAILABLE",
        "claims": document.get("claims") or "EXPERIMENTAL_NOT_VALIDATED",
        "generated_at_utc": document.get("generated_at_utc"),
        "sample": {"candidates": candidates, "settled": settled, "pending": pending},
        "forecast": {
            "average_market_probability": _finite_number(metrics.get("average_selected_market_probability")),
            "average_fenzobot_probability": _finite_number(metrics.get("average_selected_fenzobot_probability")),
            "observed_win_rate_pct": _finite_number(metrics.get("win_rate_pct")),
        },
        "proper_scoring": {
            "market_brier": market["brier_score"],
            "fenzobot_brier": fenzobot["brier_score"],
            "delta_brier": _finite_number(paired.get("brier")),
            "market_log_loss": market["log_loss"],
            "fenzobot_log_loss": fenzobot["log_loss"],
            "delta_log_loss": _finite_number(paired.get("log_loss")),
            "market_n": market["sample_size"],
            "fenzobot_n": fenzobot["sample_size"],
        },
        "market_movement": {
            "comparable_closing_n": _finite_number(metrics.get("closing_market_comparable")),
            "average_probability_pp": _finite_number(movement.get("average_probability_pp")),
            "median_probability_pp": _finite_number(movement.get("median_probability_pp")),
            "positive_direction_pct": _finite_number(movement.get("positive_direction_pct")),
        },
    }


def _read_ledger_observations(root: Path) -> tuple[list[dict[str, Any]] | None, dict[str, Any]]:
    observations_dir = root / "observations"
    archive_dir = root / "archive"
    files = []
    if observations_dir.is_dir():
        files.extend(sorted(observations_dir.glob("*.jsonl")))
    if archive_dir.is_dir():
        files.extend(sorted(archive_dir.glob("*.jsonl.gz")))
    if not root.exists():
        return None, {"status": "MISSING", "updated_at_utc": None}
    rows: list[dict[str, Any]] = []
    invalid = 0
    for path in files:
        opener = gzip.open if path.suffix == ".gz" else open
        try:
            with opener(path, "rt", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        invalid += 1
                        continue
                    if isinstance(row, dict) and row.get("record_type") == "MARKET_OBSERVATION":
                        rows.append(row)
                    else:
                        invalid += 1
        except (OSError, UnicodeError):
            invalid += 1
    timestamps = [_mapping(row.get("capture")).get("captured_at_utc") for row in rows]
    return rows, {
        "status": "DEGRADED" if invalid else "AVAILABLE",
        "updated_at_utc": _latest_timestamp(timestamps),
        "invalid_records": invalid,
    }


def _observations_by_day(observations: list[Mapping[str, Any]] | None, generated_at_utc: str) -> list[dict[str, Any]]:
    if observations is None:
        return []
    counts: Counter[str] = Counter()
    for row in observations:
        captured = _mapping(row.get("capture")).get("captured_at_utc")
        parsed = _parse_datetime(captured)
        if parsed:
            counts[parsed.date().isoformat()] += 1
    now = _parse_datetime(generated_at_utc) or datetime.now(timezone.utc)
    return [
        {"date": (now.date() - timedelta(days=offset)).isoformat(), "observations": counts[(now.date() - timedelta(days=offset)).isoformat()]}
        for offset in reversed(range(30))
    ]


def _market_memory(
    document: Mapping[str, Any] | None,
    observations: list[Mapping[str, Any]] | None,
    generated_at_utc: str,
) -> dict[str, Any]:
    if not document and observations is None:
        return {
            "status": "UNAVAILABLE",
            "total_observations": None,
            "distinct_events": None,
            "events_with_entry_market": None,
            "events_with_comparable_closing": None,
            "closing_coverage_pct": None,
            "market_only": _copy_evaluation({}),
            "market_plus_fenzobot": _copy_evaluation({}),
            "observations_by_day": [],
        }
    events = [row for row in _list(_mapping(document).get("events")) if isinstance(row, Mapping)]
    event_keys = {str(row.get("event_key")) for row in events if row.get("event_key")}
    with_entry = sum(isinstance(row.get("entry_market_probabilities"), Mapping) for row in events)
    with_closing = sum(isinstance(row.get("last_valid_prestart_market_probabilities"), Mapping) for row in events)
    total = _finite_number(_mapping(document).get("observation_count"))
    if total is None and observations is not None:
        total = len(observations)
    event_count = len(event_keys) if document else len({
        str(_mapping(row.get("event")).get("event_key"))
        for row in observations or []
        if _mapping(row.get("event")).get("event_key")
    })
    evaluation = _mapping(_mapping(document).get("evaluation"))
    return {
        "status": "AVAILABLE",
        "claims": _mapping(document).get("claims") or "EXPERIMENTAL_NOT_VALIDATED",
        "generated_at_utc": _mapping(document).get("generated_at_utc"),
        "total_observations": total,
        "distinct_events": event_count,
        "events_with_entry_market": with_entry if document else None,
        "events_with_comparable_closing": with_closing if document else None,
        "closing_coverage_pct": round(100 * with_closing / event_count, 2) if document and event_count else None,
        "closing_coverage_denominator": "DISTINCT_EVENTS",
        "market_only": _copy_evaluation(evaluation.get("market_only")),
        "market_plus_fenzobot": _copy_evaluation(evaluation.get("market_plus_sharp")),
        "observations_by_day": _observations_by_day(observations, generated_at_utc),
    }


def _system_health(history: list[Any] | None) -> dict[str, Any]:
    entries = [dict(row) for row in history or [] if isinstance(row, Mapping)]
    if not entries:
        return {"status": "UNKNOWN", "latest": None, "alerts": [], "recent_runs": []}
    latest = entries[-1]
    alerts = run_metrics.health_alerts(latest)
    raw_status = str(latest.get("status") or "").casefold()
    status = "FAILED" if raw_status == "failed" else "DEGRADED" if alerts else "HEALTHY"
    allowed = (
        "timestamp", "status", "phase", "eligible", "processed", "analysis_failed",
        "reports_failed", "rapidapi_calls", "llm_calls", "llm_estimated_cost_usd", "duration_seconds",
    )
    recent = []
    for entry in entries[-20:]:
        entry_alerts = run_metrics.health_alerts(entry)
        entry_raw = str(entry.get("status") or "").casefold()
        entry_status = "FAILED" if entry_raw == "failed" else "DEGRADED" if entry_alerts else "HEALTHY"
        recent.append({"timestamp": entry.get("timestamp"), "status": entry_status})
    return {
        "status": status,
        "latest": {field: latest.get(field) for field in allowed},
        "alerts": alerts,
        "recent_runs": recent,
    }


def _source_timestamp(document: Mapping[str, Any] | None, *keys: str) -> str | None:
    for key in keys:
        value = _mapping(document).get(key)
        if value:
            return str(value)
    return None


def build_dashboard(*, root: Path = Path("."), generated_at_utc: str | None = None) -> dict[str, Any]:
    """Constroi a vista apenas a partir de ficheiros locais e campos allowlisted."""
    root = Path(root)
    generated_at = generated_at_utc or _utc_now()
    snapshots_doc, snapshots_status = _read_json(root / "data/calibration_snapshots.json")
    paper_doc, paper_status = _read_json(root / "data/paper_trades.json")
    manual_doc, manual_status = _read_json(root / "data/manual_paper_22bet.json")
    memory_doc, memory_status = _read_json(root / "data/market_ledger/derived/market-memory-v1.json")
    green_doc, green_status = _read_json(root / "data/validation/green-strong-v1.json")
    runs_doc, runs_status = _read_json(root / "data/run_metrics_log.json")

    snapshots = [row for row in _list(_mapping(snapshots_doc).get("snapshots")) if isinstance(row, Mapping)]
    paper_entries = [row for row in _list(_mapping(paper_doc).get("entries")) if isinstance(row, Mapping)]
    green_mapping = _mapping(green_doc)
    reports, reports_status = _build_reports(root / "docs/relatorios", snapshots, paper_entries, green_mapping)
    days = _group_days(reports)
    ledger_rows, ledger_status = _read_ledger_observations(root / "data/market_ledger")

    settled_snapshots = sum(
        _mapping(snapshot.get("outcome")).get("winner_side") in {"a", "b"}
        for snapshot in snapshots
    ) if snapshots_status["status"] == "AVAILABLE" else None
    colors = Counter(str(report.get("color")) for report in reports or [])
    green_panel = _green_strong(green_mapping if green_status["status"] == "AVAILABLE" else None)
    technical = _paper_technical(paper_status, root / "data/paper_trades.json", root / "data/manual_paper_22bet.json")
    manual = _paper_22bet(_mapping(manual_doc) if manual_status["status"] == "AVAILABLE" else None)
    market = _market_memory(
        _mapping(memory_doc) if memory_status["status"] == "AVAILABLE" else None,
        ledger_rows,
        generated_at,
    )
    try:
        accuracy = calibration_store.compute_system_accuracy(root / "data/calibration_snapshots.json")
    except Exception:
        accuracy = None
    report_history = {
        "status": "AVAILABLE" if snapshots_status["status"] == "AVAILABLE" else "UNAVAILABLE",
        "snapshot_universe": {
            "total": len(snapshots) if snapshots_status["status"] == "AVAILABLE" else None,
            "settled": settled_snapshots,
        },
        "divergence": dict(_mapping(accuracy).get("divergencia")) if _mapping(accuracy).get("divergencia") else None,
        "alignment": dict(_mapping(accuracy).get("alinhamento_forte")) if _mapping(accuracy).get("alinhamento_forte") else None,
    }
    run_history = runs_doc if isinstance(runs_doc, list) and runs_status["status"] == "AVAILABLE" else None
    health = _system_health(run_history)

    snapshots_status["updated_at_utc"] = _source_timestamp(_mapping(snapshots_doc), "updated_at_utc")
    paper_status["updated_at_utc"] = _source_timestamp(_mapping(paper_doc), "updated_at_utc")
    manual_status["updated_at_utc"] = _mapping(_mapping(manual_doc).get("source")).get("synced_at_utc")
    memory_status["updated_at_utc"] = _source_timestamp(_mapping(memory_doc), "generated_at_utc")
    green_status["updated_at_utc"] = _source_timestamp(_mapping(green_doc), "generated_at_utc")
    runs_status["updated_at_utc"] = _latest_timestamp(
        row.get("timestamp") for row in run_history or [] if isinstance(row, Mapping)
    )

    dashboard = {
        "schema_version": SCHEMA_VERSION,
        "change_id": CHANGE_ID,
        "mode": MODE,
        "generated_at_utc": generated_at,
        "claims": CLAIMS,
        "source_freshness": {
            "reports": reports_status,
            "snapshots": snapshots_status,
            "paper_technical": paper_status,
            "paper_22bet": manual_status,
            "market_memory": memory_status,
            "market_ledger": ledger_status,
            "green_strong_v1": green_status,
            "run_metrics": runs_status,
        },
        "global": {
            "total_reports": len(reports) if reports is not None else None,
            "total_snapshots": len(snapshots) if snapshots_status["status"] == "AVAILABLE" else None,
            "settled_snapshots": settled_snapshots,
            "report_colors": {
                "GREEN": colors["GREEN"] if reports is not None else None,
                "YELLOW": colors["YELLOW"] if reports is not None else None,
                "RED": colors["RED"] if reports is not None else None,
                "UNAVAILABLE": colors["UNAVAILABLE"] if reports is not None else None,
            },
            "green_strong_candidates": green_panel["sample"]["candidates"],
            "paper_technical_entries": technical.get("total_entries"),
            "paper_22bet_entries": manual.get("total_entries"),
            "market_observations": market.get("total_observations"),
        },
        "report_history": report_history,
        "market_memory": market,
        "green_strong_v1": green_panel,
        "guerra_selection_v1": _guerra_selection(green_mapping if green_status["status"] == "AVAILABLE" else None),
        "paper_technical": technical,
        "paper_22bet": manual,
        "system_health": health,
        "days": days,
    }
    fingerprint_payload = dict(dashboard)
    fingerprint_payload.pop("generated_at_utc", None)
    dashboard["semantic_fingerprint"] = hashlib.sha256(
        json.dumps(fingerprint_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return dashboard


def _script_json(value: Mapping[str, Any]) -> str:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def render_dashboard_html(data: Mapping[str, Any]) -> str:
    """Renderiza um unico documento sem CDN, backend ou dependencias externas."""
    embedded = _script_json(data)
    return f"""<!doctype html>
<html lang="pt"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>Fenzobot Control</title>
<style>
:root{{--bg:#080d13;--panel:#111923;--panel2:#162231;--line:#26384b;--text:#edf4fb;--dim:#8fa5bc;--steel:#58a6d8;--green:#35d49a;--yellow:#efbd4e;--red:#f06b6b;--amber:#e6a93d}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 Inter,"Segoe UI",system-ui,sans-serif;font-variant-numeric:tabular-nums}}
button,a{{font:inherit}}button{{color:inherit}}.shell{{min-height:100vh;display:grid;grid-template-columns:minmax(280px,25vw) 1fr}}
.sidebar{{height:100vh;position:sticky;top:0;overflow:auto;border-right:1px solid var(--line);background:#0c131c;padding:24px 18px}}
.brand{{letter-spacing:.15em;font-size:11px;color:var(--steel);text-transform:uppercase}}.sidebar h2{{font-size:16px;margin:8px 0 18px}}
.day{{border:1px solid var(--line);border-radius:12px;margin:0 0 10px;background:var(--panel);overflow:hidden}}.day[open]{{border-color:#365573}}
.day summary{{cursor:pointer;padding:12px 13px;list-style:none}}.day summary::-webkit-details-marker{{display:none}}.day-head{{display:flex;justify-content:space-between;gap:10px;font-weight:700}}
.day-meta{{color:var(--dim);font-size:12px;margin-top:4px}}.reports{{border-top:1px solid var(--line);padding:7px}}
.report{{display:block;color:var(--text);text-decoration:none;border-radius:8px;padding:9px 8px;margin:2px 0}}.report:hover,.report:focus{{background:#1a2939;outline:none}}
.report-top{{display:flex;gap:7px;align-items:center}}.report-title{{font-size:13px;font-weight:650;min-width:0}}.report-meta{{font-size:11px;color:var(--dim);margin:3px 0 0 20px}}
.dot{{width:9px;height:9px;border-radius:50%;flex:0 0 auto;background:#647386}}.dot.GREEN{{background:var(--green)}}.dot.YELLOW{{background:var(--yellow)}}.dot.RED{{background:var(--red)}}
.badge{{display:inline-flex;border:1px solid #3a526b;border-radius:999px;padding:1px 6px;font-size:9px;letter-spacing:.04em;margin-left:4px;color:#bdd3e7}}.badge.gs{{border-color:#278b70;color:var(--green)}}
.main{{min-width:0;padding:28px clamp(20px,3vw,48px) 60px}}.top{{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;margin-bottom:22px}}
h1{{font-size:clamp(24px,3vw,36px);letter-spacing:.08em;margin:0}}.subtitle{{color:var(--dim);margin-top:6px}}.updated{{color:var(--dim);font-size:12px;text-align:right}}
.toggle{{display:inline-flex;background:var(--panel);border:1px solid var(--line);padding:4px;border-radius:10px;margin-top:12px}}.toggle button{{border:0;background:transparent;padding:8px 13px;border-radius:7px;cursor:pointer;color:var(--dim)}}.toggle button.active{{background:#24415b;color:#fff}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:12px;margin:0 0 18px}}.card{{border:1px solid var(--line);border-radius:13px;background:var(--panel);padding:15px;text-align:left}}
button.card{{cursor:pointer}}button.card:hover{{border-color:var(--steel)}}.card .label{{color:var(--dim);font-size:11px;text-transform:uppercase;letter-spacing:.08em}}.card .value{{font-size:27px;font-weight:750;margin-top:4px}}.card.GREEN .value{{color:var(--green)}}.card.YELLOW .value{{color:var(--yellow)}}.card.RED .value{{color:var(--red)}}
.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:15px}}.panel{{border:1px solid var(--line);border-radius:15px;background:var(--panel);padding:18px;min-width:0}}.panel.wide{{grid-column:1/-1}}.panel.feature{{border-color:#2b806c;background:linear-gradient(145deg,#11241f,var(--panel) 58%)}}
.panel h2{{font-size:15px;letter-spacing:.08em;text-transform:uppercase;margin:0 0 3px}}.eyebrow{{color:var(--dim);font-size:10px;letter-spacing:.12em;text-transform:uppercase;margin-bottom:15px}}.metrics{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px}}
.metric{{background:var(--panel2);border:1px solid #223950;border-radius:10px;padding:11px}}.metric span{{display:block;color:var(--dim);font-size:10px;text-transform:uppercase;letter-spacing:.05em}}.metric strong{{display:block;font-size:18px;margin-top:4px;overflow-wrap:anywhere}}.metric small{{display:block;color:var(--dim);font-size:10px;margin-top:2px}}
.note{{border-left:3px solid var(--steel);padding:10px 12px;background:#132131;color:#b9cbe0;border-radius:0 8px 8px 0;margin:12px 0}}.note.warning{{border-color:var(--yellow)}}
.split{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}}.rows{{margin-top:12px}}.row{{display:flex;justify-content:space-between;gap:20px;padding:8px 0;border-bottom:1px solid #213142}}.row:last-child{{border-bottom:0}}.row span{{color:var(--dim)}}
.chart{{height:155px;display:flex;align-items:end;gap:3px;padding:12px 2px 22px;margin-top:8px;border-bottom:1px solid var(--line)}}.bar{{flex:1;min-width:2px;background:linear-gradient(#64b6e8,#2e658b);border-radius:3px 3px 0 0;position:relative}}.bar:hover{{background:var(--green)}}
.health{{display:inline-flex;padding:5px 9px;border-radius:999px;border:1px solid var(--line);font-weight:750}}.health.HEALTHY{{color:var(--green);border-color:#27785f}}.health.DEGRADED{{color:var(--yellow);border-color:#806822}}.health.FAILED{{color:var(--red);border-color:#884343}}
.spark{{width:100%;height:55px;margin-top:12px}}.fresh{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:8px}}.fresh div{{background:var(--panel2);padding:9px;border-radius:8px}}.fresh small{{display:block;color:var(--dim)}}
.empty{{color:var(--dim);padding:22px 0}}.filter-note{{color:var(--dim);font-size:12px;margin:-8px 0 16px}}.filter-clear{{background:transparent;border:0;color:var(--steel);cursor:pointer;text-decoration:underline}}
.top a,.panel a{{color:var(--steel)}}[hidden]{{display:none!important}}
@media(max-width:900px){{.shell{{grid-template-columns:1fr}}.sidebar{{position:relative;height:auto;max-height:48vh;border-right:0;border-bottom:1px solid var(--line)}}.grid{{grid-template-columns:1fr}}.panel.wide{{grid-column:auto}}.top{{flex-direction:column}}.updated{{text-align:left}}}}
@media(max-width:560px){{.main{{padding:20px 14px 40px}}.metrics{{grid-template-columns:repeat(2,minmax(0,1fr))}}.split{{grid-template-columns:1fr}}}}
</style></head><body>
<div class="shell"><aside class="sidebar"><div class="brand">Fenzo Intelligence</div><h2>Histórico de relatórios</h2><div id="days"></div></aside>
<main class="main"><header class="top"><div><h1>FENZOBOT CONTROL</h1><div class="subtitle">Superfície read-only · dados derivados · sem execução</div><div class="toggle" role="group" aria-label="Âmbito"><button id="day-toggle">DIA SELECIONADO</button><button id="global-toggle">GLOBAL</button></div></div><div class="updated"><a href="../">Todos os relatórios</a><br><span id="generated"></span></div></header><section id="content"></section></main></div>
<script>
const DATA={embedded};
const nf=new Intl.NumberFormat('pt-PT',{{maximumFractionDigits:2}});
const state={{scope:DATA.days.length?'DAY':'GLOBAL',day:DATA.days[0]?.date||null,filter:'ALL'}};
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
const val=(v,s='')=>v===null||v===undefined?'N/D':`${{typeof v==='number'?nf.format(v):esc(v)}}${{s}}`;
const pct=v=>val(v,'%'); const prob=v=>v===null||v===undefined?'N/D':pct(100*v);
const fmtTime=v=>{{if(!v)return'N/D';const d=new Date(v);return Number.isNaN(d.valueOf())?'N/D':d.toLocaleString('pt-PT',{{dateStyle:'short',timeStyle:'short'}})}};
const dayLabel=v=>v==='UNAVAILABLE'?'DATA N/D':new Date(v+'T12:00:00Z').toLocaleDateString('pt-PT',{{day:'2-digit',month:'short',year:'numeric'}}).toUpperCase();
const metric=(label,value,suffix='',detail='')=>`<div class="metric"><span>${{esc(label)}}</span><strong>${{val(value,suffix)}}</strong>${{detail?`<small>${{esc(detail)}}</small>`:''}}</div>`;
const cards=items=>`<div class="cards">${{items.map(x=>`<${{x.filter?'button':'div'}} class="card ${{x.cls||''}}" ${{x.filter?`data-filter="${{x.filter}}" title="Filtrar relatórios deste dia"`:''}}><div class="label">${{esc(x.label)}}</div><div class="value">${{val(x.value)}}</div></${{x.filter?'button':'div'}}>`).join('')}}</div>`;
function renderSidebar(){{const host=document.getElementById('days');if(!DATA.days.length){{host.innerHTML='<div class="empty">Sem relatórios disponíveis.</div>';return}}host.innerHTML=DATA.days.map((day,i)=>{{const c=day.counts;const reports=day.reports.filter(r=>day.date!==state.day||state.filter==='ALL'||r.color===state.filter);return `<details class="day" ${{day.date===state.day||(!state.day&&i===0)?'open':''}} data-day="${{esc(day.date)}}"><summary><div class="day-head"><span>▾ ${{dayLabel(day.date)}}</span><span>${{c.reports}}</span></div><div class="day-meta">${{c.reports}} reports · 🟢${{c.GREEN}} · 🟡${{c.YELLOW}} · 🔴${{c.RED}} · GS ${{c.GREEN_STRONG}}</div></summary><div class="reports">${{reports.length?reports.map(r=>`<a class="report" href="${{esc(r.url)}}"><div class="report-top"><i class="dot ${{r.color}}"></i><span class="report-title">${{esc(r.title)}}</span>${{r.green_strong?'<b class="badge gs">GS</b>':''}}${{r.paper_technical?'<b class="badge">PAPER</b>':''}}</div><div class="report-meta">${{fmtTime(r.scheduled_start_utc)}} · ${{r.linkage==='EXACT_REPORT_ID'?'ligação exata':'legacy · metadata N/D'}}</div></a>`).join(''):'<div class="empty">Sem relatórios neste filtro.</div>'}}</div></details>`}}).join('');host.querySelectorAll('.day').forEach(el=>el.addEventListener('toggle',()=>{{if(el.open&&el.dataset.day!==state.day){{state.day=el.dataset.day;state.scope='DAY';state.filter='ALL';render()}}}}))}}
function panel(title,eyebrow,body,cls=''){{return `<article class="panel ${{cls}}"><h2>${{esc(title)}}</h2><div class="eyebrow">${{esc(eyebrow)}}</div>${{body}}</article>`}}
function summaryRows(obj){{return `<div class="rows">${{[['Entradas',obj.total_entries],['Liquidadas',obj.settled],['Pendentes',obj.pending],['W–L',obj.wins==null||obj.losses==null?null:`${{obj.wins}}–${{obj.losses}}`],['Win rate',obj.win_rate_pct==null?null:pct(obj.win_rate_pct)],['Unidades',obj.units],['ROI',obj.roi_pct==null?null:pct(obj.roi_pct)],['Odd média',obj.average_odd]].map(([k,v])=>`<div class="row"><span>${{k}}</span><b>${{v==null?'N/D':v}}</b></div>`).join('')}}</div>`}}
function globalView(){{const g=DATA.global,h=DATA.report_history,gs=DATA.green_strong_v1,gu=DATA.guerra_selection_v1,mm=DATA.market_memory,pt=DATA.paper_technical,p22=DATA.paper_22bet,sh=DATA.system_health;let out=cards([{{label:'Relatórios',value:g.total_reports}},{{label:'Snapshots',value:g.total_snapshots}},{{label:'Liquidados',value:g.settled_snapshots}},{{label:'Verdes',value:g.report_colors.GREEN,cls:'GREEN'}},{{label:'Amarelos',value:g.report_colors.YELLOW,cls:'YELLOW'}},{{label:'Vermelhos',value:g.report_colors.RED,cls:'RED'}},{{label:'GREEN_STRONG',value:g.green_strong_candidates}},{{label:'PAPER técnico',value:g.paper_technical_entries}},{{label:'PAPER 22Bet',value:g.paper_22bet_entries}},{{label:'Market obs.',value:g.market_observations}}]);out+='<div class="grid">';
out+=panel('Histórico dos relatórios','Snapshot universe',`<div class="metrics">${{metric('Snapshots',h.snapshot_universe.total)}}${{metric('Liquidados',h.snapshot_universe.settled)}}</div><div class="split"><div><h3>Divergência</h3>${{h.divergence?`${{metric('Acertos',h.divergence.acertos)}}${{metric('N',h.divergence.total)}}${{metric('Taxa',h.divergence.taxa_pct,'%')}}${{metric('Intervalo',h.divergence.intervalo_pct?.join('–')||null,'%')}}`:'<div class="empty">N/D — amostra mínima não atingida ou fonte indisponível.</div>'}}</div><div><h3>Alinhamento</h3>${{h.alignment?`${{metric('Acertos',h.alignment.acertos)}}${{metric('N',h.alignment.total)}}${{metric('Taxa',h.alignment.taxa_pct,'%')}}${{metric('Intervalo',h.alignment.intervalo_pct?.join('–')||null,'%')}}`:'<div class="empty">N/D — amostra mínima não atingida ou fonte indisponível.</div>'}}</div></div>`);
const zero=gs.sample.candidates===0;out+=panel('GREEN_STRONG_V1','Prospective shadow validation',`${{zero?'<div class="note warning">N=0 — acumulação prospetiva iniciada. Sem conclusão possível.</div>':''}}<div class="metrics">${{metric('Candidatos',gs.sample.candidates)}}${{metric('Liquidados',gs.sample.settled)}}${{metric('Pendentes',gs.sample.pending)}}${{metric('Mercado médio',gs.forecast.average_market_probability==null?null:100*gs.forecast.average_market_probability,'%')}}${{metric('Fenzobot médio',gs.forecast.average_fenzobot_probability==null?null:100*gs.forecast.average_fenzobot_probability,'%')}}${{metric('Win rate observado',gs.forecast.observed_win_rate_pct,'%')}}</div><h3>Proper scoring</h3><div class="metrics">${{metric('Market Brier',gs.proper_scoring.market_brier,'',`N=${{val(gs.proper_scoring.market_n)}}`)}}${{metric('Fenzobot Brier',gs.proper_scoring.fenzobot_brier,'',`N=${{val(gs.proper_scoring.fenzobot_n)}}`)}}${{metric('Δ Brier',gs.proper_scoring.delta_brier)}}${{metric('Market Log Loss',gs.proper_scoring.market_log_loss)}}${{metric('Fenzobot Log Loss',gs.proper_scoring.fenzobot_log_loss)}}${{metric('Δ Log Loss',gs.proper_scoring.delta_log_loss)}}</div><h3>Market movement</h3><div class="metrics">${{metric('Closing comparável N',gs.market_movement.comparable_closing_n)}}${{metric('Movimento médio',gs.market_movement.average_probability_pp,' p.p.')}}${{metric('Mediana',gs.market_movement.median_probability_pp,' p.p.')}}${{metric('Na direção Fenzobot',gs.market_movement.positive_direction_pct,'%')}}</div>`, 'wide feature');
out+=panel('GUERRA_SELECTION_V1','Manual paper strategy',`${{gu.status!=='AVAILABLE'?'<div class="note">N/D — agregado público ainda indisponível.</div>':''}}<div class="metrics">${{metric('GS elegíveis',gu.eligible_green_strong)}}${{metric('Candidatos selecionados',gu.selected_candidates)}}${{metric('Taxa de seleção',gu.selection_rate_pct,'%')}}${{metric('Entradas / legs',gu.paper_entries)}}</div>${{summaryRows(gu.summary)}}<h3>Completude underdog</h3><div class="metrics">${{metric('Underdogs selecionados',gu.underdog_pair_completeness.underdog_selected_candidates)}}${{metric('Pares completos',gu.underdog_pair_completeness.complete_moneyline_positive_handicap_pairs)}}${{metric('Só Moneyline',gu.underdog_pair_completeness.moneyline_only)}}${{metric('Só handicap +',gu.underdog_pair_completeness.positive_handicap_only)}}${{metric('Incompleto / N/D',gu.underdog_pair_completeness.incomplete_or_unrecognized)}}</div>`);
const bars=mm.observations_by_day||[];const max=Math.max(1,...bars.map(x=>x.observations));out+=panel('Market Memory / Odds History','Experimental · not validated',`<div class="metrics">${{metric('Observações',mm.total_observations)}}${{metric('Eventos distintos',mm.distinct_events)}}${{metric('Com entry market',mm.events_with_entry_market)}}${{metric('Closing comparável',mm.events_with_comparable_closing)}}${{metric('Cobertura closing',mm.closing_coverage_pct,'%')}}${{metric('Market-only N',mm.market_only.sample_size)}}${{metric('Market + Fenzobot N',mm.market_plus_fenzobot.sample_size)}}</div><div class="split"><div><h3>Market-only</h3>${{metric('Brier',mm.market_only.brier_score)}}${{metric('Log Loss',mm.market_only.log_loss)}}</div><div><h3>Market + Fenzobot</h3>${{metric('Brier',mm.market_plus_fenzobot.brier_score)}}${{metric('Log Loss',mm.market_plus_fenzobot.log_loss)}}</div></div><h3>Observações por dia · últimos 30 dias</h3><div class="chart" aria-label="Market observations by day">${{bars.map(x=>`<i class="bar" style="height:${{Math.max(2,100*x.observations/max)}}%" title="${{esc(x.date)}}: ${{x.observations}}"></i>`).join('')}}</div>`,'wide');
out+=panel('PAPER técnico','Universo PAPER automático',summaryRows(pt));out+=panel('PAPER manual 22Bet','Agregados públicos apenas',`${{summaryRows(p22)}}<div class="note">22Bet source synced at: ${{fmtTime(p22.synced_at_utc)}}</div><h3>Mercados</h3><div class="rows">${{Object.entries(p22.by_market||{{}}).map(([k,v])=>`<div class="row"><span>${{esc(k)}}</span><b>${{val(v.total_entries)}} entradas</b></div>`).join('')||'<div class="empty">N/D</div>'}}</div>`);
const latest=sh.latest||{{}};const pts=(sh.recent_runs||[]).map((x,i,a)=>`${{a.length<2?0:100*i/(a.length-1)}},${{x.status==='HEALTHY'?8:x.status==='DEGRADED'?28:48}}`).join(' ');out+=panel('System Health','Alertas existentes · sem thresholds novos',`<span class="health ${{sh.status}}">${{sh.status}}</span><div class="metrics" style="margin-top:12px">${{metric('Timestamp',latest.timestamp?fmtTime(latest.timestamp):null)}}${{metric('Fase',latest.phase)}}${{metric('Elegíveis',latest.eligible)}}${{metric('Processados',latest.processed)}}${{metric('Analysis failed',latest.analysis_failed)}}${{metric('Reports failed',latest.reports_failed)}}${{metric('RapidAPI calls',latest.rapidapi_calls)}}${{metric('LLM calls',latest.llm_calls)}}${{metric('Custo LLM USD',latest.llm_estimated_cost_usd)}}${{metric('Duração',latest.duration_seconds,' s')}}</div>${{sh.alerts.length?`<div class="note warning">${{sh.alerts.map(esc).join('<br>')}}</div>`:''}}<svg class="spark" viewBox="0 0 100 55" preserveAspectRatio="none" aria-label="Saúde das últimas runs"><polyline fill="none" stroke="#58a6d8" stroke-width="2" points="${{pts}}"/></svg>`,'wide');
out+=panel('Frescura das fontes','Momento conhecido de cada artefacto',`<div class="fresh">${{Object.entries(DATA.source_freshness).map(([name,src])=>`<div><b>${{esc(name)}}</b><small>${{esc(src.status)}} · ${{src.updated_at_utc?fmtTime(src.updated_at_utc):'N/D'}}</small></div>`).join('')}}</div>`,'wide');return out+'</div>'}}
function dayView(){{const day=DATA.days.find(x=>x.date===state.day);if(!day)return'<div class="empty">Dia não disponível.</div>';const c=day.counts;return `<h2>${{dayLabel(day.date)}}</h2>${{cards([{{label:'Relatórios',value:c.reports}},{{label:'Verdes',value:c.GREEN,cls:'GREEN',filter:'GREEN'}},{{label:'Amarelos',value:c.YELLOW,cls:'YELLOW',filter:'YELLOW'}},{{label:'Vermelhos',value:c.RED,cls:'RED',filter:'RED'}},{{label:'N/D',value:c.UNAVAILABLE,filter:'UNAVAILABLE'}},{{label:'GREEN_STRONG',value:c.GREEN_STRONG}},{{label:'PAPER técnico',value:c.PAPER_TECHNICAL}}])}}<div class="filter-note">${{state.filter==='ALL'?'Clique num card de cor para filtrar a lista do dia.':`Filtro ativo: ${{esc(state.filter)}} · `+'<button class="filter-clear">limpar</button>'}}</div><div class="panel"><h2>Leitura do dia</h2><div class="eyebrow">Estado visual não é validação</div><p>GREEN_STRONG e PAPER técnico são universos separados da cor operacional do relatório. GUERRA_SELECTION_V1 não é mostrado por jogo porque a fonte pública é deliberadamente agregada.</p></div>`}}
function render(){{document.getElementById('generated').textContent='Gerado em '+fmtTime(DATA.generated_at_utc);document.getElementById('day-toggle').classList.toggle('active',state.scope==='DAY');document.getElementById('global-toggle').classList.toggle('active',state.scope==='GLOBAL');document.getElementById('content').innerHTML=state.scope==='GLOBAL'?globalView():dayView();document.querySelectorAll('[data-filter]').forEach(b=>b.addEventListener('click',()=>{{state.filter=b.dataset.filter;render()}}));document.querySelector('.filter-clear')?.addEventListener('click',()=>{{state.filter='ALL';render()}});renderSidebar()}}
document.getElementById('day-toggle').addEventListener('click',()=>{{state.scope='DAY';render()}});document.getElementById('global-toggle').addEventListener('click',()=>{{state.scope='GLOBAL';state.filter='ALL';render()}});render();
</script></body></html>"""


def _atomic_write_text(path: Path, content: str) -> bool:
    try:
        if path.read_text(encoding="utf-8") == content:
            return False
    except (FileNotFoundError, OSError, UnicodeError):
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        os.replace(temp_path, path)
        temp_path = None
        return True
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)


def build_and_write(
    *,
    root: Path = Path("."),
    output_path: Path | None = None,
    html_path: Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    root = Path(root)
    output = output_path or root / DEFAULT_OUTPUT_PATH
    page = html_path or root / DEFAULT_HTML_PATH
    dashboard = build_dashboard(root=root, generated_at_utc=generated_at_utc)
    previous, _ = _read_json(output)
    if (
        isinstance(previous, Mapping)
        and previous.get("semantic_fingerprint") == dashboard["semantic_fingerprint"]
        and previous.get("generated_at_utc")
    ):
        dashboard["generated_at_utc"] = previous["generated_at_utc"]
    json_content = json.dumps(dashboard, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _atomic_write_text(output, json_content)
    _atomic_write_text(page, render_dashboard_html(dashboard))
    return dashboard


def build_and_write_best_effort(**kwargs: Any) -> dict[str, Any]:
    """Fronteira nao bloqueante para pipeline, settlement e rebuild manual."""
    try:
        dashboard = build_and_write(**kwargs)
    except Exception as exc:
        return {"status": "UNAVAILABLE", "error": f"{type(exc).__name__}: {exc}"}
    return {
        "status": "AVAILABLE",
        "generated_at_utc": dashboard["generated_at_utc"],
        "semantic_fingerprint": dashboard["semantic_fingerprint"],
    }
