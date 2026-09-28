"""Canonical, no-lookahead data products for the Fenzobot system history.

The bot may publish more than one HTML report for a fixture as the market
changes.  This module deliberately never uses those HTML files as analytical
rows.  The immutable first pre-match snapshot is the single observation for a
match, so a repeated report cannot inflate any learning metric.

Historical WTA aggregates are built exclusively from the locally cached
tennis-data.co.uk files.  They are labelled WTA / reference-line evidence and
are not PAPER results or bookmaker handicap settlement.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = 2
ODDS_BANDS = (
    (1.01, 1.20, "1.01–1.20"),
    (1.21, 1.30, "1.21–1.30"),
    (1.31, 1.40, "1.31–1.40"),
    (1.41, 1.50, "1.41–1.50"),
    (1.51, 1.60, "1.51–1.60"),
    (1.61, 1.75, "1.61–1.75"),
    (1.76, 2.00, "1.76–2.00"),
    (2.01, 2.30, "2.01–2.30"),
    (2.31, 2.80, "2.31–2.80"),
    (2.81, 3.30, "2.81–3.30"),
    (3.31, math.inf, "3.31+"),
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _timestamp(value: Any) -> str:
    return _text(value) or "9999-12-31T23:59:59+00:00"


def odds_band(odd: Any) -> str | None:
    value = _float(odd)
    if value is None or value <= 1:
        return None
    for lower, upper, label in ODDS_BANDS:
        if lower <= value <= upper:
            return label
    return None


def snapshot_event_id(snapshot: Mapping[str, Any]) -> str:
    """Stable event identity that is defensive against provider ID reuse."""
    canonical = _text(snapshot.get("canonical_match_instance_id"))
    if canonical:
        return canonical
    player_a = snapshot.get("player_a") if isinstance(snapshot.get("player_a"), Mapping) else {}
    player_b = snapshot.get("player_b") if isinstance(snapshot.get("player_b"), Mapping) else {}
    players = sorted(
        value.casefold()
        for value in (
            _text(player_a.get("id")) or _text(player_a.get("name")),
            _text(player_b.get("id")) or _text(player_b.get("name")),
        )
        if value
    )
    start_day = _text(snapshot.get("commence_time_utc"))[:10]
    return "|".join((
        _text(snapshot.get("tour")).casefold(),
        _text(snapshot.get("match_id") or snapshot.get("key")),
        start_day,
        ";".join(players),
    ))


def canonical_snapshots(snapshots: Iterable[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Keep the earliest immutable observation per event, with no overwrite."""
    selected: dict[str, dict[str, Any]] = {}
    raw_count = 0
    for raw in snapshots:
        if not isinstance(raw, Mapping):
            continue
        raw_count += 1
        snapshot = dict(raw)
        event_id = snapshot_event_id(snapshot)
        previous = selected.get(event_id)
        if previous is None or _timestamp(snapshot.get("analyzed_at_utc")) < _timestamp(previous.get("analyzed_at_utc")):
            selected[event_id] = snapshot
    ordered = sorted(selected.values(), key=lambda item: (_timestamp(item.get("analyzed_at_utc")), snapshot_event_id(item)))
    return ordered, raw_count - len(ordered)


def _role(odd: float | None, opponent_odd: float | None) -> str:
    if odd is None or opponent_odd is None:
        return "indisponível"
    if odd < opponent_odd:
        return "favorito"
    if odd > opponent_odd:
        return "underdog"
    return "equilibrado"


def _reference_lines_bo3(favourite_odd: float) -> tuple[float, ...]:
    """Internal BO3 reference zones, never asserted as bookmaker lines."""
    if favourite_odd < 1.30:
        return (-4.5, -5.0)
    if favourite_odd < 1.40:
        return (-4.0, -4.5)
    if favourite_odd < 1.51:
        return (-3.0, -3.5)
    if favourite_odd < 1.61:
        return (-1.5, -2.5)
    if favourite_odd < 1.75:
        return (-1.0, -1.5)
    return ()


def _pct(numerator: int, denominator: int) -> float | None:
    return round(numerator * 100 / denominator, 1) if denominator else None


def _aggregate_player_rows(rows: Iterable[tuple[str, str, str, bool]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], dict[str, int]] = defaultdict(lambda: {"matches": 0, "wins": 0})
    for player, band, role, won in rows:
        if not band:
            continue
        bucket = grouped[(player, band, role)]
        bucket["matches"] += 1
        bucket["wins"] += int(won)
    return [
        {
            "player": player, "odds_band": band, "role": role,
            "matches": value["matches"], "wins": value["wins"],
            "losses": value["matches"] - value["wins"], "win_pct": _pct(value["wins"], value["matches"]),
        }
        for (player, band, role), value in sorted(grouped.items(), key=lambda item: (-item[1]["matches"], item[0]))
    ]


