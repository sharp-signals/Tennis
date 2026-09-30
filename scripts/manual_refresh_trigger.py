"""Read-only trigger guard for the public manual aggregate; no providers."""
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

TARGET = 'data/manual_paper_22bet.json'


def needs_refresh(event: str, source_sha: str, root: Path = Path('.')) -> bool:
    if event == 'workflow_dispatch':
        return True
    if event != 'workflow_run' or not re.fullmatch(r'[0-9a-f]{40}', source_sha):
        return False
    try:
        # Only inspect commits already present in the trusted main checkout.
        subprocess.run(['git', 'merge-base', '--is-ancestor', source_sha, 'HEAD'],
                       cwd=root, check=True, capture_output=True, timeout=10)
        files = subprocess.check_output(
            ['git', 'diff-tree', '--root', '-m', '--first-parent', '--no-commit-id',
             '--name-only', '-r', source_sha, '--', TARGET],
            cwd=root, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return TARGET in files.splitlines()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--event', required=True)
    parser.add_argument('--source-sha', default='')
    args = parser.parse_args()
    print('needed=' + str(needs_refresh(args.event, args.source_sha)).lower())
