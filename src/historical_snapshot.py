"""Deterministic, temporally cut historical snapshot construction."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

import pandas as pd

from . import backtest, fetch_data, main, report_html
from .historical_warehouse import CHANGE_ID, HistoricalWarehouse, canonical_json, payload_hash, utc_now


REPLAY_VERSION = "historical-replay-v2"
ENGINE_VERSION = "fenzobot-v3-current"
PRICING_MODEL_VERSION = None
H2H_REQUIRED_PREHISTORY_PER_PLAYER = 10
H2H_AVAILABLE = "H2H_AVAILABLE"
H2H_NONE_OBSERVED_EX_ANTE = "H2H_NONE_OBSERVED_EX_ANTE"
H2H_DATA_INSUFFICIENT = "H2H_DATA_INSUFFICIENT"


class TemporalLeakageError(ValueError):
    pass


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_aggregate_is_ex_ante(*, aggregate_through_utc: str | None, as_of_utc: str) -> None:
    """Reject provider aggregates that may include the target or future games."""
    if aggregate_through_utc is None:
        raise TemporalLeakageError("Agregado sem timestamp 'through' não é admissível no replay.")
    if _parse_utc(aggregate_through_utc) >= _parse_utc(as_of_utc):
        raise TemporalLeakageError("Agregado inclui o cutoff ou informação futura.")


def config_hash() -> str:
    material = {
        "weights": report_html.PESOS,
        "family_caps": report_html.CAPS_FAMILIAS_PESOS,
        "engine": ENGINE_VERSION,
    }
    return hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()


def git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _winner_name(row: Mapping[str, Any]) -> str | None:
    winner = row.get("outcome_winner_id")
    if winner is None:
        return None
    winner = str(winner)
    if winner in {str(row.get("player_a_id")), str(row.get("player_a_name"))}:
        return str(row["player_a_name"])
    if winner in {str(row.get("player_b_id")), str(row.get("player_b_name"))}:
        return str(row["player_b_name"])
    # Some API records use 1/2 rather than an ID.
    if winner in {"1", "player1", "p1"}:
        return str(row["player_a_name"])
    if winner in {"2", "player2", "p2"}:
        return str(row["player_b_name"])
    return None


def _history_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    records = []
    for row in rows:
        winner = _winner_name(row)
        if not winner:
            continue
        loser = row["player_b_name"] if winner == row["player_a_name"] else row["player_a_name"]
        dt = _parse_utc(row["event_start_utc"])
        records.append({
            "winner_name": winner,
            "loser_name": loser,
            "winner_rank": row.get("player_a_rank") if winner == row["player_a_name"] else row.get("player_b_rank"),
            "loser_rank": row.get("player_b_rank") if winner == row["player_a_name"] else row.get("player_a_rank"),
            "surface": row.get("surface"),
            "tourney_date": dt.strftime("%Y%m%d"),
            "score": row.get("outcome_result"),
        })
    return pd.DataFrame(records)


def _feature(value: Any, *, sample_size: int | None, source: str, available: bool) -> dict[str, Any]:
    return {
        "value": value if available else None,
        "sample_size": sample_size,
        "source": source,
        "temporal_class": "RECONSTRUCTED_EX_ANTE" if available else "UNAVAILABLE",
        "available": available,
        "missing": not available,
    }


def _player_prehistory_matches(history: pd.DataFrame, player: str) -> int:
    if history.empty or not {"winner_name", "loser_name"}.issubset(history.columns):
        return 0
    return int(((history["winner_name"] == player) | (history["loser_name"] == player)).sum())


def build_historical_snapshot(
    warehouse: HistoricalWarehouse,
    match: str | Mapping[str, Any],
    as_of_utc: str,
    *,
    replay_version: str = REPLAY_VERSION,
) -> dict[str, Any]:
    if isinstance(match, str):
        target = warehouse.get_effective_match(match)
    else:
        # A caller-provided mapping is already the frozen input for this
        # snapshot (and is useful for leakage tests); never silently replace it.
        target = dict(match)
    if not target:
        raise KeyError(f"Jogo histórico inexistente: {match}")
    as_of = _parse_utc(as_of_utc)
    event_start = _parse_utc(target["event_start_utc"])
    if as_of > event_start:
        raise TemporalLeakageError("as_of_utc não pode ser posterior ao início do encontro.")

    cutoff = as_of
    safety_buffer_applied = False
    if target.get("date_precision") == "tournament_start":
        cutoff -= timedelta(days=backtest.LEAKAGE_SAFETY_BUFFER_DAYS)
        safety_buffer_applied = True

    candidates = warehouse.matches_before(cutoff.isoformat(), enriched=True)
    # Defensive check beyond the SQL predicate: rejects malformed/provider rows.
    safe_rows = [row for row in candidates if _parse_utc(row["event_start_utc"]) < cutoff]
    rejected = len(candidates) - len(safe_rows)
    history = _history_frame(safe_rows)
    a, b = target["player_a_name"], target["player_b_name"]
    surface = target.get("surface")
    h2h = fetch_data.compute_h2h(history, a, b, surface)
    prehistory_a = _player_prehistory_matches(history, a)
    prehistory_b = _player_prehistory_matches(history, b)
    if h2h is not None:
        h2h_status = H2H_AVAILABLE
    elif min(prehistory_a, prehistory_b) >= H2H_REQUIRED_PREHISTORY_PER_PLAYER:
        h2h_status = H2H_NONE_OBSERVED_EX_ANTE
    else:
        h2h_status = H2H_DATA_INSUFFICIENT
    form_a = fetch_data.compute_recent_form(history, a, 10)
    form_b = fetch_data.compute_recent_form(history, b, 10)
    surface_a = fetch_data.compute_surface_stats(history, a)
    surface_b = fetch_data.compute_surface_stats(history, b)

    # Ranking is taken only from the historical target record. No call to
    # singlesRanking (current ranking) is made anywhere in this module.
    ranking_a = {"rank": target.get("player_a_rank")} if target.get("player_a_rank") is not None else None
    ranking_b = {"rank": target.get("player_b_rank")} if target.get("player_b_rank") is not None else None
    payload = {
        "player_a": a, "player_b": b, "surface": surface,
        "ranking_a": ranking_a, "ranking_b": ranking_b,
        "h2h": h2h, "recent_form_a": form_a, "recent_form_b": form_b,
        "surface_stats_a": surface_a, "surface_stats_b": surface_b,
        # Historical quote semantics are not proven, so the pricing inputs
        # intentionally remain absent rather than pretending T-24h/T-1h.
        "market_odds_a": None, "market_odds_b": None,
    }
    payload["features"] = main._compute_features(payload)
    payload["divergencia"] = report_html.calcular_divergencia_publico(payload)

    overall = (h2h or {}).get("overall") or {}
    current_surface_a = (surface_a or {}).get(str(surface).lower()) or (surface_a or {}).get(str(surface).title())
    current_surface_b = (surface_b or {}).get(str(surface).lower()) or (surface_b or {}).get(str(surface).title())
    surface_history_source = (
        "warehouse.matches+match_enrichments<cutoff"
        if any((row.get("enrichment_provenance") or {}).get("surface") for row in safe_rows)
        else "warehouse.matches<cutoff"
    )
    features = {
        "ranking_a": _feature(target.get("player_a_rank"), sample_size=1 if ranking_a else None,
                              source=(target.get("enrichment_provenance") or {}).get("player_a_rank", {}).get("source", target["source"]), available=ranking_a is not None),
        "ranking_b": _feature(target.get("player_b_rank"), sample_size=1 if ranking_b else None,
                              source=(target.get("enrichment_provenance") or {}).get("player_b_rank", {}).get("source", target["source"]), available=ranking_b is not None),
        "h2h": {
            **_feature(
                h2h, sample_size=overall.get("total_matches"),
                source="warehouse.matches<cutoff", available=h2h is not None,
            ),
            "status": h2h_status,
            "prehistory_matches_a": prehistory_a,
            "prehistory_matches_b": prehistory_b,
            "required_prehistory_per_player": H2H_REQUIRED_PREHISTORY_PER_PLAYER,
        },
        "recent_form_a": _feature(form_a, sample_size=(form_a or {}).get("matches"), source="warehouse.matches<cutoff", available=form_a is not None),
        "recent_form_b": _feature(form_b, sample_size=(form_b or {}).get("matches"), source="warehouse.matches<cutoff", available=form_b is not None),
        "surface_a": _feature(current_surface_a, sample_size=(current_surface_a or {}).get("matches"), source=surface_history_source, available=current_surface_a is not None),
        "surface_b": _feature(current_surface_b, sample_size=(current_surface_b or {}).get("matches"), source=surface_history_source, available=current_surface_b is not None),
    }
    available = sum(1 for item in features.values() if item["available"])
    exact = sum(1 for item in features.values() if item["temporal_class"] == "EXACT_EX_ANTE")
    reconstructed = sum(1 for item in features.values() if item["temporal_class"] == "RECONSTRUCTED_EX_ANTE")
    missing = [name for name, item in features.items() if not item["available"]]
    stable = {
        "match_id": target["canonical_match_id"],
        "as_of_utc": as_of.isoformat(),
        "raw_source_references": warehouse.raw_references([row["canonical_match_id"] for row in safe_rows] + [target["canonical_match_id"]]),
        "feature_values": {
            "classified": features, "engine_features": payload["features"],
            "engine_divergence": payload["divergencia"],
            "effective_target_provenance": target.get("enrichment_provenance") or {},
        },
        "coverage": {
            "available": available, "total": len(features),
            "ratio": round(available / len(features), 4),
            "exact_ex_ante_fields": exact,
            "reconstructed_ex_ante_fields": reconstructed,
            "unavailable_fields": len(features) - available,
            "history_matches": len(history),
            "usable_market_quotes": warehouse.usable_market_quote_count(target["canonical_match_id"]),
        },
        "missing_data": missing,
        "temporal_rejections": {
            "future_or_cutoff_matches": rejected,
            "unsafe_aggregates": 0,
            "historical_quotes_unknown_semantics": True,
            "safety_buffer_days": backtest.LEAKAGE_SAFETY_BUFFER_DAYS if safety_buffer_applied else 0,
        },
        "engine_version": ENGINE_VERSION,
        "config_hash": config_hash(),
        "pricing_model_version": PRICING_MODEL_VERSION,
        "git_commit": git_commit(),
        "change_id": CHANGE_ID,
        "replay_version": replay_version,
    }
    digest = payload_hash(stable)
    stable.update({
        "snapshot_id": digest,
        "snapshot_hash": digest,
        "created_at_utc": utc_now(),
    })
    return stable
