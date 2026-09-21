"""Canonical GREEN flat-stake projection from ex-ante technical PAPER legs.

This module never creates a GREEN decision or reconstructs a price.  It only
projects append-only PAPER records that already preserve the selected leg and
its factual pre-match decimal odd, after applying the canonical exclusion
manifests.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Mapping

from . import paper_trading


CHANGE_ID = "CHANGE-2026-09-21-046"
SCHEMA_VERSION = 1
METRIC_ID = "GREEN_MONETIZATION_V1"
STAKE_EUR = Decimal("10.00")
DEFAULT_OUTPUT_PATH = Path("data/validation/green-monetization-v1.json")
DEFAULT_LEGACY_EXCLUSIONS_PATH = Path("data/paper_integrity_exclusions.json")
DEFAULT_MARKET_EXCLUSIONS_PATH = Path("data/validation/market-integrity-exclusions-v1.json")
VALID_RESULTS = {"WIN", "LOSS", "VOID", "PUSH"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _read_json(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, Mapping) else {}


def _manifest_exclusions(
    legacy_path: Path,
    market_path: Path,
) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in _read_json(legacy_path).get("exclusions", []):
        if not isinstance(item, Mapping) or not item.get("paper_key"):
            continue
        result[str(item["paper_key"])] = str(
            item.get("disposition") or item.get("reason_code") or "LEGACY_INTEGRITY_EXCLUSION"
        )
    for item in _read_json(market_path).get("exclusions", []):
        if not isinstance(item, Mapping) or not item.get("paper_key"):
            continue
        result[str(item["paper_key"])] = str(
            item.get("reason_code") or item.get("disposition") or "MARKET_INTEGRITY_EXCLUSION"
        )
    return result


def _decimal_odd(value: Any) -> Decimal | None:
    try:
        odd = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not odd.is_finite() or odd <= 1:
        return None
    return odd


def _line_token(value: Any) -> str | None:
    if value is None:
        return None
    try:
        number = Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, AttributeError, ValueError):
        text = str(value).strip().casefold()
        return text or None
    if not number.is_finite():
        return None
    return format(number.normalize(), "f")


def _market_bucket(value: Any) -> str:
    text = str(value or "").strip().casefold()
    if text == "moneyline":
        return "Moneyline"
    if "handicap" in text:
        return "Handicap"
    return "Other"


def _leg_identity(entry: Mapping[str, Any]) -> tuple[str | None, str | None]:
    pregame = _mapping(entry.get("pregame"))
    snapshot_key = str(pregame.get("snapshot_key") or "").strip()
    if not snapshot_key:
        return None, "MISSING_SNAPSHOT_KEY"
    market_type = str(pregame.get("market_type") or "").strip().casefold()
    if not market_type:
        return None, "MISSING_MARKET_TYPE"
    selection = str(pregame.get("selected_side") or pregame.get("selected_player") or "").strip().casefold()
    if not selection:
        return None, "MISSING_SELECTION"
    line = _line_token(pregame.get("line"))
    if market_type != "moneyline" and line is None:
        return None, "MISSING_MARKET_LINE"
    line_token = line if line is not None else "na"
    return f"{snapshot_key}|{market_type}|{line_token}|{selection}", None


def _empty_bucket() -> dict[str, Any]:
    return {
        "eligible_entries": 0,
        "resolved_entries": 0,
        "pending_entries": 0,
        "wins": 0,
        "losses": 0,
        "void_entries": 0,
        "resolved_stake_eur": Decimal("0"),
        "pending_exposure_eur": Decimal("0"),
        "net_profit_eur": Decimal("0"),
    }


def _money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _public_bucket(bucket: Mapping[str, Any]) -> dict[str, Any]:
    stake = Decimal(bucket["resolved_stake_eur"])
    profit = Decimal(bucket["net_profit_eur"])
    roi = (profit / stake * 100) if stake else None
    return {
        "eligible_entries": int(bucket["eligible_entries"]),
        "resolved_entries": int(bucket["resolved_entries"]),
        "pending_entries": int(bucket["pending_entries"]),
        "wins": int(bucket["wins"]),
        "losses": int(bucket["losses"]),
        "void_entries": int(bucket["void_entries"]),
        "resolved_stake_eur": _money(stake),
        "pending_exposure_eur": _money(Decimal(bucket["pending_exposure_eur"])),
        "net_profit_eur": _money(profit),
        "roi_pct": _money(roi) if roi is not None else None,
    }


def build_report(
    *,
    paper_path: Path = paper_trading.DEFAULT_PATH,
    legacy_exclusions_path: Path = DEFAULT_LEGACY_EXCLUSIONS_PATH,
    market_exclusions_path: Path = DEFAULT_MARKET_EXCLUSIONS_PATH,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Build the aggregate without mutating PAPER, settlement or decisions."""
    paper_path = Path(paper_path)
    source_exists = paper_path.is_file()
    entries = paper_trading.read_entries(paper_path)
    manifest_exclusions = _manifest_exclusions(
        Path(legacy_exclusions_path), Path(market_exclusions_path)
    )
    exclusion_reasons: Counter[str] = Counter()
    seen: set[str] = set()
    total = _empty_bucket()
    buckets = {name: _empty_bucket() for name in ("Moneyline", "Handicap", "Other")}
    provenance_rows: list[dict[str, Any]] = []

    for entry in entries:
        key = str(entry.get("key") or "")
        if key in manifest_exclusions:
            exclusion_reasons[manifest_exclusions[key]] += 1
            provenance_rows.append({"key": key, "status": "EXCLUDED", "reason": manifest_exclusions[key]})
            continue
        if str(entry.get("mode") or "PAPER").upper() != "PAPER":
            exclusion_reasons["NON_PAPER_MODE"] += 1
            continue
        pregame = _mapping(entry.get("pregame"))
        if not pregame.get("analyzed_at_utc"):
            exclusion_reasons["MISSING_EX_ANTE_TIMESTAMP"] += 1
            continue
        identity, identity_error = _leg_identity(entry)
        if identity_error:
            exclusion_reasons[identity_error] += 1
            continue
        odd = _decimal_odd(pregame.get("odd"))
        if odd is None:
            exclusion_reasons["INVALID_OR_MISSING_FACTUAL_ODD"] += 1
            continue

        settlement = entry.get("settlement")
        result: str | None = None
        if isinstance(settlement, Mapping):
            result = str(settlement.get("result") or "").strip().upper()
            if result not in VALID_RESULTS:
                exclusion_reasons["UNVERIFIED_OUTCOME"] += 1
                continue
        if identity in seen:
            exclusion_reasons["DUPLICATE_GREEN_LEG"] += 1
            continue
        seen.add(str(identity))

        bucket = buckets[_market_bucket(pregame.get("market_type"))]
        for target in (total, bucket):
            target["eligible_entries"] += 1
            if result is None:
                target["pending_entries"] += 1
                target["pending_exposure_eur"] += STAKE_EUR
                continue
            target["resolved_entries"] += 1
            target["resolved_stake_eur"] += STAKE_EUR
            if result == "WIN":
                target["wins"] += 1
                target["net_profit_eur"] += STAKE_EUR * (odd - 1)
            elif result == "LOSS":
                target["losses"] += 1
                target["net_profit_eur"] -= STAKE_EUR
            else:
                target["void_entries"] += 1
        provenance_rows.append({
            "identity": identity,
            "odd": str(odd),
            "result": result or "PENDING",
        })

    public_total = _public_bucket(total)
    excluded = sum(exclusion_reasons.values())
    if not source_exists:
        status = "UNAVAILABLE"
    elif not public_total["eligible_entries"]:
        status = "UNAVAILABLE"
    elif excluded:
        status = "DEGRADED"
    else:
        status = "AVAILABLE"
    fingerprint = hashlib.sha256(
        json.dumps(provenance_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": SCHEMA_VERSION,
        "change_id": CHANGE_ID,
        "metric_id": METRIC_ID,
        "status": status,
        "generated_at_utc": generated_at_utc or _utc_now(),
        "claims": "HISTORICAL_EXPERIMENTAL_SIMULATION_NOT_REAL_NOT_PROOF_OF_FUTURE_EDGE",
        "stake_per_leg_eur": float(STAKE_EUR),
        "source": {
            "universe": "PAPER_TECHNICAL_EDGE_POSITIVE_BASELINE",
            "paper_path": paper_trading.DEFAULT_PATH.as_posix(),
            "physical_entries": len(entries) if source_exists else None,
            "exclusion_manifests": [
                DEFAULT_LEGACY_EXCLUSIONS_PATH.as_posix(),
                DEFAULT_MARKET_EXCLUSIONS_PATH.as_posix(),
            ],
            "fingerprint_sha256": fingerprint,
        },
        "deduplication": {
            "contract": "snapshot_key + market_type + line/selection",
            "unique_leg_identities": len(seen),
        },
        **public_total,
        "excluded_entries": excluded,
        "exclusion_reasons": dict(sorted(exclusion_reasons.items())),
        "by_market": {
            name: _public_bucket(bucket)
            for name, bucket in buckets.items()
            if bucket["eligible_entries"]
        },
        "universes": {
            "paper_technical_source": True,
            "guerra_selection_v1": "SUPERSEDED_NOT_INCLUDED",
            "real": "NOT_INCLUDED",
        },
    }


def write_report(report: Mapping[str, Any], path: Path = DEFAULT_OUTPUT_PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temp.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def build_and_write(
    *,
    paper_path: Path = paper_trading.DEFAULT_PATH,
    legacy_exclusions_path: Path = DEFAULT_LEGACY_EXCLUSIONS_PATH,
    market_exclusions_path: Path = DEFAULT_MARKET_EXCLUSIONS_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    report = build_report(
        paper_path=paper_path,
        legacy_exclusions_path=legacy_exclusions_path,
        market_exclusions_path=market_exclusions_path,
        generated_at_utc=generated_at_utc,
    )
    write_report(report, output_path)
    return report
