"""Frozen factual handicap evidence and downstream market review for SHADOW v2.

The evidence is built at prediction time from completed matches strictly before
the fixture.  It never changes the match-win probability.  A later market
quote may only select which already-frozen lines are useful to display.
"""

from __future__ import annotations

from datetime import date
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from .config import INVESTOR_PROFILE_ODDS_HIGH, INVESTOR_PROFILE_ODDS_LOW
from .contextual_family_replay import _cached_material
from .recent_form_replay import _game_margin, _name_key


EVIDENCE_PATH = Path("data/contextual_shadow_handicap_evidence-v2.jsonl")
EVIDENCE_VERSION = "contextual-shadow-handicap-evidence-v2.0"
MODEL_VERSION = "contextual-family-shadow-v2"
LINES = tuple(value / 2 for value in range(-12, 13) if value)

_FAVOURITE_REFERENCE = {
    "bo3": (
        (1.00, 1.30, (-4.5, -5.0)),
        (1.30, 1.40, (-4.0, -4.5)),
        (1.40, 1.51, (-3.0, -3.5)),
        (1.51, 1.61, (-1.5, -2.5)),
        (1.61, 1.75, (-1.0, -1.5)),
    ),
    "bo5": (
        (1.00, 1.30, (-5.0, -6.0)),
        (1.30, 1.40, (-4.0, -4.5)),
        (1.40, 1.51, (-3.5, -4.0)),
        (1.51, 1.61, (-2.5, -3.5)),
        (1.61, 1.75, (-1.0, -1.5)),
    ),
}
_UNDERDOG_REFERENCE = (
    (3.30, (3.5, 4.0)),
    (2.80, (3.0, 3.5)),
    (2.30, (2.0, 2.5)),
    (2.16, (1.5, 2.0)),
    (2.00, (1.0, 1.5)),
)


def infer_match_format(match: Mapping[str, Any]) -> str:
    for key in ("bestOf", "best_of", "bestOfSets"):
        try:
            value = int(float(match.get(key)))
        except (TypeError, ValueError):
            continue
        if value in {3, 5}:
            return f"bo{value}"
    return "bo3"


def _historical_format(row: Mapping[str, Any]) -> str | None:
    try:
        value = int(float(row.get("best_of")))
    except (TypeError, ValueError):
        value = 0
    if value in {3, 5}:
        return f"bo{value}"
    score = str(row.get("_score") or row.get("score") or "")
    winner_sets = 0
    for token in score.split():
        base = token.split("(", 1)[0]
        try:
            left, right = (int(item) for item in base.split("-", 1))
        except (TypeError, ValueError):
            continue
        winner_sets += int(left > right)
    return "bo5" if winner_sets == 3 else "bo3" if winner_sets == 2 else None


def _line_key(line: float) -> str:
    return f"{line:+g}"


def _settlement(margins: Iterable[float], line: float) -> dict[str, int]:
    cover = push = miss = 0
    for margin in margins:
        result = float(margin) + float(line)
        if result > 0:
            cover += 1
        elif result < 0:
            miss += 1
        else:
            push += 1
    return {"cover": cover, "push": push, "miss": miss}


def _player_evidence(rows: list[tuple[bool, float]]) -> dict[str, Any]:
    wins = [margin for won, margin in rows if won]
    losses = [margin for won, margin in rows if not won]
    return {
        "sample": len(rows),
        "wins": len(wins),
        "losses": len(losses),
        "lines": {
            _line_key(line): {
                "line": line,
                "total": _settlement((margin for _, margin in rows), line),
                "wins": _settlement(wins, line),
                "losses": _settlement(losses, line),
            }
            for line in LINES
        },
    }


