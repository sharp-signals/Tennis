"""Mede cobertura das métricas avançadas usando apenas caches locais."""

from __future__ import annotations

import json
from pathlib import Path


def analyze(cache_root: Path) -> dict:
    files = list(cache_root.glob("*/*.json"))
    counts = {
        "players": len(files),
        "past_matches": 0,
        "players_with_historical_odds": 0,
        "historical_matches": 0,
        "matches_with_two_odds": 0,
        "recent_stats": 0,
        "average_opponent_rank": 0,
        "career_stats": 0,
        "career_point_totals": 0,
        "perf_breakdown": 0,
        "perf_breakdown_by_year": 0,
    }
    for path in files:
        try:
            entries = json.loads(path.read_text(encoding="utf-8")).get("entries", {})
        except (OSError, json.JSONDecodeError):
            continue
        matches = (entries.get("recent_matches") or {}).get("data") or []
        usable_odds = [
            match for match in matches
            if match.get("odd1") not in (None, "") and match.get("odd2") not in (None, "")
        ]
        counts["past_matches"] += bool(matches)
        counts["players_with_historical_odds"] += bool(usable_odds)
        counts["historical_matches"] += len(matches)
        counts["matches_with_two_odds"] += len(usable_odds)

        recent = (entries.get("recent_stats") or {}).get("data") or {}
        counts["recent_stats"] += bool(recent)
        counts["average_opponent_rank"] += bool((recent.get("yearStats") or {}).get("avgOppRank"))

        career = (entries.get("career_stats") or {}).get("data") or {}
        counts["career_stats"] += bool(career)
        counts["career_point_totals"] += bool((career.get("playerStats") or {}).get("totalPointsWon"))

        perf = (entries.get("perf_breakdown") or {}).get("data") or {}
        counts["perf_breakdown"] += bool(perf)
        counts["perf_breakdown_by_year"] += bool(perf.get("by_year"))
    return counts


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1] / "data" / "cache" / "players"
    print(json.dumps(analyze(root), ensure_ascii=False, indent=2))
