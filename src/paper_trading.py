"""Carteira PAPER append-only e metricas historicas auditaveis."""

from __future__ import annotations

import copy
import json
import math
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = 1
DEFAULT_PATH = Path("data/paper_trades.json")
_LOCK = threading.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"schema_version": SCHEMA_VERSION, "entries": []}
    if value.get("schema_version") != SCHEMA_VERSION or not isinstance(value.get("entries"), list):
        return {"schema_version": SCHEMA_VERSION, "entries": []}
    return value


def read_entries(path: Path = DEFAULT_PATH) -> list[dict[str, Any]]:
    return copy.deepcopy(_read(path)["entries"])


def _write(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def build_entries(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Cria uma entrada por mercado elegivel, sem alterar o payload."""
    decision = payload.get("prelive_decision")
    if not isinstance(decision, Mapping) or not decision.get("paper_eligible"):
        return []
    snapshot_key = str(payload.get("snapshot_key") or "")
    analyzed_at = payload.get("analyzed_at_utc") or _utc_now()
    entries = []
    for market in decision.get("paper_markets") or []:
        if not isinstance(market, Mapping):
            continue
        market_type = str(market.get("market_type") or "")
        side = str(market.get("side") or "")
        line = market.get("line")
        entry_key = f"{snapshot_key}:{market_type.casefold()}:{side}:{line if line is not None else 'na'}"
        pregame = {
            "snapshot_key": snapshot_key,
            "report_id": payload.get("report_id"),
            "match_id": payload.get("match_id"),
            "tour": payload.get("tour"),
            "tournament_id": payload.get("tournament_id"),
            "tournament": payload.get("tournament"),
            "surface": payload.get("surface"),
            "commence_time_utc": payload.get("commence_time_utc"),
            "analyzed_at_utc": analyzed_at,
            "players": {
                "a": {"id": payload.get("player_a_id"), "name": payload.get("player_a")},
                "b": {"id": payload.get("player_b_id"), "name": payload.get("player_b")},
            },
            "selected_side": side,
            "selected_player": market.get("player"),
            "fenzobot_index": decision.get("fenzobot_index"),
            "market_type": market_type,
            "market": market.get("market"),
            "line": line,
            "odd": market.get("odd"),
            "fair_odd": market.get("fair_odd"),
            "sharp_estimate_pct": market.get("sharp_estimate_pct"),
            "expected_edge_pct": market.get("expected_edge_pct"),
            "coverage": copy.deepcopy(decision.get("coverage")),
            "pricing_model_version": (payload.get("pricing") or {}).get("model_version"),
            "pricing_configuration_fingerprint": (payload.get("pricing") or {}).get(
                "configuration_fingerprint"
            ),
            "decision_contract_version": decision.get("contract_version"),
            "market_odds_decimal": copy.deepcopy(payload.get("market_odds_decimal")),
            "odds_provenance": {
                "source": payload.get("odds_source"),
                "captured_at_utc": payload.get("odds_captured_at_utc"),
                "capture_kind": payload.get("odds_capture_kind"),
            },
        }
        entries.append({
            "key": entry_key,
            "mode": "PAPER",
            "pregame": pregame,
            "settlement": None,
        })
    return entries


def append_entries(entries: Iterable[Mapping[str, Any]], path: Path = DEFAULT_PATH) -> int:
    """Acrescenta entradas novas; duplicados nunca reescrevem o pre-jogo."""
    with _LOCK:
        document = _read(path)
        existing = {item.get("key") for item in document["entries"] if item.get("key")}
        added = 0
        for entry in entries:
            key = entry.get("key")
            if key and key not in existing:
                document["entries"].append(copy.deepcopy(dict(entry)))
                existing.add(key)
                added += 1
        if added:
            document["entries"].sort(key=lambda item: (item.get("pregame") or {}).get("analyzed_at_utc") or "")
            document["updated_at_utc"] = _utc_now()
            _write(path, document)
        return added


def _parse_time(value: Any):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _players(match: Mapping[str, Any]) -> tuple[Any, Any]:
    return (
        match.get("player1Id") or (match.get("player1") or {}).get("id"),
        match.get("player2Id") or (match.get("player2") or {}).get("id"),
    )


def _game_margin(result: Any, selected_is_player1: bool) -> int | None:
    """Margem de jogos de um resultado completo; retires ficam N/D."""
    text = str(result or "")
    if not text or re.search(r"ret|w/o|walkover|aband", text, re.I):
        return None
    pairs = re.findall(r"(?<!\d)(\d{1,2})\s*[-:]\s*(\d{1,2})(?:\s*\([^)]*\))?", text)
    if not pairs:
        return None
    margin = sum(int(left) - int(right) for left, right in pairs)
    return margin if selected_is_player1 else -margin


def settle_from_matches(matches: Iterable[Mapping[str, Any]], path: Path = DEFAULT_PATH) -> int:
    completed = []
    for match in matches:
        if match.get("match_winner") is None:
            continue
        if str(match.get("result_type") or "").casefold() not in {"completed", "finished"}:
            continue
        completed.append(match)
    by_id = {str(match.get("id")): match for match in completed if match.get("id") is not None}

    def find(pregame: Mapping[str, Any]):
        direct = by_id.get(str(pregame.get("match_id")))
        if direct:
            return direct
        ids = frozenset(str((pregame.get("players") or {}).get(side, {}).get("id")) for side in ("a", "b"))
        scheduled = _parse_time(pregame.get("commence_time_utc"))
        candidates = []
        for match in completed:
            p1, p2 = _players(match)
            if frozenset((str(p1), str(p2))) != ids or scheduled is None:
                continue
            played = _parse_time(match.get("date"))
            if played is not None and abs((played - scheduled).total_seconds()) <= 48 * 3600:
                candidates.append((abs((played - scheduled).total_seconds()), match))
        return min(candidates, key=lambda item: item[0])[1] if candidates else None

    with _LOCK:
        document = _read(path)
        settled = 0
        for entry in document["entries"]:
            if entry.get("settlement") is not None:
                continue
            pregame = entry.get("pregame") or {}
            match = find(pregame)
            if not match:
                continue
            selected_side = pregame.get("selected_side")
            selected_id = (pregame.get("players") or {}).get(selected_side, {}).get("id")
            winner_id = match.get("match_winner")
            market_type = str(pregame.get("market_type") or "").casefold()
            result = None
            if market_type == "moneyline":
                result = "WIN" if str(winner_id) == str(selected_id) else "LOSS"
            elif market_type == "handicap":
                p1, _ = _players(match)
                margin = _game_margin(match.get("result"), str(selected_id) == str(p1))
                try:
                    adjusted = margin + float(pregame.get("line")) if margin is not None else None
                except (TypeError, ValueError):
                    adjusted = None
                result = "WIN" if adjusted is not None and adjusted > 0 else "LOSS" if adjusted is not None and adjusted < 0 else "PUSH" if adjusted == 0 else None
            if result is None:
                continue
            odd = pregame.get("odd")
            try:
                pnl = float(odd) - 1.0 if result == "WIN" else -1.0 if result == "LOSS" else 0.0
            except (TypeError, ValueError):
                pnl = None
            entry["settlement"] = {
                "result": result,
                "pnl_units": round(pnl, 4) if pnl is not None else None,
                "match_result": match.get("result"),
                "winner_id": winner_id,
                "closing_odd": None,
                "clv_pct": None,
                "settled_at_utc": _utc_now(),
            }
            settled += 1
        if settled:
            document["updated_at_utc"] = _utc_now()
            _write(path, document)
        return settled


def _summary(entries: list[Mapping[str, Any]]) -> dict[str, Any]:
    settled = [entry for entry in entries if isinstance(entry.get("settlement"), Mapping)]
    results = [entry["settlement"].get("result") for entry in settled]
    wins, losses, pushes = results.count("WIN"), results.count("LOSS"), results.count("PUSH")
    pnl_values = [entry["settlement"].get("pnl_units") for entry in settled]
    pnl_values = [float(value) for value in pnl_values if isinstance(value, (int, float))]
    units = sum(pnl_values)
    decided = wins + losses
    odds = [(entry.get("pregame") or {}).get("odd") for entry in entries]
    odds = [float(value) for value in odds if isinstance(value, (int, float))]
    edges = [(entry.get("pregame") or {}).get("expected_edge_pct") for entry in entries]
    edges = [float(value) for value in edges if isinstance(value, (int, float))]
    equity = peak = drawdown = 0.0
    cumulative = []
    for entry in sorted(settled, key=lambda item: (item.get("pregame") or {}).get("analyzed_at_utc") or ""):
        value = (entry.get("settlement") or {}).get("pnl_units")
        if not isinstance(value, (int, float)):
            continue
        equity += float(value)
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
        cumulative.append({"at": (entry.get("settlement") or {}).get("settled_at_utc"), "units": round(equity, 4)})
    return {
        "total_entries": len(entries),
        "settled": len(settled),
        "pending": len(entries) - len(settled),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "win_rate_pct": round(100 * wins / decided, 2) if decided else None,
        "units": round(units, 4) if pnl_values else None,
        "roi_pct": round(100 * units / len(pnl_values), 2) if pnl_values else None,
        "yield_pct": round(100 * units / len(pnl_values), 2) if pnl_values else None,
        "average_odd": round(sum(odds) / len(odds), 3) if odds else None,
        "average_edge_pct": round(sum(edges) / len(edges), 2) if edges else None,
        "clv_pct": None,
        "max_drawdown_units": round(drawdown, 4) if pnl_values else None,
        "cumulative": cumulative,
    }


def compute_history(path: Path = DEFAULT_PATH) -> dict[str, Any]:
    entries = _read(path)["entries"]
    by_market = {}
    for kind in ("Moneyline", "Handicap"):
        subset = [entry for entry in entries if str((entry.get("pregame") or {}).get("market_type")) == kind]
        by_market[kind] = _summary(subset) if subset else None
    return {
        "PAPER": {**_summary(entries), "by_market": by_market, "edge_buckets": None},
        "BACKTEST_RECONSTRUCTED": None,
        "REAL": None,
        "history_version": "paper-history-v1",
    }
