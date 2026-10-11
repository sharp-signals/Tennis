"""Offline impact audit for CHANGE-2026-10-11-102.

Reads only committed player caches. It performs no network calls and writes
nothing unless --output is explicitly supplied.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from src import competition_evidence

NEW_POLICY = {
    "active": True,
    "tour": "atp",
    "change_id": competition_evidence.RANKING_ELIGIBLE_CHANGE_ID,
    "version": competition_evidence.RANKING_ELIGIBLE_POLICY_VERSION,
    "config_hash": competition_evidence.RANKING_ELIGIBLE_CONFIG_HASH,
}
CURRENT_POLICY = {
    "active": True,
    "tour": "atp",
    "change_id": competition_evidence.LAVER_ONLY_CHANGE_ID,
    "version": competition_evidence.LAVER_ONLY_POLICY_VERSION,
    "config_hash": competition_evidence.LAVER_ONLY_CONFIG_HASH,
}
FACTORS = (
    "h2h_recency", "tiebreak", "deciding_set", "comeback",
    "hands", "opponent_level", "cpi", "sample_confidence",
)


def _recent_rows(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    entry = ((payload.get("entries") or {}).get("recent_matches") or {})
    rows = entry.get("data") or []
    return [row for row in rows if isinstance(row, dict)]


def _positive_finite_weight(result: dict[str, Any]) -> bool:
    weight = result.get("weight")
    return (
        isinstance(weight, (int, float))
        and not isinstance(weight, bool)
        and math.isfinite(float(weight))
        and float(weight) > 0.0
    )


def _factor_applicable(factor: str, row: dict[str, Any]) -> bool:
    score = str(row.get("result") or row.get("score") or "")
    tournament = row.get("tournament") or {}
    if factor == "h2h_recency":
        return bool(row.get("player1") and row.get("player2"))
    if factor == "tiebreak":
        return "7-6" in score or "6-7" in score
    if factor in {"deciding_set", "comeback"}:
        return len(score.split()) >= 3
    if factor == "hands":
        return bool(row.get("player1") and row.get("player2"))
    if factor == "opponent_level":
        return any(row.get(key) not in (None, "") for key in (
            "player1Rank", "player2Rank", "winner_rank", "loser_rank"
        ))
    if factor == "cpi":
        return isinstance(tournament, dict) and (
            tournament.get("courtId") is not None
            or tournament.get("court") is not None
        )
    return True


def build_audit(cache_dir: Path) -> dict[str, Any]:
    files = sorted(cache_dir.glob("*.json"))
    unique: dict[str, dict[str, Any]] = {}
    per_player: dict[str, list[dict[str, Any]]] = {}
    for path in files:
        rows = _recent_rows(path)
        per_player[path.stem] = rows
        for row in rows:
            key = str(
                row.get("id") or row.get("matchId")
                or json.dumps(row, sort_keys=True, ensure_ascii=False)
            )
            previous = unique.get(key)
            if previous is None or len(json.dumps(row)) > len(json.dumps(previous)):
                unique[key] = row

    distribution: Counter[str] = Counter()
    non_ranking: Counter[str] = Counter()
    unresolved: Counter[str] = Counter()
    comparison: Counter[str] = Counter()
    factor_counts = {factor: Counter() for factor in FACTORS}

    for row in unique.values():
        current = competition_evidence.classify_match(row, CURRENT_POLICY)
        new = competition_evidence.classify_match(row, NEW_POLICY)
        classification = str(new.get("classification") or "UNRESOLVED")
        distribution[classification] += 1
        tournament = row.get("tournament") or {}
        name = (
            tournament.get("name") if isinstance(tournament, dict) else None
        ) or row.get("tournament_name") or row.get("tourney_name") or "N/D"
        identity = f"{name} [id={new.get('tournament_id') or 'N/D'}]"
        if classification == "NON_RANKING":
            non_ranking[identity] += 1
        if classification == "UNRESOLVED":
            unresolved[identity] += 1

        if _positive_finite_weight(current):
            comparison["laver_only_rows_admitted"] += 1
        elif current.get("weight") == 0.0:
            comparison["laver_only_rows_excluded"] += 1
        else:
            comparison["laver_only_rows_blocked"] += 1
        if new.get("weight") == 1.0:
            comparison["ranking_policy_rows_admitted"] += 1
        elif new.get("weight") == 0.0:
            comparison["ranking_policy_rows_excluded"] += 1
        else:
            comparison["ranking_policy_rows_blocked"] += 1

        for factor in FACTORS:
            if not _factor_applicable(factor, row):
                continue
            factor_counts[factor]["raw_applicable"] += 1
            if _positive_finite_weight(current):
                factor_counts[factor]["laver_only_admitted"] += 1
            elif current.get("weight") == 0.0:
                factor_counts[factor]["laver_only_excluded"] += 1
            else:
                factor_counts[factor]["laver_only_blocked"] += 1
            if new.get("weight") == 1.0:
                factor_counts[factor]["ranking_policy_admitted"] += 1
            elif new.get("weight") == 0.0:
                factor_counts[factor]["ranking_policy_excluded"] += 1
            else:
                factor_counts[factor]["ranking_policy_blocked"] += 1

    threshold_crossings: dict[str, int] = {}
    blocked_samples = 0
    removed_rows_by_sample = 0
    for threshold in (10, 30):
        crossings = 0
        for rows in per_player.values():
            current_count = sum(
                _positive_finite_weight(
                    competition_evidence.classify_match(row, CURRENT_POLICY)
                )
                for row in rows
            )
            classes = [
                competition_evidence.classify_match(row, NEW_POLICY)
                for row in rows
            ]
            blocked = any(item.get("weight") is None for item in classes)
            new_count = sum(item.get("weight") == 1.0 for item in classes)
            if current_count >= threshold and (blocked or new_count < threshold):
                crossings += 1
        threshold_crossings[str(threshold)] = crossings
    for rows in per_player.values():
        classes = [
            competition_evidence.classify_match(row, NEW_POLICY)
            for row in rows
        ]
        if any(item.get("weight") is None for item in classes):
            blocked_samples += 1
        removed_rows_by_sample += sum(item.get("weight") != 1.0 for item in classes)

    factors: dict[str, dict[str, Any]] = {}
    for factor, counts in factor_counts.items():
        before = counts["laver_only_admitted"]
        after = counts["ranking_policy_admitted"]
        factors[factor] = {
            **dict(counts),
            "rows_removed": before - after,
            "coverage_loss_pct": (
                round(100.0 * (before - after) / before, 3)
                if before else None
            ),
        }
    factors["fatigue_load"] = {
        "raw_rows_preserved": len(unique),
        "rows_removed": 0,
        "coverage_loss_pct": 0.0,
        "policy_application": "NOT_APPLIED_RAW_FACTUAL",
    }
    return {
        "audit_contract": "change-102-offline-cache-impact-v2",
        "policy_version": competition_evidence.RANKING_ELIGIBLE_POLICY_VERSION,
        "config_hash": competition_evidence.RANKING_ELIGIBLE_CONFIG_HASH,
        "registry_version": competition_evidence.RANKING_REGISTRY_VERSION,
        "registry_sha256": competition_evidence.RANKING_REGISTRY_SHA256,
        "source": str(cache_dir),
        "cache_files": len(files),
        "cached_rows_physical": sum(len(rows) for rows in per_player.values()),
        "unique_matches": len(unique),
        "classification_distribution": dict(sorted(distribution.items())),
        "non_ranking_competitions": [
            {"competition": key, "matches": value}
            for key, value in sorted(non_ranking.items())
        ],
        "unresolved_competitions": [
            {"competition": key, "matches": value}
            for key, value in sorted(unresolved.items())
        ],
        "policy_comparison": dict(comparison),
        "row_applicability_proxy": factors,
        "rows_removed_across_player_samples": removed_rows_by_sample,
        "player_samples_blocked_by_unresolved": blocked_samples,
        "samples_falling_below_existing_gates": threshold_crossings,
        "limitations": [
            "The committed ATP player cache is provider recent-match evidence, not a complete tour archive.",
            "Opponent-rank and player-hand availability cannot be inferred when those fields are absent from a cached match row.",
            "Row applicability is a cache-field proxy, not a replay of production factor coverage.",
            "UNRESOLVED is reported, never promoted through loader scope, tournament.rank, rankId, odds or fuzzy names.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cache-dir", type=Path,
        default=Path("data/cache/players/atp"),
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = build_audit(args.cache_dir)
    rendered = json.dumps(
        result, ensure_ascii=False, sort_keys=True, indent=2
    )
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
