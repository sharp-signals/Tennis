"""Fail closed when a protected CHANGE-067 record was mutated or removed."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.activate_forward_only import _ledger_rows, _read_json  # noqa: E402
from src import forward_only  # noqa: E402


def validate(manifest_path: Path) -> list[str]:
    boundary = forward_only.load_boundary(manifest_path)
    if not boundary.active:
        # Before coordinated activation there is deliberately no protected base.
        return []
    manifest = boundary.manifest or {}
    protected = manifest.get("protected") or {}
    current = {
        "snapshots": _read_json(ROOT / "data/calibration_snapshots.json", "snapshots"),
        "paper": _read_json(ROOT / "data/paper_trades.json", "entries"),
        "market_ledger": list(_ledger_rows(ROOT / "data/market_ledger")),
    }
    errors: list[str] = []
    for collection, rows in current.items():
        actual = {
            forward_only.record_key(collection, row): forward_only.canonical_sha256(row)
            for row in rows
        }
        section = protected.get(collection) or {}
        for expected in section.get("records") or []:
            identity = str(expected.get("identity") or "")
            if identity not in actual:
                errors.append(f"{collection}:{identity}:PROTECTED_RECORD_MISSING")
            elif actual[identity] != expected.get("sha256"):
                errors.append(f"{collection}:{identity}:PROTECTED_RECORD_MUTATED")
    for report in (protected.get("published_reports") or {}).get("files") or []:
        path = ROOT / str(report.get("path") or "")
        if not path.exists():
            errors.append(f"report:{report.get('path')}:PROTECTED_REPORT_MISSING")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != report.get("sha256"):
            errors.append(f"report:{report.get('path')}:PROTECTED_REPORT_MUTATED")
    for section in protected.get("exclusions") or []:
        relative = str(section.get("path") or "")
        rows = _read_json(ROOT / relative, "exclusions")
        actual = {}
        for index, row in enumerate(rows):
            identity = str(
                row.get("paper_key") or row.get("snapshot_key")
                or row.get("report_id") or f"index:{index}"
            )
            actual[identity] = forward_only.canonical_sha256(row)
        for expected in section.get("records") or []:
            identity = str(expected.get("identity") or "")
            if identity not in actual:
                errors.append(f"exclusion:{identity}:PROTECTED_RECORD_MISSING")
            elif actual[identity] != expected.get("sha256"):
                errors.append(f"exclusion:{identity}:PROTECTED_RECORD_MUTATED")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=forward_only.DEFAULT_MANIFEST_PATH)
    args = parser.parse_args()
    errors = validate(args.manifest)
    if errors:
        print(json.dumps({"status": "FAILED", "reason_codes": errors[:100]}, indent=2))
        return 1
    boundary = forward_only.load_boundary(args.manifest)
    print(json.dumps({
        "status": "VALIDATED" if boundary.active else "EXTERNAL_ACTIVATION_PENDING",
        "manifest": str(args.manifest),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
