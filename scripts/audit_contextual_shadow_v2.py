"""Audit the prospective contextual SHADOW v2 ledger without mutating it."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
from typing import Any


def _read_contract(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("invalid model contract")
    return value


def audit_ledger(path: Path, contract_path: Path) -> dict[str, Any]:
    contract = _read_contract(contract_path)
    expected_version = (
        contract.get("model_version") or contract["global_release_id"]
    )
    expected_fingerprint = contract["configuration_fingerprint"]
    accepted_historical = {
        (
            int(item.get("runtime_generation") or 0),
            str(item.get("configuration_fingerprint") or ""),
        )
        for item in contract.get("accepted_historical_releases") or []
        if int(item.get("runtime_generation") or 0) > 0
        and item.get("configuration_fingerprint")
    }
    violations: list[dict[str, Any]] = []
    counts = Counter()
    reasons = Counter()
    seen = set()
    if not path.exists():
        return {
            "status": "WAITING_FOR_DATA",
            "rows": 0,
            "violations": [],
            "counts": {},
            "reason_codes": {},
        }
    for line_number, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1,
    ):
        try:
            row = json.loads(raw)
            shadow = row["contextual_shadow"]
        except (ValueError, KeyError, TypeError) as exc:
            violations.append({
                "line": line_number,
                "code": "INVALID_JSON_OR_SCHEMA",
                "detail": type(exc).__name__,
            })
            continue
        observation_id = str(row.get("observation_id") or "")
        if not observation_id or observation_id in seen:
            violations.append({
                "line": line_number,
                "code": "MISSING_OR_DUPLICATE_OBSERVATION_ID",
            })
        seen.add(observation_id)
        try:
            row_generation = int(
                shadow.get("runtime_generation")
                or (shadow.get("component_versions") or {}).get(
                    "runtime_generation"
                )
                or 0
            )
        except (TypeError, ValueError):
            row_generation = 0
        row_fingerprint = str(
            shadow.get("configuration_fingerprint") or ""
        )
        historical_release = (
            row_generation, row_fingerprint
        ) in accepted_historical
        checks = {
            "MODEL_VERSION_MISMATCH": (
                shadow.get("model_version") == expected_version
                or shadow.get("global_release_id") == expected_version
            ),
            "FINGERPRINT_MISMATCH": (
                row_fingerprint == expected_fingerprint or historical_release
            ),
            "MARKET_ISOLATION_VIOLATION": shadow.get("market_used") is False,
            "EDGE_ISOLATION_VIOLATION": shadow.get("edge_calculated") is False,
            "PRODUCTION_ISOLATION_VIOLATION": (
                shadow.get("production_effect") is False
            ),
            "PAPER_ISOLATION_VIOLATION": (
                shadow.get("paper_eligible") is False
                and row.get("paper_eligible") is False
            ),
            "GREEN_ISOLATION_VIOLATION": (
                shadow.get("green_eligible") is False
                and row.get("green_eligible") is False
            ),
            "CANONICAL_IDENTITY_MISSING": bool(
                row.get("canonical_match_instance_id")
            ),
        }
        for code, passed in checks.items():
            if not passed:
                violations.append({"line": line_number, "code": code})
        try:
            probability_a = float(shadow["probability_model_a"])
            probability_b = float(shadow["probability_model_b"])
            lower, upper = map(
                float, shadow["probability_interval_90_model_a"],
            )
            fair_a = float(shadow["fair_odd_model_a"]["central"])
            if not (
                0.0 < probability_a < 1.0
                and math.isclose(probability_a + probability_b, 1.0, abs_tol=2e-6)
                and lower <= probability_a <= upper
                and math.isclose(fair_a, 1.0 / probability_a, abs_tol=1e-3)
            ):
                raise ValueError("probability or fair-odd invariant")
        except (KeyError, TypeError, ValueError):
            violations.append({
                "line": line_number,
                "code": "PROBABILITY_CONTRACT_VIOLATION",
            })
        universe = str(shadow.get("universe") or "unknown")
        status = str(shadow.get("status") or "unknown")
        quality = str(shadow.get("quality_group") or "unknown")
        counts[f"universe:{universe}"] += 1
        counts[f"status:{status}"] += 1
        counts[f"quality:{quality}"] += 1
        counts[
            f"release:{'historical' if historical_release else 'current'}"
        ] += 1
        for reason in shadow.get("reason_codes") or []:
            reasons[str(reason)] += 1
    return {
        "status": "CONTRACT_VIOLATION" if violations else "HEALTHY",
        "rows": sum(value for key, value in counts.items() if key.startswith("universe:")),
        "violations": violations,
        "counts": dict(sorted(counts.items())),
        "reason_codes": dict(sorted(reasons.items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ledger", type=Path,
        default=Path("data/contextual_shadow_observations-v2.jsonl"),
    )
    parser.add_argument(
        "--contract", type=Path,
        default=Path("data/models/contextual-family-shadow-v2.json"),
    )
    args = parser.parse_args()
    result = audit_ledger(args.ledger, args.contract)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 1 if result["status"] == "CONTRACT_VIOLATION" else 0


if __name__ == "__main__":
    raise SystemExit(main())
