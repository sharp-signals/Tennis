"""Settle and evaluate FENZOBOT_CONTEXTUAL_2026_11 observations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.settle_contextual_shadow_v2 import settle  # noqa: E402
from src.contextual_shadow_settlement_v2 import (  # noqa: E402
    load_validation_contract,
)
from src.fenzobot_contextual_runtime import GLOBAL_RELEASE_ID  # noqa: E402
from src.fenzobot_contextual_store import DEFAULT_PATH  # noqa: E402


OUTCOMES_PATH = Path(
    "data/contextual_shadow_outcomes-fenzobot-contextual-2026-11.jsonl"
)
MARKET_PATH = Path(
    "data/contextual_shadow_market-fenzobot-contextual-2026-11.jsonl"
)
EVALUATION_PATH = Path(
    "data/validation/fenzobot-contextual-2026-11-evaluation-latest.json"
)
VALIDATION_PATH = Path(
    "data/models/fenzobot-contextual-2026-11-validation.json"
)


def settle_release(
    *, max_observations: int = 50, evaluate_only: bool = False,
) -> dict:
    validation = load_validation_contract(
        VALIDATION_PATH,
        expected_model_version=GLOBAL_RELEASE_ID,
        expected_contract_version="fenzobot-contextual-2026-11-validation.1",
    )
    return settle(
        observations_path=DEFAULT_PATH,
        outcomes_path=OUTCOMES_PATH,
        market_path=MARKET_PATH,
        evaluation_path=EVALUATION_PATH,
        max_observations=max_observations,
        evaluate_only=evaluate_only,
        model_version=GLOBAL_RELEASE_ID,
        validation_contract=validation,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-observations", type=int, default=50)
    parser.add_argument("--evaluate-only", action="store_true")
    args = parser.parse_args()
    print(json.dumps(settle_release(
        max_observations=max(0, args.max_observations),
        evaluate_only=args.evaluate_only,
    ), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
