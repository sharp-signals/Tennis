"""Read-only trigger guard for the public manual aggregate; no providers."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

TARGETS = {
    # O inbox legado inicia a promoção. A cópia autorizada também inicia uma
    # reconstrução quando é semeada ou atualizada diretamente.
    'data/manual_paper_22bet.json',
    'data/manual_paper_22bet_authoritative.json',
}


def _read_document(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _valid_candidate(document: object) -> bool:
    """Mirror the promotion contract without importing dashboard dependencies."""
    if not isinstance(document, dict) or document.get('schema_version') != 2:
        return False
    summary = document.get('summary')
    source = document.get('source')
    required_summary = {
        'total_entries', 'settled', 'pending', 'wins', 'losses', 'pushes',
        'units', 'settled_stake_units', 'pending_stake_units',
    }
    required_columns = {'market', 'side', 'odd', 'stake', 'result', 'profit'}
    columns = source.get('operational_columns') if isinstance(source, dict) else None
    return (
        isinstance(summary, dict)
        and required_summary.issubset(summary)
        and isinstance(source, dict)
        and bool(source.get('synced_at_utc'))
        and isinstance(columns, dict)
        and required_columns.issubset(columns)
    )


def _source_timestamp(document: object) -> str:
    if not isinstance(document, dict) or not isinstance(document.get('source'), dict):
        return ''
    return str(document['source'].get('synced_at_utc') or '')


def scheduled_refresh_needed(root: Path) -> bool:
    """Catch a valid Sheet publication if GitHub's workflow_run hook was missed."""
    candidate = _read_document(root / 'data/manual_paper_22bet.json')
    current = _read_document(root / 'data/manual_paper_22bet_authoritative.json')
    return _valid_candidate(candidate) and (
        not _valid_candidate(current) or _source_timestamp(candidate) > _source_timestamp(current)
    )


def needs_refresh(event: str, source_sha: str, root: Path = Path('.')) -> bool:
    if event == 'workflow_dispatch':
        return True
    if event == 'schedule':
        return scheduled_refresh_needed(root)
    if event != 'workflow_run' or not re.fullmatch(r'[0-9a-f]{40}', source_sha):
        return False
    try:
        # Only inspect commits already present in the trusted main checkout.
        subprocess.run(['git', 'merge-base', '--is-ancestor', source_sha, 'HEAD'],
                       cwd=root, check=True, capture_output=True, timeout=10)
        files = subprocess.check_output(
            ['git', 'diff-tree', '--root', '-m', '--first-parent', '--no-commit-id',
             '--name-only', '-r', source_sha, '--', *sorted(TARGETS)],
            cwd=root, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return bool(TARGETS.intersection(files.splitlines()))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--event', required=True)
    parser.add_argument('--source-sha', default='')
    args = parser.parse_args()
    print('needed=' + str(needs_refresh(args.event, args.source_sha)).lower())
