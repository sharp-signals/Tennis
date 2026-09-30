"""Bounded, resumable settlement using exclusively local caches.

CHANGE-2026-09-30-067 keeps a durable cursor outside the historical records.
The cursor advances only after an atomic store write returns. Re-running a
batch is safe because both stores settle idempotently.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import (  # noqa: E402
    calibration_store,
    dashboard,
    forward_only,
    green_strong_validation,
    market_ledger,
    market_memory_report,
    paper_trading,
    run_metrics,
)


CHECKPOINT_PATH = ROOT / "data/maintenance/settlement-v1.json"
SNAPSHOTS_PATH = ROOT / "data/calibration_snapshots.json"
PAPER_PATH = ROOT / "data/paper_trades.json"
LEDGER_ROOT = ROOT / "data/market_ledger"
DEFAULT_BATCH_SIZE = 50
DEFAULT_DEADLINE_SECONDS = 150


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def cached_matches(cache_root: Path):
    seen = set()
    for path in cache_root.glob("*/*.json"):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        matches = ((document.get("entries") or {}).get("recent_matches") or {}).get("data") or []
        for match in matches:
            match_id = match.get("id")
            if match_id is not None and str(match_id) not in seen:
                seen.add(str(match_id))
                yield match


def _read_checkpoint(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"schema_version": 1, "cursors": {}}
    if not isinstance(value, Mapping) or value.get("schema_version") != 1:
        return {"schema_version": 1, "cursors": {}}
    return dict(value)


def _atomic_write(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(document, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def _pending_keys(collection: str, path: Path, boundary: forward_only.Boundary) -> list[str]:
    if collection == "snapshots":
        records = calibration_store._read(path).get("snapshots") or []
        pending = [item for item in records if item.get("outcome") is None]
    else:
        records = paper_trading._read(path).get("entries") or []
        pending = [item for item in records if item.get("settlement") is None]
    eligible = []
    for record in pending:
        allowed, _ = forward_only.settlement_eligibility(
            collection, record, boundary=boundary,
        )
        if allowed:
            key = forward_only.record_key(collection, record)
            if key:
                eligible.append(key)
    return sorted(set(eligible))


def _batch(keys: list[str], cursor: str | None, limit: int) -> list[str]:
    if not keys or limit <= 0:
        return []
    start = (keys.index(cursor) + 1) % len(keys) if cursor in keys else 0
    ordered = keys[start:] + keys[:start]
    return ordered[: min(limit, len(ordered))]


def _phase(
    report: dict[str, Any], name: str, operation, *,
    checkpoint: dict[str, Any] | None = None, checkpoint_path: Path | None = None,
):
    started = time.monotonic()
    report["phases"][name] = {"status": "IN_PROGRESS", "started_at_utc": _utc_now()}
    if checkpoint is not None and checkpoint_path is not None:
        checkpoint.update({"last_run": report, "updated_at_utc": _utc_now()})
        _atomic_write(checkpoint_path, checkpoint)
    result = operation()
    report["phases"][name] = {
        "duration_seconds": round(time.monotonic() - started, 4),
        "status": "COMPLETED",
    }
    return result


def run(
    *,
    checkpoint_path: Path = CHECKPOINT_PATH,
    batch_size: int = DEFAULT_BATCH_SIZE,
    deadline_seconds: int = DEFAULT_DEADLINE_SECONDS,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    deadline = started + max(1, deadline_seconds)
    report: dict[str, Any] = {
        "schema_version": 1,
        "change_id": forward_only.CHANGE_ID,
        "started_at_utc": _utc_now(),
        "status": "FAILED",
        "phases": {},
    }
    checkpoint = _read_checkpoint(checkpoint_path)
    cursors = dict(checkpoint.get("cursors") or {})
    boundary = forward_only.load_boundary(manifest_path)
    report["activation_status"] = boundary.reason_code
    settled_total = 0
    checkpoint.update({"last_run": report, "updated_at_utc": _utc_now(), "cursors": cursors})
    _atomic_write(checkpoint_path, checkpoint)

    try:
        matches = _phase(
            report, "read_local_cache",
            lambda: list(cached_matches(ROOT / "data/cache/players")),
            checkpoint=checkpoint, checkpoint_path=checkpoint_path,
        )
        report["cached_matches"] = len(matches)
        batches: dict[str, list[str]] = {}
        for collection, path in (("snapshots", SNAPSHOTS_PATH), ("paper", PAPER_PATH)):
            keys = _pending_keys(collection, path, boundary)
            batches[collection] = _batch(keys, cursors.get(collection), batch_size)
            report.setdefault("candidates", {})[collection] = {
                "eligible_pending": len(keys),
                "batch_size": len(batches[collection]),
                "examined": 0,
                "pending_no_result": 0,
                "remaining_unexamined": len(keys),
            }
        if not any(batches.values()):
            report["status"] = "NO_ELIGIBLE_WORK"
        else:
            snapshot_details: dict[str, Any] = {}
            snapshot_count = _phase(
                report, "snapshot_settlement",
                lambda: calibration_store.settle_from_matches(
                    matches, SNAPSHOTS_PATH,
                    protection_manifest_path=manifest_path,
                    candidate_keys=set(batches["snapshots"]),
                    max_settlements=batch_size,
                    diagnostics=snapshot_details,
                    deadline_monotonic=deadline,
                ),
                checkpoint=checkpoint, checkpoint_path=checkpoint_path,
            )
            report["phases"]["snapshot_settlement"].update(snapshot_details)
            report["phases"]["snapshot_settlement"]["settled"] = snapshot_count
            report["candidates"]["snapshots"].update({
                "examined": int(snapshot_details.get("examined") or 0),
                "pending_no_result": int(snapshot_details.get("pending_no_result") or 0),
                "remaining_unexamined": max(
                    0,
                    report["candidates"]["snapshots"]["eligible_pending"]
                    - int(snapshot_details.get("examined") or 0),
                ),
            })
            settled_total += snapshot_count
            if snapshot_details.get("last_examined_key"):
                cursors["snapshots"] = snapshot_details["last_examined_key"]
                checkpoint.update({"cursors": cursors, "updated_at_utc": _utc_now()})
                _atomic_write(checkpoint_path, checkpoint)
            if snapshot_details.get("deadline_reached") or time.monotonic() >= deadline:
                report["status"] = "TIMED_OUT"
            else:
                paper_details: dict[str, Any] = {}
                paper_count = _phase(
                    report, "paper_settlement",
                    lambda: paper_trading.settle_from_matches(
                        matches, PAPER_PATH, ledger_root=LEDGER_ROOT,
                        protection_manifest_path=manifest_path,
                        candidate_keys=set(batches["paper"]),
                        max_settlements=batch_size,
                        diagnostics=paper_details,
                        deadline_monotonic=deadline,
                    ),
                    checkpoint=checkpoint, checkpoint_path=checkpoint_path,
                )
                report["phases"]["paper_settlement"].update(paper_details)
                report["phases"]["paper_settlement"]["settled"] = paper_count
                report["candidates"]["paper"].update({
                    "examined": int(paper_details.get("examined") or 0),
                    "pending_no_result": int(paper_details.get("pending_no_result") or 0),
                    "remaining_unexamined": max(
                        0,
                        report["candidates"]["paper"]["eligible_pending"]
                        - int(paper_details.get("examined") or 0),
                    ),
                })
                settled_total += paper_count
                if paper_details.get("last_examined_key"):
                    cursors["paper"] = paper_details["last_examined_key"]
                    checkpoint.update({"cursors": cursors, "updated_at_utc": _utc_now()})
                    _atomic_write(checkpoint_path, checkpoint)
                deadline_reached = (
                    paper_details.get("deadline_reached") is True
                    or time.monotonic() >= deadline
                )
                more_work = any(
                    report["candidates"][name].get("remaining_unexamined", 0) > 0
                    for name in ("snapshots", "paper")
                )
                if deadline_reached:
                    report["status"] = "TIMED_OUT"
                else:
                    report["status"] = "PARTIAL" if more_work else "COMPLETED"

        report["work"] = {
            "examined": sum(
                int(values.get("examined") or 0)
                for values in (report.get("candidates") or {}).values()
            ),
            "remaining_unexamined": sum(
                int(values.get("remaining_unexamined") or 0)
                for values in (report.get("candidates") or {}).values()
            ),
            "pending_no_result": sum(
                int(values.get("pending_no_result") or 0)
                for values in (report.get("candidates") or {}).values()
            ),
        }

        if (
            settled_total
            and report["status"] not in {"TIMED_OUT", "FAILED"}
            and time.monotonic() < deadline
        ):
            def rebuild_memory():
                memory = market_memory_report.build_and_write(
                    ledger_root=LEDGER_ROOT,
                    snapshots_path=SNAPSHOTS_PATH,
                    paper_path=PAPER_PATH,
                    output_path=LEDGER_ROOT / "derived/market-memory-v1.json",
                )
                market_ledger.rotate_archives(root=LEDGER_ROOT)
                return memory

            memory = _phase(
                report, "market_memory", rebuild_memory,
                checkpoint=checkpoint, checkpoint_path=checkpoint_path,
            )
            report["phases"]["market_memory"]["observations"] = memory["observation_count"]
            if time.monotonic() >= deadline:
                report["status"] = "TIMED_OUT"
            else:
                _phase(
                    report, "green_projection",
                    lambda: green_strong_validation.build_and_write(
                        memory_report=memory,
                        manual_path=ROOT / "data/manual_paper_22bet.json",
                        output_path=ROOT / "data/validation/green-strong-v1.json",
                    ),
                    checkpoint=checkpoint, checkpoint_path=checkpoint_path,
                )
                if time.monotonic() >= deadline:
                    report["status"] = "TIMED_OUT"
                else:
                    dashboard_status = _phase(
                        report, "dashboard",
                        lambda: dashboard.build_and_write_best_effort(root=ROOT),
                        checkpoint=checkpoint, checkpoint_path=checkpoint_path,
                    )
                    if dashboard_status["status"] != "AVAILABLE":
                        report["phases"]["dashboard"].update({
                            "status": "FAILED",
                            "reason_code": "DASHBOARD_REBUILD_UNAVAILABLE",
                        })
                        report["status"] = "PARTIAL"
        elif settled_total and report["status"] not in {"FAILED", "TIMED_OUT"}:
            report["status"] = "TIMED_OUT"
    except Exception as exc:
        report["status"] = "FAILED"
        report["reason_code"] = f"{type(exc).__name__}:{exc}"

    report["finished_at_utc"] = _utc_now()
    report["duration_seconds"] = round(time.monotonic() - started, 4)
    checkpoint.update({"last_run": report, "updated_at_utc": _utc_now(), "cursors": cursors})
    _atomic_write(checkpoint_path, checkpoint)
    github_run_id = os.environ.get("GITHUB_RUN_ID", "").strip()
    if github_run_id:
        run_metrics.update_persisted_run(
            github_run_id, {"settlement_maintenance": report},
            path=os.environ.get("FENZOBOT_RUN_METRICS_PATH", "data/run_metrics_log.json"),
        )
    return report


def main() -> int:
    report = run(
        batch_size=max(1, int(os.environ.get("SETTLEMENT_BATCH_SIZE", DEFAULT_BATCH_SIZE))),
        deadline_seconds=max(
            1, int(os.environ.get("SETTLEMENT_DEADLINE_SECONDS", DEFAULT_DEADLINE_SECONDS)),
        ),
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] in {"COMPLETED", "NO_ELIGIBLE_WORK"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
