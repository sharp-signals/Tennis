"""Build private previews for FENZOBOT_CONTEXTUAL_2026_11."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
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
from scripts.run_fenzobot_contextual_2026_11 import SUMMARY_PATH  # noqa: E402
from src.contextual_shadow_settlement_v2 import read_jsonl  # noqa: E402


REPORT_CONTRACT_PATH = Path(
    "data/models/fenzobot-contextual-2026-11-report.json"
)
HANDICAP_EVIDENCE_PATH = Path(
    "data/contextual_shadow_handicap_evidence-fenzobot-contextual-2026-11.jsonl"
)
MONEYLINE_EVIDENCE_PATH = Path(
    "data/contextual_shadow_moneyline_evidence-fenzobot-contextual-2026-11.jsonl"
)
H2H_EVIDENCE_PATH = Path(
    "data/contextual_shadow_h2h_evidence-fenzobot-contextual-2026-11.jsonl"
)

IMMINENT_CARRY_FORWARD_HOURS = 6
MAX_CARRY_FORWARD_ANALYSIS_AGE_HOURS = 36


def _parse_utc(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _active_release_observation_ids(
    built_ids: set[str], *, now: datetime | None = None,
) -> set[str]:
    """Keep the current run plus the newest still-prestart imminent fixtures.

    Some provider feeds remove a fixture shortly before first ball.  That must
    not make a valid report disappear between the morning and evening runs.
    The narrow time and age gates avoid reviving old or distant fixtures.
    """
    instant = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rows = read_jsonl(DEFAULT_PATH)
    built_canonical = {
        str(row.get("canonical_match_instance_id") or row.get("event_key") or "")
        for row in rows
        if str(row.get("observation_id") or "") in built_ids
    }
    cutoff = instant - timedelta(hours=MAX_CARRY_FORWARD_ANALYSIS_AGE_HOURS)
    horizon = instant + timedelta(hours=IMMINENT_CARRY_FORWARD_HOURS)
    newest_by_match: dict[str, tuple[datetime, str]] = {}
    for row in rows:
        observation_id = str(row.get("observation_id") or "")
        canonical = str(
            row.get("canonical_match_instance_id") or row.get("event_key") or ""
        )
        if not observation_id or not canonical or canonical in built_canonical:
            continue
        shadow = row.get("contextual_shadow") or {}
        if shadow.get("status") != "READY_FOR_PROSPECTIVE_SHADOW":
            continue
        commence = _parse_utc(row.get("commence_time_utc"))
        analyzed = _parse_utc(row.get("analyzed_at_utc"))
        if (
            commence is None or analyzed is None
            or not (instant < commence <= horizon)
            or analyzed < cutoff
        ):
            continue
        current = newest_by_match.get(canonical)
        if current is None or analyzed > current[0]:
            newest_by_match[canonical] = (analyzed, observation_id)
    return built_ids | {value[1] for value in newest_by_match.values()}


def build_release_previews(
    *, output_dir: Path, max_observations: int = 50,
    now: datetime | None = None,
) -> dict:
    contract = load_report_contract(
        REPORT_CONTRACT_PATH,
        expected_model_version=GLOBAL_RELEASE_ID,
        expected_contract_version="fenzobot-contextual-2026-11-report.12",
    )
    observation_ids = None
    if SUMMARY_PATH.is_file():
        summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
        built = summary.get("observation_ids_built")
        if isinstance(built, list):
            observation_ids = _active_release_observation_ids(
                {str(value) for value in built if value}, now=now,
            )
    return build_previews(
        output_dir=output_dir,
        observations_path=DEFAULT_PATH,
        market_path=MARKET_PATH,
        outcomes_path=OUTCOMES_PATH,
        handicap_evidence_path=HANDICAP_EVIDENCE_PATH,
        moneyline_evidence_path=MONEYLINE_EVIDENCE_PATH,
        h2h_evidence_path=H2H_EVIDENCE_PATH,
        max_observations=max_observations,
        expected_model_version=GLOBAL_RELEASE_ID,
        report_contract=contract,
        observation_ids=observation_ids,
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