def build_frozen_handicap_evidence(
    history: pd.DataFrame,
    *,
    observation_id: str,
    configuration_fingerprint: str,
    player_a: str,
    player_b: str,
    cutoff: date,
    match_format: str,
    captured_at_utc: str,
    model_version: str = MODEL_VERSION,
) -> dict[str, Any]:
    """Build pre-match BO3/BO5 margin counts with a strict chronological cut."""
    wanted = {"a": _name_key(player_a), "b": _name_key(player_b)}
    material = _cached_material(history)
    material = material[
        (material["_event_date"] < cutoff)
        & ~material["_non_standard"]
        & (
            material["_winner_key"].isin(wanted.values())
            | material["_loser_key"].isin(wanted.values())
        )
    ]
    rows: dict[str, list[tuple[bool, float]]] = {"a": [], "b": []}
    for _, match in material.iterrows():
        if _historical_format(match) != match_format:
            continue
        winner_margin = _game_margin(match.get("_score"), won=True)
        if winner_margin is None:
            continue
        winner = match.get("_winner_key")
        loser = match.get("_loser_key")
        for side, player in wanted.items():
            if winner == player:
                rows[side].append((True, float(winner_margin)))
            elif loser == player:
                rows[side].append((False, -float(winner_margin)))
    evidence = {
        "format": match_format,
        "cutoff": cutoff.isoformat(),
        "players": {
            "a": _player_evidence(rows["a"]),
            "b": _player_evidence(rows["b"]),
        },
    }
    material_hash = hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "schema_version": 1,
        "evidence_version": EVIDENCE_VERSION,
        "observation_id": observation_id,
        "model_version": model_version,
        "configuration_fingerprint": configuration_fingerprint,
        "captured_at_utc": captured_at_utc,
        "evidence_hash": material_hash,
        "production_effect": False,
        "handicap_evidence": evidence,
    }


def append_frozen_handicap_evidence(
    rows: Iterable[Mapping[str, Any]], path: Path = EVIDENCE_PATH,
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: set[str] = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                existing.add(str(json.loads(line).get("observation_id") or ""))
            except (ValueError, AttributeError):
                continue
    additions = []
    for row in rows:
        key = str(row.get("observation_id") or "")
        if key and key not in existing:
            additions.append(dict(row))
            existing.add(key)
    if additions:
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            for row in additions:
                handle.write(json.dumps(
                    row, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":"),
                ) + "\n")
    return len(additions)


def _reference_lines(odd: float, match_format: str, *, underdog: bool) -> list[float]:
    if underdog:
        pair = next((lines for threshold, lines in _UNDERDOG_REFERENCE if odd >= threshold), ())
        if not pair:
            return []
        return list(dict.fromkeys((*pair, pair[-1] + 0.5, pair[-1] + 1.0)))
    for low, high, pair in _FAVOURITE_REFERENCE.get(match_format, _FAVOURITE_REFERENCE["bo3"]):
        if low <= odd < high:
            return list(dict.fromkeys((pair[0] + 1.0, pair[0] + 0.5, *pair)))
    return []


def _price_line(
    *, probability: float, line: float, counts: Mapping[str, Any],
) -> dict[str, Any]:
    wins = counts.get("wins") or {}
    losses = counts.get("losses") or {}
    win_total = sum(int(wins.get(key) or 0) for key in ("cover", "push", "miss"))
    loss_total = sum(int(losses.get(key) or 0) for key in ("cover", "push", "miss"))
    relevant_sample = win_total if line < 0 else loss_total
    has_required_states = bool(win_total and loss_total)
    result = {
        "status": (
            "READY"
            if relevant_sample >= 30 and has_required_states
            else "INSUFFICIENT_SAMPLE"
        ),
        "relevant_sample": relevant_sample,
        "fair_odd": None,
        "minimum_odd": None,
        "maximum_odd": INVESTOR_PROFILE_ODDS_HIGH,
        "cover_probability_pct": None,
        "push_probability_pct": None,
    }
    if relevant_sample < 30 or not has_required_states:
        return result
    win_cover = float(wins["cover"]) / win_total
    win_push = float(wins["push"]) / win_total
    loss_cover = float(losses["cover"]) / loss_total
    loss_push = float(losses["push"]) / loss_total
    cover_probability = probability * win_cover + (1.0 - probability) * loss_cover
    push_probability = probability * win_push + (1.0 - probability) * loss_push
    miss_probability = max(0.0, 1.0 - cover_probability - push_probability)
    if cover_probability <= 0:
        return result
    fair = 1.0 + miss_probability / cover_probability
    minimum = max(
        INVESTOR_PROFILE_ODDS_LOW,
        math.floor((fair + 0.010000001) * 100.0) / 100.0,
    )
    result.update({
        "fair_odd": round(fair, 2),
        "minimum_odd": round(minimum, 2) if minimum <= INVESTOR_PROFILE_ODDS_HIGH else None,
        "cover_probability_pct": round(100.0 * cover_probability, 1),
        "push_probability_pct": round(100.0 * push_probability, 1),
    })
    return result


