"""Create the CHANGE-067 activation manifest at a coordinated cut-over.

This script is intentionally never called by CI.  It snapshots the base as it
exists; it does not settle, rebuild or normalize any historical record.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import forward_only  # noqa: E402


def _read_json(path: Path, list_key: str) -> list[dict[str, Any]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    values = document.get(list_key) if isinstance(document, Mapping) else None
    return [dict(item) for item in values or [] if isinstance(item, Mapping)]


def _ledger_rows(root: Path) -> Iterable[dict[str, Any]]:
    for path in sorted((root / "observations").glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    yield json.loads(line)
    for path in sorted((root / "archive").glob("**/*.jsonl.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    yield json.loads(line)


def _section(collection: str, rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    records = []
    tokens: set[str] = set()
    for row in rows:
        identity = forward_only.record_key(collection, row)
        records.append({"identity": identity, "sha256": forward_only.canonical_sha256(row)})
        tokens.update(forward_only.identity_tokens(collection, row))
    return {
        "count": len(records),
        "records": sorted(records, key=lambda item: item["identity"]),
        "identity_tokens": sorted(tokens),
    }


def _exclusion_section(path: Path) -> dict[str, Any]:
    rows = _read_json(path, "exclusions")
    records = []
    for index, row in enumerate(rows):
        identity = str(
            row.get("paper_key") or row.get("snapshot_key")
            or row.get("report_id") or f"index:{index}"
        )
        records.append({"identity": identity, "sha256": forward_only.canonical_sha256(row)})
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "count": len(records),
        "records": records,
    }


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_manifest(*, effective_from_utc: str, code_commit: str, data_base_commit: str) -> dict[str, Any]:
    parsed = datetime.fromisoformat(effective_from_utc.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("effective_from_utc must include a timezone")
    t0 = parsed.astimezone(timezone.utc).isoformat(timespec="seconds")
    snapshots = _read_json(ROOT / "data/calibration_snapshots.json", "snapshots")
    paper = _read_json(ROOT / "data/paper_trades.json", "entries")
    ledger = list(_ledger_rows(ROOT / "data/market_ledger"))
    reports = []
    for path in sorted((ROOT / "docs/relatorios").glob("*.html")):
        reports.append({"path": path.relative_to(ROOT).as_posix(), "sha256": _file_hash(path)})
    audit_files = []
    for relative in (
        "data/validation/market-integrity-exclusions-v1.json",
        "data/paper_integrity_exclusions.json",
        "data/manual_paper_22bet.json",
        "data/dashboard/dashboard-data.json",
        "data/market_ledger/derived/market-memory-v1.json",
    ):
        path = ROOT / relative
        if path.exists():
            audit_files.append({"path": relative, "sha256_at_t0": _file_hash(path)})
    return {
        "schema_version": forward_only.SCHEMA_VERSION,
        "change_id": forward_only.CHANGE_ID,
        "status": "ACTIVE",
        "effective_from_utc": t0,
        "code_commit": code_commit,
        "data_base_commit": data_base_commit,
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "protected": {
            "snapshots": _section("snapshots", snapshots),
            "paper": _section("paper", paper),
            "market_ledger": _section("market_ledger", ledger),
            "published_reports": {"count": len(reports), "files": reports},
            "exclusions": [
                _exclusion_section(ROOT / "data/paper_integrity_exclusions.json"),
                _exclusion_section(
                    ROOT / "data/validation/market-integrity-exclusions-v1.json"
                ),
            ],
            "historic_aggregate_references": audit_files,
        },
    }


def _git_sha() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
    ).strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--effective-from-utc", required=True)
    parser.add_argument("--code-commit", default="")
    parser.add_argument("--data-base-commit", default="")
    parser.add_argument("--output", type=Path, default=forward_only.DEFAULT_MANIFEST_PATH)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("activation manifest already exists; T0 is immutable")
    current = _git_sha()
    document = build_manifest(
        effective_from_utc=args.effective_from_utc,
        code_commit=args.code_commit or current,
        data_base_commit=args.data_base_commit or current,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Activation manifest written once: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
