"""Atualiza resultados dos snapshots usando exclusivamente caches locais."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.calibration_store import settle_from_matches
from src.paper_trading import settle_from_matches as settle_paper_from_matches


def cached_matches(cache_root: Path):
    seen = set()
    for path in cache_root.glob("*/*.json"):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        matches = ((document.get("entries") or {}).get("recent_matches") or {}).get("data") or []
        for match in matches:
            match_id = match.get("id")
            if match_id is not None and str(match_id) not in seen:
                seen.add(str(match_id))
                yield match


if __name__ == "__main__":
    matches = list(cached_matches(ROOT / "data" / "cache" / "players"))
    count = settle_from_matches(
        matches,
        ROOT / "data" / "calibration_snapshots.json",
    )
    print(f"Snapshots com resultado atualizado: {count}")
    paper_count = settle_paper_from_matches(matches, ROOT / "data" / "paper_trades.json")
    print(f"Entradas PAPER liquidadas: {paper_count}")
