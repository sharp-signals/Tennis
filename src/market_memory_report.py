"""Vista derivada e reconstruivel do Market-Time Ledger.

Este modulo nao escreve no ledger, nao chama APIs e nao altera decisoes.
"""

from __future__ import annotations

import json
import math
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from . import market_ledger


SCHEMA_VERSION = 1
DEFAULT_SNAPSHOTS_PATH = Path("data/calibration_snapshots.json")
DEFAULT_PAPER_PATH = Path("data/paper_trades.json")
DEFAULT_OUTPUT_PATH = Path("data/market_ledger/derived/market-memory-v1.json")


def _read_list(path: Path, key: str) -> list[dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    rows = value.get(key) if isinstance(value, Mapping) else None
    return [dict(row) for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []


def _probabilities(observation: Mapping[str, Any] | None) -> dict[str, float] | None:
    if not observation:
        return None
    values = {}
    for selection in observation.get("selections") or []:
        side = str(selection.get("side") or "").casefold()
        try:
            probability = float(selection.get("devig_probability"))
        except (TypeError, ValueError):
            continue
        if side in {"a", "b"} and 0 < probability < 1:
            values[side] = probability
    return values if set(values) == {"a", "b"} else None


def _pricing_probabilities(snapshot: Mapping[str, Any], *, sharp: bool) -> dict[str, float] | None:
    pricing = snapshot.get("pricing")
    if not isinstance(pricing, Mapping) or not pricing.get("available"):
        return None
    result = {}
    players = pricing.get("players") if isinstance(pricing.get("players"), Mapping) else {}
    for side in ("a", "b"):
        nested_key = "sharp_estimate_pct" if sharp else "market_probability_pct"
        flat_key = f"sharp_estimate_{side}" if sharp else f"market_probability_{side}"
        value = (players.get(side) or {}).get(nested_key) if isinstance(players.get(side), Mapping) else None
        if value is None:
            value = pricing.get(flat_key)
            scale = 1.0
        else:
            scale = 100.0
        try:
            probability = float(value) / scale
        except (TypeError, ValueError):
            continue
        if 0 < probability < 1:
            result[side] = probability
    return result if set(result) == {"a", "b"} else None


def _prediction(probabilities: Mapping[str, float] | None) -> str | None:
    if not probabilities or probabilities.get("a") == probabilities.get("b"):
        return None
    return "a" if probabilities["a"] > probabilities["b"] else "b"


def evaluate_probabilities(rows: list[Mapping[str, Any]], probability_field: str) -> dict[str, Any]:
    observations = []
    for row in rows:
        outcome = row.get("outcome_side")
        probabilities = row.get(probability_field)
        if outcome not in {"a", "b"} or not isinstance(probabilities, Mapping):
            continue
        try:
            probability_a = min(1 - 1e-12, max(1e-12, float(probabilities["a"])))
        except (KeyError, TypeError, ValueError):
            continue
        target = 1.0 if outcome == "a" else 0.0
        observations.append((probability_a, target))
    if not observations:
        return {"sample_size": 0, "accuracy_pct": None, "brier_score": None, "log_loss": None}
    correct = sum((probability >= 0.5) == bool(target) for probability, target in observations)
    brier = sum((probability - target) ** 2 for probability, target in observations) / len(observations)
    log_loss = -sum(
        target * math.log(probability) + (1 - target) * math.log(1 - probability)
        for probability, target in observations
    ) / len(observations)
    return {
        "sample_size": len(observations),
        "accuracy_pct": round(100 * correct / len(observations), 2),
        "brier_score": round(brier, 6),
        "log_loss": round(log_loss, 6),
    }


def build_report(
    *,
    ledger_root: Path = market_ledger.DEFAULT_ROOT,
    snapshots_path: Path = DEFAULT_SNAPSHOTS_PATH,
    paper_path: Path = DEFAULT_PAPER_PATH,
) -> dict[str, Any]:
    observations = market_ledger.read_observations(root=ledger_root)
    by_id = {item["observation_id"]: item for item in observations}
    snapshots = _read_list(snapshots_path, "snapshots")
    paper_entries = _read_list(paper_path, "entries")
    paper_by_snapshot: dict[str, list[dict[str, Any]]] = {}
    for entry in paper_entries:
        pregame = entry.get("pregame") or {}
        paper_by_snapshot.setdefault(str(pregame.get("snapshot_key") or ""), []).append(entry)

    rows = []
    for snapshot in snapshots:
        event = str(snapshot.get("event_key") or snapshot.get("key") or "")
        entry_id = snapshot.get("entry_market_observation_id")
        entry_observation = by_id.get(str(entry_id)) if entry_id else None
        entry_probabilities = _probabilities(entry_observation)
        lookup = {
            "event_key": event,
            "snapshot_key": snapshot.get("key"),
            "entry_market_observation_id": entry_id,
            "commence_time_utc": snapshot.get("commence_time_utc"),
        }
        closing = market_ledger.last_comparable_prestart(lookup, root=ledger_root)
        closing_probabilities = _probabilities(closing)
        outcome_side = (snapshot.get("outcome") or {}).get("winner_side")
        sharp_probabilities = _pricing_probabilities(snapshot, sharp=True)
        pricing_market_probabilities = _pricing_probabilities(snapshot, sharp=False)
        validation = snapshot.get("validation") if isinstance(snapshot.get("validation"), Mapping) else {}
        memberships = validation.get("cohorts") if isinstance(validation.get("cohorts"), Mapping) else {}
        selected_side = None
        for membership in memberships.values():
            if isinstance(membership, Mapping) and membership.get("eligible") is True:
                selected_side = membership.get("selected_side")
                break
        market_position = None
        if selected_side in {"a", "b"} and pricing_market_probabilities:
            other = "b" if selected_side == "a" else "a"
            if pricing_market_probabilities[selected_side] != pricing_market_probabilities[other]:
                market_position = "FAVORITE" if pricing_market_probabilities[selected_side] > pricing_market_probabilities[other] else "UNDERDOG"
        paper = paper_by_snapshot.get(str(snapshot.get("key") or ""), [])
        paper_links = []
        for paper_entry in paper:
            pregame = paper_entry.get("pregame") or {}
            derived_clv = market_ledger.clv_for_pregame(pregame, root=ledger_root)
            paper_links.append({
                "paper_key": paper_entry.get("key"),
                "selected_side": pregame.get("selected_side"),
                "entry_market_observation_id": pregame.get("entry_market_observation_id"),
                "closing_market_observation_id": (derived_clv or {}).get("closing_market_observation_id"),
                "entry_market_probability": (derived_clv or {}).get("entry_market_probability"),
                "last_valid_prestart_market_probability": (derived_clv or {}).get("last_valid_prestart_market_probability"),
                "clv_probability_pp": (derived_clv or {}).get("clv_probability_pp"),
                "clv_price_pct": (derived_clv or {}).get("clv_price_pct"),
            })
        row = {
            "event_key": event,
            "snapshot_key": snapshot.get("key"),
            "report_id": snapshot.get("report_id"),
            "match_id": snapshot.get("match_id"),
            "scheduled_start_utc": snapshot.get("commence_time_utc"),
            "players": {"a": snapshot.get("player_a"), "b": snapshot.get("player_b")},
            "entry_market_observation_id": entry_id,
            "last_valid_prestart_market_observation_id": closing.get("observation_id") if closing else None,
            "entry_market_probabilities": entry_probabilities,
            "last_valid_prestart_market_probabilities": closing_probabilities,
            "market_only_prediction": _prediction(entry_probabilities),
            "market_plus_sharp_probabilities": sharp_probabilities,
            "market_plus_sharp_prediction": _prediction(sharp_probabilities),
            "pricing_model_version": (snapshot.get("pricing") or {}).get("model_version"),
            "pricing_configuration_fingerprint": (snapshot.get("pricing") or {}).get("configuration_fingerprint"),
            "outcome_side": outcome_side,
            "paper": paper_links,
            "availability": {
                "entry_market": "AVAILABLE" if entry_probabilities else "UNAVAILABLE",
                "closing_market": "AVAILABLE" if closing_probabilities else "UNAVAILABLE",
                "market_plus_sharp": "AVAILABLE" if sharp_probabilities else "UNAVAILABLE",
            },
        }
        if memberships:
            row.update({
                "tour": snapshot.get("tour"),
                "surface": snapshot.get("surface"),
                "match_format": snapshot.get("match_format"),
                "pricing_market_probabilities": pricing_market_probabilities,
                "fenzobot_probabilities": sharp_probabilities,
                "selected_side": selected_side,
                "selected_side_market_position": market_position,
                "cohort_memberships": dict(memberships),
                "cohort_code_revision": next((
                    (membership.get("source") or {}).get("code_revision")
                    for membership in memberships.values()
                    if isinstance(membership, Mapping) and membership.get("eligible") is True
                ), None),
            })
        rows.append(row)

    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        version = str(row.get("pricing_model_version") or "UNAVAILABLE")
        fingerprint = str(row.get("pricing_configuration_fingerprint") or "UNAVAILABLE")
        grouped.setdefault(f"{version}:{fingerprint}", []).append(row)

    return {
        "schema_version": SCHEMA_VERSION,
        "change_id": market_ledger.CHANGE_ID,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "SHADOW_ANALYTICS",
        "claims": "EXPERIMENTAL_NOT_VALIDATED",
        "source_of_truth": "append_only_market_ledger",
        "observation_count": len(observations),
        "events": rows,
        "evaluation": {
            "market_only": evaluate_probabilities(rows, "entry_market_probabilities"),
            "market_plus_sharp": evaluate_probabilities(rows, "market_plus_sharp_probabilities"),
        },
        "evaluation_by_pricing_version": {
            key: {
                "pricing_model_version": subset[0].get("pricing_model_version"),
                "pricing_configuration_fingerprint": subset[0].get("pricing_configuration_fingerprint"),
                "market_only": evaluate_probabilities(subset, "entry_market_probabilities"),
                "market_plus_sharp": evaluate_probabilities(subset, "market_plus_sharp_probabilities"),
            }
            for key, subset in sorted(grouped.items())
        },
        "evaluation_by_cohort": {
            cohort: {
                "sample_size": len(subset),
                "market_only": evaluate_probabilities(subset, "pricing_market_probabilities"),
                "market_plus_fenzobot": evaluate_probabilities(subset, "fenzobot_probabilities"),
                "paired_delta": {
                    metric: (
                        round(
                            evaluate_probabilities(subset, "fenzobot_probabilities")[metric]
                            - evaluate_probabilities(subset, "pricing_market_probabilities")[metric],
                            6,
                        )
                        if evaluate_probabilities(subset, "fenzobot_probabilities")[metric] is not None
                        and evaluate_probabilities(subset, "pricing_market_probabilities")[metric] is not None
                        else None
                    )
                    for metric in ("brier_score", "log_loss")
                },
            }
            for cohort in sorted({
                name
                for row in rows
                for name, membership in (row.get("cohort_memberships") or {}).items()
                if isinstance(membership, Mapping) and membership.get("eligible") is True
            })
            for subset in [[
                row for row in rows
                if isinstance((row.get("cohort_memberships") or {}).get(cohort), Mapping)
                and (row.get("cohort_memberships") or {})[cohort].get("eligible") is True
            ]]
        },
        "unavailable_semantics": "Missing linkage or incomparable market data remains UNAVAILABLE; it is never inferred.",
    }


def write_report(report: Mapping[str, Any], *, path: Path = DEFAULT_OUTPUT_PATH) -> None:
    """Escrita atomica de uma vista derivada; o ledger nunca e alterado."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def build_and_write(**kwargs: Any) -> dict[str, Any]:
    output_path = kwargs.pop("output_path", DEFAULT_OUTPUT_PATH)
    report = build_report(**kwargs)
    write_report(report, path=output_path)
    return report
