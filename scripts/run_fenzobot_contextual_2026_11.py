"""Collect isolated prospective observations for FENZOBOT_CONTEXTUAL_2026_11."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_contextual_shadow_v2 import _run_shadow_only
from src.fenzobot_contextual_activation import ENV_NAME, activation_state
from src.fenzobot_contextual_runtime import (
    DEFAULT_MODEL_PATH,
    GLOBAL_RELEASE_ID,
    load_contract,
    predict_fenzobot_contextual,
)
from src.fenzobot_contextual_store import (
    DEFAULT_PATH,
    PAYLOAD_KEY,
    append_observations,
    build_observation,
    existing_observation_ids,
)
from src.contextual_chronological_rating import build_rating_features
from src.contextual_rating_ab_v1 import (
    DEFAULT_LEDGER_PATH as RATING_AB_LEDGER_PATH,
    DEFAULT_MODEL_PATH as RATING_AB_MODEL_PATH,
    append_observations as append_rating_ab_observations,
    build_observation as build_rating_ab_observation,
    load_contract as load_rating_ab_contract,
    predict_candidates as predict_rating_ab_candidates,
)


SUMMARY_PATH = Path(
    "data/validation/fenzobot-contextual-2026-11-latest.json"
)
HANDICAP_PATH = Path(
    "data/contextual_shadow_handicap_evidence-fenzobot-contextual-2026-11.jsonl"
)
MONEYLINE_PATH = Path(
    "data/contextual_shadow_moneyline_evidence-fenzobot-contextual-2026-11.jsonl"
)
H2H_PATH = Path(
    "data/contextual_shadow_h2h_evidence-fenzobot-contextual-2026-11.jsonl"
)


def run_release_only(*, max_matches: int = 0, workers: int = 4) -> dict:
    return _run_shadow_only(
        max_matches=max_matches,
        workers=workers,
        activation_loader=activation_state,
        disabled_code="FENZOBOT_CONTEXTUAL_2026_11_DISABLED",
        activation_env=ENV_NAME,
        model_path=DEFAULT_MODEL_PATH,
        ledger_path=DEFAULT_PATH,
        summary_path=SUMMARY_PATH,
        contract_loader=load_contract,
        predictor=predict_fenzobot_contextual,
        observation_builder=build_observation,
        observation_ids_loader=existing_observation_ids,
        observation_appender=append_observations,
        payload_key=PAYLOAD_KEY,
        model_version=GLOBAL_RELEASE_ID,
        handicap_path=HANDICAP_PATH,
        moneyline_path=MONEYLINE_PATH,
        h2h_path=H2H_PATH,
        usage_status="fenzobot_contextual_2026_11_success",
        comparison_model_path=RATING_AB_MODEL_PATH,
        comparison_contract_loader=load_rating_ab_contract,
        comparison_feature_builder=build_rating_features,
        comparison_predictor=predict_rating_ab_candidates,
        comparison_observation_builder=build_rating_ab_observation,
        comparison_appender=append_rating_ab_observations,
        comparison_ledger_path=RATING_AB_LEDGER_PATH,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-matches", type=int, default=0)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    summary = run_release_only(
        max_matches=max(0, args.max_matches), workers=max(1, args.workers),
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
