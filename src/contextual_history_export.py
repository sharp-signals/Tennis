"""Flatten the contextual release ledgers for Excel/Google Sheets views."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


RELEASE_SLUG = "fenzobot-contextual-2026-11"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _pct(part: Any, total: Any) -> float | None:
    try:
        denominator = int(total)
        return round(100.0 * int(part) / denominator, 1) if denominator else None
    except (TypeError, ValueError):
        return None


def _side_name(observation: Mapping[str, Any], side: str | None) -> str | None:
    player = ((observation.get("players") or {}).get(side or "") or {})
    return player.get("name")


def _evidence_map(rows: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {
        str(row.get("observation_id")): row
        for row in rows if row.get("observation_id")
    }


def build_contextual_history_export(
    *, observations_path: Path, market_path: Path, outcomes_path: Path,
    handicap_path: Path, moneyline_path: Path, h2h_path: Path,
) -> dict[str, Any]:
    """Return a stable, denormalised view without changing source ledgers."""
    observations = _read_jsonl(observations_path)
    markets = _evidence_map(_read_jsonl(market_path))
    outcomes = _evidence_map(_read_jsonl(outcomes_path))
    handicaps = _evidence_map(_read_jsonl(handicap_path))
    moneylines = _evidence_map(_read_jsonl(moneyline_path))
    h2hs = _evidence_map(_read_jsonl(h2h_path))
    games: list[dict[str, Any]] = []
    families: list[dict[str, Any]] = []
    moneyline_rows: list[dict[str, Any]] = []
    handicap_rows: list[dict[str, Any]] = []
    h2h_rows: list[dict[str, Any]] = []

    for observation in observations:
        observation_id = str(observation.get("observation_id") or "")
        shadow = observation.get("contextual_shadow") or {}
        players = observation.get("players") or {}
        competition = observation.get("competition") or {}
        market = markets.get(observation_id) or {}
        outcome = outcomes.get(observation_id) or {}
        probability_a = shadow.get("probability_model_a")
        probability_b = shadow.get("probability_model_b")
        odds = market.get("odds") or {}
        market_probability = market.get("market_probability_devig") or {}
        favorite_side = (
            "a" if isinstance(probability_a, (int, float))
            and float(probability_a) >= float(probability_b or 0.0) else "b"
        )
        fair_a = shadow.get("fair_odd_model_a") or {}
        fair_b = shadow.get("fair_odd_model_b") or {}
        coverage = shadow.get("family_coverage") or {}
        winner_side = outcome.get("winner_side")
        games.append({
            "observation_id": observation_id,
            "canonical_match_instance_id": observation.get("canonical_match_instance_id"),
            "analyzed_at_utc": observation.get("analyzed_at_utc"),
            "commence_time_utc": observation.get("commence_time_utc"),
            "tour": observation.get("tour"),
            "tier": observation.get("tier"),
            "tournament": competition.get("tournament_name"),
            "round": competition.get("round_stage"),
            "surface": shadow.get("surface_context") or competition.get("surface"),
            "player_a": (players.get("a") or {}).get("name"),
            "player_b": (players.get("b") or {}).get("name"),
            "probability_a_pct": round(100.0 * float(probability_a), 2) if isinstance(probability_a, (int, float)) else None,
            "probability_b_pct": round(100.0 * float(probability_b), 2) if isinstance(probability_b, (int, float)) else None,
            "fair_odd_a": fair_a.get("central"),
            "fair_odd_a_min": fair_a.get("lower_odd"),
            "fair_odd_a_max": fair_a.get("upper_odd"),
            "fair_odd_b": fair_b.get("central"),
            "fair_odd_b_min": fair_b.get("lower_odd"),
            "fair_odd_b_max": fair_b.get("upper_odd"),
            "model_favorite": _side_name(observation, favorite_side),
            "coverage_pct": coverage.get("pct"),
            "families_observed": coverage.get("observed"),
            "families_total": coverage.get("total"),
            "quality_group": shadow.get("quality_group"),
            "status": shadow.get("status"),
            "reason_codes": ", ".join(map(str, shadow.get("reason_codes") or [])),
            "market_odd_a": odds.get("a"),
            "market_odd_b": odds.get("b"),
            "market_probability_a_pct": round(100.0 * float(market_probability.get("a")), 2) if isinstance(market_probability.get("a"), (int, float)) else None,
            "market_probability_b_pct": round(100.0 * float(market_probability.get("b")), 2) if isinstance(market_probability.get("b"), (int, float)) else None,
            "market_captured_at_utc": market.get("captured_at_utc"),
            "bookmaker": market.get("bookmaker"),
            "winner": _side_name(observation, winner_side),
            "winner_side": winner_side,
            "prediction_correct": favorite_side == winner_side if winner_side in {"a", "b"} else None,
            "settled_at_utc": outcome.get("settled_at_utc"),
        })

        for family in shadow.get("families") or []:
            if not isinstance(family, Mapping):
                continue
            families.append({
                "observation_id": observation_id,
                "tour": observation.get("tour"),
                "player_a": (players.get("a") or {}).get("name"),
                "player_b": (players.get("b") or {}).get("name"),
                "family": family.get("label") or family.get("key"),
                "family_key": family.get("key"),
                "data_state": family.get("data_state"),
                "coverage_grade": family.get("coverage_grade"),
                "probability_a_pct": round(100.0 * float(family.get("probability_model_a")), 2) if isinstance(family.get("probability_model_a"), (int, float)) else None,
                "impact_pp_model_a": family.get("impact_pp_model_a"),
                "impact_intensity": family.get("impact_intensity"),
                "logit_contribution": family.get("logit_contribution"),
            })

        moneyline = (moneylines.get(observation_id) or {}).get("moneyline_evidence") or {}
        for side in ("a", "b"):
            player = (moneyline.get("players") or {}).get(side) or {}
            for format_name, values in (player.get("general") or {}).items():
                moneyline_rows.append({
                    "observation_id": observation_id, "side": side,
                    "player": _side_name(observation, side), "scope": "general",
                    "odds_band": "Todas", "format": format_name,
                    "sample": values.get("sample"), "wins": values.get("wins"),
                    "win_rate_pct": values.get("win_rate_pct"),
                    "source": player.get("source"), "odds_basis": player.get("odds_basis"),
                })
            for odds_band, formats in (player.get("buckets") or {}).items():
                for format_name, values in (formats or {}).items():
                    moneyline_rows.append({
                        "observation_id": observation_id, "side": side,
                        "player": _side_name(observation, side), "scope": "faixa",
                        "odds_band": odds_band, "format": format_name,
                        "sample": values.get("sample"), "wins": values.get("wins"),
                        "win_rate_pct": values.get("win_rate_pct"),
                        "source": player.get("source"), "odds_basis": player.get("odds_basis"),
                    })

        handicap = (handicaps.get(observation_id) or {}).get("handicap_evidence") or {}
        for side in ("a", "b"):
            player = (handicap.get("players") or {}).get(side) or {}
            for line_label, line in (player.get("lines") or {}).items():
                total = line.get("total") or {}
                wins = line.get("wins") or {}
                losses = line.get("losses") or {}
                total_sample = sum(int(total.get(key) or 0) for key in ("cover", "push", "miss"))
                wins_sample = sum(int(wins.get(key) or 0) for key in ("cover", "push", "miss"))
                losses_sample = sum(int(losses.get(key) or 0) for key in ("cover", "push", "miss"))
                handicap_rows.append({
                    "observation_id": observation_id, "side": side,
                    "player": _side_name(observation, side),
                    "format": handicap.get("format"), "line": line.get("line", line_label),
                    "total_sample": total_sample, "total_cover": total.get("cover"),
                    "total_push": total.get("push"), "total_miss": total.get("miss"),
                    "total_cover_pct": _pct(total.get("cover"), total_sample),
                    "wins_sample": wins_sample, "wins_cover": wins.get("cover"),
                    "wins_cover_pct": _pct(wins.get("cover"), wins_sample),
                    "losses_sample": losses_sample, "losses_cover": losses.get("cover"),
                    "losses_cover_pct": _pct(losses.get("cover"), losses_sample),
                })

        h2h = (h2hs.get(observation_id) or {}).get("h2h_evidence") or {}
        for match in h2h.get("matches") or []:
            if not isinstance(match, Mapping):
                continue
            h2h_rows.append({
                "observation_id": observation_id,
                "player_a": (players.get("a") or {}).get("name"),
                "player_b": (players.get("b") or {}).get("name"),
                "event_date": match.get("event_date"),
                "tournament": match.get("tournament"),
                "round": match.get("round"),
                "surface": match.get("surface"),
                "winner": _side_name(observation, match.get("winner_side")),
                "score": match.get("score"),
            })

    source_paths = (
        observations_path, market_path, outcomes_path, handicap_path,
        moneyline_path, h2h_path,
    )
    digest = hashlib.sha256()
    for path in source_paths:
        digest.update(path.name.encode("utf-8"))
        if path.exists():
            digest.update(path.read_bytes())
    return {
        "schema_version": 1,
        "release": "FENZOBOT_CONTEXTUAL_2026_11",
        "source_fingerprint_sha256": digest.hexdigest(),
        "summary": {
            "observations": len(observations),
            "with_market": sum(str(row.get("observation_id")) in markets for row in observations),
            "settled": sum(str(row.get("observation_id")) in outcomes for row in observations),
            "family_rows": len(families),
            "moneyline_rows": len(moneyline_rows),
            "handicap_rows": len(handicap_rows),
            "h2h_matches": len(h2h_rows),
        },
        "games": games,
        "families": families,
        "moneyline": moneyline_rows,
        "handicaps": handicap_rows,
        "h2h": h2h_rows,
    }
