"""Create/restore a scoped byte-complete NOT_PUBLISHED recovery artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.generated_output_contract import is_allowed, normalize  # noqa: E402
from scripts.stage_generated_outputs import changed_paths  # noqa: E402


def _head_paths(root: Path, remote_ref: str) -> list[str]:
    try:
        value = subprocess.check_output(
            ["git", "diff", "--name-only", f"{remote_ref}...HEAD"], cwd=root, text=True,
        )
    except subprocess.CalledProcessError:
        return []
    return [normalize(path) for path in value.splitlines() if path.strip()]


def create_recovery(
    *, root: Path, target: Path, profile: str, reason: str,
    remote_ref: str = "origin/main", title: str = "generated outputs",
) -> dict:
    root, target = root.resolve(), target.resolve()
    target.mkdir(parents=True, exist_ok=True)
    candidates = sorted(set(changed_paths(root) + _head_paths(root, remote_ref)))
    rejected = [path for path in candidates if not is_allowed(path, profile)]
    candidates = [path for path in candidates if path not in rejected]
    files = []
    for relative in candidates:
        source = root / relative
        if not source.is_file():
            files.append({"path": relative, "status": "DELETED"})
            continue
        destination = target / "files" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        value = source.read_bytes()
        files.append({
            "path": relative, "status": "PRESENT", "size": len(value),
            "sha256": hashlib.sha256(value).hexdigest(),
        })
    bundle = target / "local-commits.bundle"
    result = subprocess.run(
        ["git", "bundle", "create", str(bundle), f"{remote_ref}..HEAD"],
        cwd=root, capture_output=True, text=True,
    )
    if result.returncode != 0:
        bundle.unlink(missing_ok=True)
    document = {
        "schema_version": 1, "status": "NOT_PUBLISHED", "reason_code": reason,
        "title": title, "profile": profile,
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "remote_ref": remote_ref, "files": files,
        "excluded_outside_allowlist": rejected,
        "restore": "python scripts/recover_generated_outputs.py --restore <artifact> --root <fresh-workspace>",
    }
    (target / "recovery-manifest.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return document


def restore(*, artifact: Path, root: Path) -> list[str]:
    document = json.loads((artifact / "recovery-manifest.json").read_text(encoding="utf-8"))
    restored = []
    for item in document.get("files") or []:
        if item.get("status") != "PRESENT":
            continue
        relative = normalize(str(item["path"]))
        if not is_allowed(relative, str(document["profile"])):
            raise RuntimeError(f"RECOVERY_OUTSIDE_ALLOWLIST:{relative}")
        source, destination = artifact / "files" / relative, root / relative
        value = source.read_bytes()
        if hashlib.sha256(value).hexdigest() != item.get("sha256"):
            raise RuntimeError(f"RECOVERY_HASH_MISMATCH:{relative}")
        if destination.exists() and destination.read_bytes() != value:
            raise RuntimeError(f"RECOVERY_REFUSES_OVERWRITE:{relative}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            destination.write_bytes(value)
        restored.append(relative)
    return restored


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--profile")
    parser.add_argument("--target", type=Path)
    parser.add_argument("--reason", default="UNSPECIFIED")
    parser.add_argument("--title", default="generated outputs")
    parser.add_argument("--remote-ref", default="origin/main")
    parser.add_argument("--restore", type=Path)
    args = parser.parse_args()
    if args.restore:
        print(json.dumps({"restored": restore(artifact=args.restore, root=args.root)}))
        return 0
    if not args.profile or not args.target:
        parser.error("--profile and --target are required when creating an artifact")
    create_recovery(
        root=args.root, target=args.target, profile=args.profile, reason=args.reason,
        remote_ref=args.remote_ref, title=args.title,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
