"""Read-only CLI for CHANGE-2026-11-02-175 recent-form coverage audit."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.recent_form_audit import (
    DEFAULT_WINDOW_DAYS,
    audit_local_caches,
    audit_operational_histories,
)


def _as_of(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", type=Path, default=Path("data/history_cache"))
    parser.add_argument("--as-of")
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    parser.add_argument("--mode", choices=("local", "operational"), default="local")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.mode == "operational":
        result = audit_operational_histories(
            as_of=_as_of(args.as_of), window_days=args.window_days,
        )
    else:
        result = audit_local_caches(
            args.cache_dir,
            as_of=_as_of(args.as_of),
            window_days=args.window_days,
        )
    encoded = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
