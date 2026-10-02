"""Create the CHANGE-067 activation manifest at a coordinated cut-over.

This script is intentionally never called by CI.  It snapshots the base as it
exists; it does not settle, rebuild or normalize any historical record.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import forward_only  # noqa: E402


class ActivationSourceError(RuntimeError):
    pass


def _read_json(path: Path, list_key: str, *, required: bool = True) -> list[dict[str, Any]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        if required:
            raise ActivationSourceError(
                f"required_activation_source_unreadable:{path}:{type(exc).__name__}"
            ) from exc
        return []
    if not isinstance(document, Mapping):
        raise ActivationSourceError(f"required_activation_source_invalid:{path}")
    values = document.get(list_key) if isinstance(document, Mapping) else None
    if not isinstance(values, list) or any(not isinstance(item, Mapping) for item in values):
        raise ActivationSourceError(f"required_activation_list_invalid:{path}:{list_key}")
    return [dict(item) for item in values]


def _ledger_rows(root: Path) -> Iterable[dict[str, Any]]:
    if not root.is_dir():
        raise ActivationSourceError(f"required_activation_ledger_missing:{root}")
    for path in sorted((root / "observations").glob("*.jsonl")):
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        value = json.loads(line)
                        if not isinstance(value, Mapping):
                            raise ActivationSourceError(f"activation_ledger_row_invalid:{path}")
                        yield dict(value)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ActivationSourceError(
                f"required_activation_ledger_unreadable:{path}:{type(exc).__name__}"
            ) from exc
    for path in sorted((root / "archive").glob("**/*.jsonl.gz")):
        try:
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        value = json.loads(line)
                        if not isinstance(value, Mapping):
                            raise ActivationSourceError(f"activation_ledger_row_invalid:{path}")
                        yield dict(value)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ActivationSourceError(
                f"required_activation_ledger_unreadable:{path}:{type(exc).__name__}"
            ) from exc


def _section(collection: str, rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    records = []
    tokens: set[str] = set()
    aliases: dict[str, set[str]] = {}
    for row in rows:
        identity = forward_only.record_key(collection, row)
        if not identity:
            raise ActivationSourceError(f"activation_identity_missing:{collection}")
        records.append({"identity": identity, "sha256": forward_only.canonical_sha256(row)})
        tokens.update(forward_only.identity_tokens(collection, row))
        canonical = forward_only.canonical_identity(collection, row)
        for alias in forward_only.weak_aliases(collection, row):
            aliases.setdefault(alias, set()).add(canonical)
    return {
        "count": len(records),
        "records": sorted(records, key=lambda item: item["identity"]),
        "identity_tokens": sorted(tokens),
        "weak_alias_contexts": {
            alias: sorted(values) for alias, values in sorted(aliases.items())
        },
    }


def _exclusion_section(path: Path, *, root: Path = ROOT) -> dict[str, Any]:
    rows = _read_json(path, "exclusions")
    records = []
    for index, row in enumerate(rows):
        identity = str(
            row.get("paper_key") or row.get("snapshot_key")
            or row.get("report_id") or f"index:{index}"
        )
        records.append({"identity": identity, "sha256": forward_only.canonical_sha256(row)})
    return {
        "path": path.relative_to(root).as_posix(),
        "count": len(records),
        "records": records,
    }


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_blob(root: Path, commit: str, relative: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", f"{commit}:{relative}"], cwd=root, text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError as exc:
        raise ActivationSourceError(f"activation_git_reference_missing:{commit}:{relative}") from exc


def _historic_reference(root: Path, commit: str, relative: str, kind: str) -> dict[str, Any]:
    path = root / relative
    if not path.is_file():
        raise ActivationSourceError(f"required_activation_projection_missing:{relative}")
    return {
        "path": relative,
        "kind": kind,
        "sha256_at_t0": _file_hash(path),
        "git_blob_oid": _git_blob(root, commit, relative),
    }


def _freeze_mutable_indexes(root: Path, t0: datetime) -> list[dict[str, Any]]:
    frozen_dir = root / "docs/relatorios/frozen-indexes"
    frozen_dir.mkdir(parents=True, exist_ok=True)
    result = []
    candidates = [root / "docs/index.html"]
    candidates.append(root / f"docs/relatorios/index-{t0.date().isoformat()}.html")
    for source in candidates:
        if not source.is_file():
            continue
        digest = _file_hash(source)
        target = frozen_dir / f"{source.stem}-t0-{digest[:12]}{source.suffix}"
        if target.exists() and _file_hash(target) != digest:
            raise ActivationSourceError(f"frozen_index_collision:{target}")
        if not target.exists():
            shutil.copyfile(source, target)
        result.append({
            "source_path": source.relative_to(root).as_posix(),
            "path": target.relative_to(root).as_posix(),
            "sha256": digest,
        })
    return result


def build_manifest(
    *, effective_from_utc: str, code_commit: str, data_base_commit: str,
    root: Path = ROOT,
) -> dict[str, Any]:
    parsed = datetime.fromisoformat(effective_from_utc.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("effective_from_utc must include a timezone")
    t0 = parsed.astimezone(timezone.utc).isoformat(timespec="seconds")
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).strip():
        raise ActivationSourceError("activation_requires_clean_worktree")
    snapshots = _read_json(root / "data/calibration_snapshots.json", "snapshots")
    paper = _read_json(root / "data/paper_trades.json", "entries")
    ledger = list(_ledger_rows(root / "data/market_ledger"))
    frozen_indexes = _freeze_mutable_indexes(root, parsed.astimezone(timezone.utc))
    reports = []
    reports_dir = root / "docs/relatorios"
    if not reports_dir.is_dir():
        raise ActivationSourceError("required_activation_reports_missing")
    mutable_today = f"index-{parsed.astimezone(timezone.utc).date().isoformat()}.html"
    for path in sorted(reports_dir.glob("*.html")):
        if path.name == mutable_today:
            continue
        reports.append({"path": path.relative_to(root).as_posix(), "sha256": _file_hash(path)})
    reports.extend({"path": item["path"], "sha256": item["sha256"]} for item in frozen_indexes)
    projection_specs = (
        ("data/market_ledger/derived/market-memory-v1.json", "JSON"),
        ("data/validation/green-strong-v1.json", "JSON"),
        ("data/validation/green-monetization-v1.json", "JSON"),
        ("data/dashboard/fenzobot-dashboard-v1.json", "JSON"),
        ("data/dashboard/system_history_analytics.json", "JSON"),
        ("docs/dashboard/Fenzobot_Historico_do_Sistema.xlsx", "XLSX"),
    )
    audit_files = [
        _historic_reference(root, data_base_commit, relative, kind)
        for relative, kind in projection_specs
    ]
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
                _exclusion_section(root / "data/paper_integrity_exclusions.json", root=root),
                _exclusion_section(
                    root / "data/validation/market-integrity-exclusions-v1.json",
                    root=root,
                ),
            ],
            "historic_aggregate_references": audit_files,
            "mutable_index_versions": frozen_indexes,
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
    lock_path = forward_only.activation_lock_path(args.output)
    if args.output.exists() or lock_path.exists():
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
    lock = {
        "schema_version": 1,
        "change_id": forward_only.CHANGE_ID,
        "effective_from_utc": document["effective_from_utc"],
        "manifest_sha256": forward_only.canonical_sha256(document),
        "code_commit": document["code_commit"],
        "data_base_commit": document["data_base_commit"],
    }
    lock_path.write_text(
        json.dumps(lock, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Activation manifest written once: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
