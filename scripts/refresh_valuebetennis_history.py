"""Refresh licensed annual ATP odds/result caches."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.valuebetennis_history import FIRST_YEAR, refresh_year


CACHE_DIR = ROOT / "data" / "history_cache"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-year", type=int, default=FIRST_YEAR)
    parser.add_argument("--to-year", type=int, default=datetime.now(timezone.utc).year)
    args = parser.parse_args()
    for year in range(args.from_year, args.to_year + 1):
        frame = refresh_year(CACHE_DIR, year)
        paired = int(frame[["PSW", "PSL"]].notna().all(axis=1).sum()) if not frame.empty else 0
        print(f"[info] Valuebetennis ATP {year}: {len(frame)} jogos; {paired} com par de odds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
