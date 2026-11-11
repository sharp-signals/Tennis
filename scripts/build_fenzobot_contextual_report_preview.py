"""Build private previews for FENZOBOT_CONTEXTUAL_2026_11."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_contextual_shadow_report_preview_v2 import build_previews  # noqa: E402
from scripts.capture_fenzobot_contextual_market import MARKET_PATH  # noqa: E402
from scripts.settle_fenzobot_contextual_2026_11 import OUTCOMES_PATH  # noqa: E402
from src.contextual_shadow_report_v2 import load_report_contract  # noqa: E402
from src.fenzobot_contextual_runtime import GLOBAL_RELEASE_ID  # noqa: E402
from src.fenzobot_contextual_store import DEFAULT_PATH  # noqa: E402


REPORT_CONTRACT_PATH = Path(
    "data/models/fenzobot-contextual-2026-11-report.json"
)
HANDICAP_EVIDENCE_PATH = Path(
    "data/contextual_shadow_handicap_evidence-fenzobot-contextual-2026-11.jsonl"
)
MONEYLINE_EVIDENCE_PATH = Path(
    "data/contextual_shadow_moneyline_evidence-fenzobot-contextual-2026-11.jsonl"
)


def build_release_previews(
    *, output_dir: Path, max_observations: int = 50,
) -> dict:
    contract = load_report_contract(
        REPORT_CONTRACT_PATH,
        expected_model_version=GLOBAL_RELEASE_ID,
        expected_contract_version="fenzobot-contextual-2026-11-report.6",
    )
    return build_previews(
        output_dir=output_dir,
        observations_path=DEFAULT_PATH,
        market_path=MARKET_PATH,
        outcomes_path=OUTCOMES_PATH,
        handicap_evidence_path=HANDICAP_EVIDENCE_PATH,
        moneyline_evidence_path=MONEYLINE_EVIDENCE_PATH,
        max_observations=max_observations,
        expected_model_version=GLOBAL_RELEASE_ID,
        report_contract=contract,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-observations", type=int, default=50)
    args = parser.parse_args()
    print(json.dumps(build_release_previews(
        output_dir=args.output_dir,
        max_observations=max(0, args.max_observations),
    ), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
