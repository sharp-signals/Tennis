"""Rebase-and-push generated commits with post-rebase validation and recovery."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.recover_generated_outputs import create_recovery  # noqa: E402


def _run(command: list[str], *, root: Path, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=root, check=check, text=True)


def publish(
    *, root: Path, profile: str, title: str, remote: str = "origin",
    branch: str = "main", recovery_dir: Path, retries: int = 3,
    validation_command: list[str] | None = None,
) -> None:
    validation = validation_command or [sys.executable, "scripts/validate_forward_only.py"]

    def recover(reason: str) -> None:
        create_recovery(
            root=root, target=recovery_dir, profile=profile, reason=reason,
            remote_ref=f"{remote}/{branch}", title=title,
        )

    current = subprocess.check_output(
        ["git", "branch", "--show-current"], cwd=root, text=True,
    ).strip()
    if current != branch:
        recover("PUBLISH_BRANCH_INVALID")
        raise RuntimeError("automatic generated-data publication requires main")
    if subprocess.check_output(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=root, text=True,
    ).strip():
        recover("WORKTREE_NOT_CLEAN_AFTER_EXPLICIT_COMMIT")
        raise RuntimeError("worktree is not clean")
    try:
        _run(validation, root=root)
    except subprocess.CalledProcessError:
        recover("FORWARD_ONLY_VALIDATION_FAILED_BEFORE_FETCH")
        raise
    try:
        _run(["git", "fetch", remote, branch], root=root)
    except subprocess.CalledProcessError:
        recover("FETCH_FAILED")
        raise
    for attempt in range(1, retries + 1):
        if _run(["git", "rebase", f"{remote}/{branch}"], root=root, check=False).returncode:
            _run(["git", "rebase", "--abort"], root=root, check=False)
            recover("REBASE_CONFLICT")
            raise RuntimeError("generated-data rebase conflict")
        try:
            _run(validation, root=root)
        except subprocess.CalledProcessError:
            recover("FORWARD_ONLY_VALIDATION_FAILED_AFTER_REBASE")
            raise
        if _run(
            ["git", "push", remote, f"HEAD:{branch}"], root=root, check=False,
        ).returncode == 0:
            print(f"generated data published: {title} (attempt {attempt})")
            return
        if attempt < retries:
            try:
                _run(["git", "fetch", remote, branch], root=root)
            except subprocess.CalledProcessError:
                recover("FETCH_FAILED_AFTER_PUSH_REJECTION")
                raise
            time.sleep(1)
    recover("PUSH_REJECTED_AFTER_RETRIES")
    raise RuntimeError("generated-data push rejected")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("title", nargs="?", default="chore: atualizar dados gerados")
    parser.add_argument("--profile", default=os.environ.get("FENZOBOT_WRITER_PROFILE", "bot"))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--branch", default="main")
    default_recovery = Path(
        os.environ.get("FENZOBOT_RECOVERY_DIR", os.environ.get("RUNNER_TEMP", "."))
    ) / "fenzobot-data-recovery"
    parser.add_argument("--recovery-dir", type=Path, default=default_recovery)
    args = parser.parse_args()
    publish(
        root=args.root, profile=args.profile, title=args.title, remote=args.remote,
        branch=args.branch, recovery_dir=args.recovery_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
