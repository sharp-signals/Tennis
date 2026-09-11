"""Compare all legacy dashboard values against a Git baseline on identical inputs."""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import tempfile
from pathlib import Path

from src import dashboard


def _legacy_projection(value: dict) -> dict:
    """Remove apenas campos aditivos posteriores ao baseline comparado."""
    value.pop('semantic_fingerprint', None)
    value.pop('audit_v1', None)
    value.pop('guidance_v1', None)
    value.pop('change_id', None)
    strategy = value.get('guerra_selection_v1')
    if isinstance(strategy, dict):
        strategy.pop('flat_stake_simulation', None)
    return value


def check(baseline_ref: str, root: Path = Path('.')) -> dict:
    source = subprocess.check_output(['git', 'show', f'{baseline_ref}:src/dashboard.py'], cwd=root, text=True)
    # Trusted reviewed project code, isolated module; primary inputs are not changed.
    with tempfile.TemporaryDirectory() as tmp:
        module_path = Path(tmp) / 'baseline.py'
        module_path.write_text(source, encoding='utf-8')
        spec = importlib.util.spec_from_file_location('src._dashboard_baseline', module_path)
        baseline = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(baseline)
        at = '2026-09-08T19:00:00+00:00'
        expected = baseline.build_dashboard(root=root, generated_at_utc=at)
        actual = dashboard.build_dashboard(root=root, generated_at_utc=at)
    for value in (expected, actual):
        _legacy_projection(value)
    if expected != actual:
        raise AssertionError('Legacy dashboard metric parity failed; do not release')
    return {'legacy_metrics_equal': True, 'baseline_ref': baseline_ref,
            'reports': actual['global']['total_reports'], 'external_provider_calls': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline-ref', required=True)
    args = parser.parse_args()
    print(json.dumps(check(args.baseline_ref), sort_keys=True))
