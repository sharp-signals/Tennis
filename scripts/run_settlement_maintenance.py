"""External settlement supervisor that persists a hard timeout after killing its child."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import update_calibration_outcomes as maintenance  # noqa: E402
from src import forward_only, run_metrics  # noqa: E402


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def supervise(
    *, command: Sequence[str], checkpoint_path: Path, timeout_seconds: float,
    metrics_path: Path | None = None, github_run_id: str = "",
) -> dict:
    checkpoint = maintenance._read_checkpoint(checkpoint_path)
    report = {
        "schema_version": 1, "change_id": forward_only.CHANGE_ID,
        "status": "IN_PROGRESS", "started_at_utc": _utc_now(),
        "supervisor": {"status": "RUNNING", "timeout_seconds": timeout_seconds},
        "phases": {},
    }
    checkpoint.update({"last_run": report, "updated_at_utc": _utc_now()})
    maintenance._atomic_write(checkpoint_path, checkpoint)
    process = subprocess.Popen(list(command), cwd=ROOT)
    try:
        return_code = process.wait(timeout=max(0.01, timeout_seconds))
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        checkpoint = maintenance._read_checkpoint(checkpoint_path)
        previous = checkpoint.get("last_run")
        if isinstance(previous, dict):
            report.update(previous)
        report.update({
            "status": "TIMED_OUT", "finished_at_utc": _utc_now(),
            "reason_code": "SETTLEMENT_MAINTENANCE_EXTERNAL_TIMEOUT",
            "supervisor": {"status": "TERMINATED", "timeout_seconds": timeout_seconds},
        })
        checkpoint.update({"last_run": report, "updated_at_utc": _utc_now()})
        maintenance._atomic_write(checkpoint_path, checkpoint)
        if github_run_id and metrics_path:
            run_metrics.update_persisted_run(
                github_run_id, {"settlement_maintenance": report}, path=str(metrics_path),
            )
        return report
    checkpoint = maintenance._read_checkpoint(checkpoint_path)
    child_report = checkpoint.get("last_run")
    report = dict(child_report) if isinstance(child_report, dict) else report
    terminal = {"COMPLETED", "NO_ELIGIBLE_WORK", "PARTIAL", "TIMED_OUT", "FAILED"}
    if str(report.get("status") or "") not in terminal:
        report.update({
            "status": "FAILED",
            "finished_at_utc": _utc_now(),
            "reason_code": (
                "SETTLEMENT_MAINTENANCE_CHILD_NONZERO_EXIT"
                if return_code
                else "SETTLEMENT_MAINTENANCE_CHILD_NO_TERMINAL_STATE"
            ),
        })
    elif return_code and report.get("status") not in {"PARTIAL", "TIMED_OUT", "FAILED"}:
        report.update({
            "status": "FAILED",
            "finished_at_utc": _utc_now(),
            "reason_code": "SETTLEMENT_MAINTENANCE_CHILD_NONZERO_EXIT",
        })
    report["supervisor"] = {"status": "EXITED", "return_code": return_code}
    checkpoint.update({"last_run": report, "updated_at_utc": _utc_now()})
    maintenance._atomic_write(checkpoint_path, checkpoint)
    if github_run_id and metrics_path:
        run_metrics.update_persisted_run(
            github_run_id, {"settlement_maintenance": report}, path=str(metrics_path),
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout-seconds", type=float, default=float(
        os.environ.get("SETTLEMENT_HARD_TIMEOUT_SECONDS", "270")
    ))
    parser.add_argument("--checkpoint", type=Path, default=maintenance.CHECKPOINT_PATH)
    args = parser.parse_args()
    report = supervise(
        command=[sys.executable, "scripts/update_calibration_outcomes.py"],
        checkpoint_path=args.checkpoint,
        timeout_seconds=args.timeout_seconds,
        metrics_path=Path(os.environ.get(
            "FENZOBOT_RUN_METRICS_PATH", "data/run_metrics_log.json",
        )),
        github_run_id=os.environ.get("GITHUB_RUN_ID", ""),
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report.get("status") in {"COMPLETED", "NO_ELIGIBLE_WORK", "PARTIAL"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