def snapshot_performance(snapshots: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Outcome metrics from canonical Fenzobot observations only."""
    player_rows: list[tuple[str, str, str, bool]] = []
    model_rows: list[tuple[str, str, str, bool]] = []
    event_rows: list[dict[str, Any]] = []
    for snapshot in snapshots:
        a = snapshot.get("player_a") if isinstance(snapshot.get("player_a"), Mapping) else {}
        b = snapshot.get("player_b") if isinstance(snapshot.get("player_b"), Mapping) else {}
        name_a, name_b = _text(a.get("name")), _text(b.get("name"))
        odds = snapshot.get("market_odds_decimal") if isinstance(snapshot.get("market_odds_decimal"), Mapping) else {}
        odd_a, odd_b = _float(odds.get(name_a)), _float(odds.get(name_b))
        outcome = snapshot.get("outcome") if isinstance(snapshot.get("outcome"), Mapping) else {}
        winner = _text(outcome.get("winner_side"))
        settled = winner in {"a", "b"}
        for name, own, other, side in ((name_a, odd_a, odd_b, "a"), (name_b, odd_b, odd_a, "b")):
            if not name or not settled:
                continue
            player_rows.append((name, odds_band(own) or "sem faixa", _role(own, other), winner == side))
        divergence = ((snapshot.get("metrics") or {}).get("divergencia") or {}) if isinstance(snapshot.get("metrics"), Mapping) else {}
        model_side = _text(divergence.get("indice_favorece"))
        if settled and model_side in {name_a, name_b}:
            own = odd_a if model_side == name_a else odd_b
            other = odd_b if model_side == name_a else odd_a
            model_rows.append((model_side, odds_band(own) or "sem faixa", _role(own, other), winner == ("a" if model_side == name_a else "b")))
        event_rows.append({
            "event_id": snapshot_event_id(snapshot), "snapshot_key": snapshot.get("key"),
            "analyzed_at_utc": snapshot.get("analyzed_at_utc"), "commence_time_utc": snapshot.get("commence_time_utc"),
            "tour": _text(snapshot.get("tour")).upper(), "tournament": snapshot.get("tournament"),
            "player_a": name_a, "player_b": name_b, "odd_a": odd_a, "odd_b": odd_b,
            "winner_side": winner or None, "result": outcome.get("result"),
            "fenzobot_side": model_side or None,
        })
    return {"event_rows": event_rows, "player_odds": _aggregate_player_rows(player_rows), "fenzobot_odds": _aggregate_player_rows(model_rows)}


def _int(value: Any) -> int | None:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return int(parsed) if math.isfinite(parsed) and parsed.is_integer() else None


def load_local_wta_history(cache_dir: Path) -> list[dict[str, Any]]:
    """Read the WTA raw files already present locally; never fetches data."""
    rows: list[dict[str, Any]] = []
    for path in sorted(cache_dir.glob("wta_tdcouk_*.csv")):
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if _text(row.get("Comment")).casefold() not in {"", "completed"}:
                    continue
                winner, loser = _text(row.get("winner_name")), _text(row.get("loser_name"))
                if not winner or not loser:
                    continue
                w1, l1, w2, l2, w3, l3 = (_int(row.get(key)) for key in ("W1", "L1", "W2", "L2", "W3", "L3"))
                if None in {w1, l1, w2, l2}:
                    continue
                odds_w = _float(row.get("AvgW")) or _float(row.get("PSW")) or _float(row.get("B365W"))
                odds_l = _float(row.get("AvgL")) or _float(row.get("PSL")) or _float(row.get("B365L"))
                rows.append({
                    "date": _text(row.get("tourney_date")), "winner": winner, "loser": loser,
                    "winner_odd": odds_w, "loser_odd": odds_l,
                    "winner_games": w1 + w2 + (w3 or 0), "loser_games": l1 + l2 + (l3 or 0),
                    "winner_lost_first": w1 < l1, "deciding_set": w3 is not None and l3 is not None,
                    "winner_tiebreak": max(w1, l1) == 7 and abs(w1 - l1) == 1 or max(w2, l2) == 7 and abs(w2 - l2) == 1 or (w3 is not None and l3 is not None and max(w3, l3) == 7 and abs(w3 - l3) == 1),
                })
    return rows


def historical_wta_analytics(matches: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    player_rows: list[tuple[str, str, str, bool]] = []
    handicap: dict[tuple[str, str, float], dict[str, int]] = defaultdict(lambda: {"matches": 0, "covers": 0, "pushes": 0, "fails": 0})
    recovery: dict[str, dict[str, int]] = defaultdict(lambda: {"lost_first": 0, "recovered": 0})
    deciding: dict[str, dict[str, int]] = defaultdict(lambda: {"matches": 0, "wins": 0})
    tiebreak: dict[str, dict[str, int]] = defaultdict(lambda: {"matches": 0, "wins": 0})
    for match in matches:
        winner, loser = _text(match.get("winner")), _text(match.get("loser"))
        odd_w, odd_l = _float(match.get("winner_odd")), _float(match.get("loser_odd"))
        if odd_w and odd_l:
            player_rows.extend(((winner, odds_band(odd_w) or "sem faixa", _role(odd_w, odd_l), True), (loser, odds_band(odd_l) or "sem faixa", _role(odd_l, odd_w), False)))
            favourite, favourite_odd = (winner, odd_w) if odd_w < odd_l else (loser, odd_l)
            fav_diff = (int(match["winner_games"]) - int(match["loser_games"])) * (1 if favourite == winner else -1)
            for line in _reference_lines_bo3(favourite_odd):
                for player, applied_line, games_diff, role in ((favourite, line, fav_diff, "favorito"), (loser if favourite == winner else winner, -line, -fav_diff, "underdog")):
                    item = handicap[(player, role, applied_line)]
                    item["matches"] += 1
                    total = games_diff + applied_line
                    if total > 0:
                        item["covers"] += 1
                    elif total == 0:
                        item["pushes"] += 1
                    else:
                        item["fails"] += 1
        if match.get("winner_lost_first"):
            recovery[winner]["lost_first"] += 1
            recovery[winner]["recovered"] += 1
        else:
            # If the eventual winner won set one, the loser is the player who
            # lost it first and did not recover.  Keeping this denominator is
            # essential: otherwise every player's recovery rate is inflated.
            recovery[loser]["lost_first"] += 1
        if match.get("deciding_set"):
            deciding[winner]["matches"] += 1; deciding[winner]["wins"] += 1
            deciding[loser]["matches"] += 1
        if match.get("winner_tiebreak"):
            tiebreak[winner]["matches"] += 1; tiebreak[winner]["wins"] += 1
            tiebreak[loser]["matches"] += 1
    handicap_rows = []
    for (player, role, line), value in sorted(handicap.items(), key=lambda item: (-item[1]["matches"], item[0])):
        handicap_rows.append({"player": player, "role": role, "reference_line": line, **value, "cover_pct": _pct(value["covers"], value["matches"])})
    recovery_rows = [{"player": player, **value, "recovery_pct": _pct(value["recovered"], value["lost_first"])} for player, value in sorted(recovery.items(), key=lambda item: (-item[1]["lost_first"], item[0]))]
    deciding_rows = [{"player": player, **value, "win_pct": _pct(value["wins"], value["matches"])} for player, value in sorted(deciding.items(), key=lambda item: (-item[1]["matches"], item[0]))]
    tiebreak_rows = [{"player": player, **value, "win_pct": _pct(value["wins"], value["matches"])} for player, value in sorted(tiebreak.items(), key=lambda item: (-item[1]["matches"], item[0]))]
    return {"player_odds": _aggregate_player_rows(player_rows), "handicap_reference": handicap_rows, "set1_recovery": recovery_rows, "deciding_set": deciding_rows, "tiebreak": tiebreak_rows}


def build_system_history(
    snapshot_document: Mapping[str, Any],
    local_wta_matches: Iterable[Mapping[str, Any]],
    report_files: Iterable[str] = (),
) -> dict[str, Any]:
    local_wta_matches = list(local_wta_matches)
    report_registry = []
    for name in sorted({_text(item) for item in report_files if _text(item)}):
        match = re.search(r"(20\d{2}-\d{2}-\d{2})", name)
        report_registry.append({"report_file": name, "report_date": match.group(1) if match else None})
    raw = snapshot_document.get("snapshots") if isinstance(snapshot_document.get("snapshots"), list) else []
    canonical, removed = canonical_snapshots(raw)
    operational = snapshot_performance(canonical)
    history = historical_wta_analytics(local_wta_matches)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "methodology": {
            "canonical_snapshot_rule": "first_valid_pre_match_snapshot_per_event",
            "raw_report_html_excluded_from_metrics": True,
            "historical_wta_source": "local tennis-data.co.uk cache only",
            "handicap_reference": "BO3 internal reference line; not a bookmaker handicap settlement",
        },
        "summary": {
            "raw_snapshots": len(raw), "canonical_snapshots": len(canonical), "duplicate_snapshots_excluded": removed,
            "settled_canonical_snapshots": sum(1 for item in canonical if _text((item.get("outcome") or {}).get("winner_side")) in {"a", "b"}),
            "historical_wta_matches": len(local_wta_matches),
            "raw_report_html_versions": len(report_registry),
        },
        "operational": operational,
        "historical_wta": history,
        "report_registry": report_registry,
    }
    canonical_text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["input_fingerprint_sha256"] = hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()
    return payload


def write_if_changed(payload: Mapping[str, Any], target: Path) -> bool:
    """Avoid commits and workbook rewrites when source data did not change."""
    try:
        old = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        old = {}
    if old.get("input_fingerprint_sha256") == payload.get("input_fingerprint_sha256"):
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return True