def build_market_review(
    *, probabilities: Mapping[str, float], intervals: Mapping[str, list[float]],
    odds: Mapping[str, float], evidence_record: Mapping[str, Any] | None,
    handicap_side: str | None = None,
) -> dict[str, Any]:
    """Select review markets after prediction; never alter model probability."""
    if not all(side in odds and float(odds[side]) > 1.0 for side in ("a", "b")):
        return {"status": "MARKET_UNAVAILABLE", "candidate_side": None}
    candidates = []
    for side in ("a", "b"):
        odd = float(odds[side])
        central_ev = 100.0 * (float(probabilities[side]) * odd - 1.0)
        conservative_ev = 100.0 * (float(intervals[side][0]) * odd - 1.0)
        if central_ev > 0:
            candidates.append((side, central_ev, conservative_ev))
    selected = max(candidates, key=lambda item: item[1]) if candidates else None
    side = selected[0] if selected else None
    central_ev = selected[1] if selected else None
    conservative_ev = selected[2] if selected else None
    review = {
        "status": (
            "CONSERVATIVE_POSITIVE" if conservative_ev is not None and conservative_ev > 0
            else "CENTRAL_ONLY" if selected else "NO_POSITIVE_EDGE"
        ),
        "candidate_side": side,
        "central_ev_pct": round(central_ev, 1) if central_ev is not None else None,
        "conservative_ev_pct": (
            round(conservative_ev, 1) if conservative_ev is not None else None
        ),
        "moneyline": None,
        "handicap": None,
    }
    if side is not None:
        odd = float(odds[side])
    else:
        odd = None
    if odd is not None and INVESTOR_PROFILE_ODDS_LOW <= odd <= INVESTOR_PROFILE_ODDS_HIGH:
        fair = 1.0 / float(probabilities[side])
        minimum = max(
            INVESTOR_PROFILE_ODDS_LOW,
            math.floor((fair + 0.010000001) * 100.0) / 100.0,
        )
        review["moneyline"] = {
            "observed_odd": odd,
            "fair_odd": round(fair, 2),
            "minimum_odd": round(minimum, 2) if minimum <= INVESTOR_PROFILE_ODDS_HIGH else None,
            "maximum_odd": INVESTOR_PROFILE_ODDS_HIGH,
        }
    handicap_side = handicap_side if handicap_side in {"a", "b"} else side
    if handicap_side is None:
        return review
    handicap_odd = float(odds[handicap_side])
    handicap_other = "b" if handicap_side == "a" else "a"
    underdog = handicap_odd > float(odds[handicap_other])
    evidence = (evidence_record or {}).get("handicap_evidence") or {}
    player_evidence = (evidence.get("players") or {}).get(handicap_side) or {}
    match_format = str(evidence.get("format") or "bo3")
    reference_lines = _reference_lines(handicap_odd, match_format, underdog=underdog)
    all_relevant_lines = [
        line for line in LINES
        if (line > 0 if underdog else line < 0)
    ]
    if not all_relevant_lines or not player_evidence:
        return review
    line_models = []
    reference_keys = {_line_key(line) for line in reference_lines}
    for line in all_relevant_lines:
        counts = (player_evidence.get("lines") or {}).get(_line_key(line))
        if not counts:
            continue
        total = counts.get("total") or {}
        wins = counts.get("wins") or {}
        losses = counts.get("losses") or {}
        total_n = sum(int(total.get(key) or 0) for key in ("cover", "push", "miss"))
        win_n = sum(int(wins.get(key) or 0) for key in ("cover", "push", "miss"))
        loss_n = sum(int(losses.get(key) or 0) for key in ("cover", "push", "miss"))
        line_models.append({
            "line": _line_key(line),
            "highlighted": _line_key(line) in reference_keys,
            "total": total_n,
            "cover": int(total.get("cover") or 0),
            "cover_pct": round(100.0 * int(total.get("cover") or 0) / total_n, 1) if total_n else None,
            "win_total": win_n,
            "win_cover": int(wins.get("cover") or 0),
            "win_cover_pct": round(100.0 * int(wins.get("cover") or 0) / win_n, 1) if win_n else None,
            "loss_total": loss_n,
            "loss_cover": int(losses.get("cover") or 0),
            "loss_cover_pct": round(100.0 * int(losses.get("cover") or 0) / loss_n, 1) if loss_n else None,
            "price": _price_line(
                probability=float(probabilities[handicap_side]), line=line, counts=counts,
            ),
        })
    if line_models:
        line_models.sort(key=lambda item: (
            not item["highlighted"], abs(float(item["line"])),
        ))
        review["handicap"] = {
            "side": handicap_side,
            "type": "positive" if underdog else "negative",
            "format": match_format.upper(),
            "lines": line_models,
            "highlight_lines": sorted(reference_keys),
            "evidence_version": (evidence_record or {}).get("evidence_version"),
        }
    return review
