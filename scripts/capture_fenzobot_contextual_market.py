"""Freeze the post-prediction market for FENZOBOT_CONTEXTUAL_2026_11."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.capture_contextual_shadow_market_v2 import capture  # noqa: E402
from src.contextual_shadow_market_v2 import build_market_observation  # noqa: E402
from src.fenzobot_contextual_runtime import GLOBAL_RELEASE_ID  # noqa: E402
from src.fenzobot_contextual_store import DEFAULT_PATH  # noqa: E402


MARKET_PATH = Path(
    "data/contextual_shadow_market-fenzobot-contextual-2026-11.jsonl"
)
SUMMARY_PATH = Path(
    "data/validation/fenzobot-contextual-2026-11-market-latest.json"
)


def capture_release(*, max_observations: int = 50) -> dict:
    return capture(
        max_observations=max_observations,
        observations_path=DEFAULT_PATH,
        market_path=MARKET_PATH,
        summary_path=SUMMARY_PATH,
        market_builder=build_market_observation,
        model_version=GLOBAL_RELEASE_ID,
        usage_status="fenzobot_contextual_2026_11_market",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-observations", type=int, default=50)
    args = parser.parse_args()
    print(json.dumps(
        capture_release(max_observations=max(0, args.max_observations)),
        ensure_ascii=False, sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
