"""Stage every and only changed path allowed for one generated-data writer."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.generated_output_contract import is_allowed, normalize  # noqa: E402


def changed_paths(root: Path) -> list[str]:
    raw = subprocess.check_output(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"], cwd=root,
    )
    parts = raw.decode("utf-8", "surrogateescape").split("\0")
    result: list[str] = []
    index = 0
    while index < len(parts):
        item = parts[index]
        index += 1
        if not item:
            continue
        status, path = item[:2], item[3:]
        if "R" in status or "C" in status:
            if index < len(parts) and parts[index]:
                path = parts[index]
                index += 1
        result.append(normalize(path))
    return sorted(set(result))


def stage(*, root: Path, profile: str) -> list[str]:
    paths = changed_paths(root)
    rejected = [path for path in paths if not is_allowed(path, profile)]
    if rejected:
        raise RuntimeError("GENERATED_OUTPUT_OUTSIDE_ALLOWLIST:" + ",".join(rejected))
    if paths:
        subprocess.run(["git", "add", "--", *paths], cwd=root, check=True)
    remaining = changed_paths(root)
    unstaged = subprocess.check_output(
        ["git", "diff", "--name-only"], cwd=root, text=True,
    ).splitlines()
    if remaining and unstaged:
        raise RuntimeError("GENERATED_OUTPUT_STAGING_INCOMPLETE:" + ",".join(unstaged))
    return paths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    paths = stage(root=args.root, profile=args.profile)
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8") as handle:
            handle.write(f"changed={'true' if paths else 'false'}\n")
    print(f"staged={len(paths)} profile={args.profile}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
