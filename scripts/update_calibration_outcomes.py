"""Atualiza resultados dos snapshots usando exclusivamente caches locais."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.calibration_store import settle_from_matches
from src import green_strong_validation, market_ledger, market_memory_report
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
    paper_count = settle_paper_from_matches(
        matches,
        ROOT / "data" / "paper_trades.json",
        ledger_root=ROOT / "data" / "market_ledger",
    )
    print(f"Entradas PAPER liquidadas: {paper_count}")
    try:
        report = market_memory_report.build_and_write(
            ledger_root=ROOT / "data" / "market_ledger",
            snapshots_path=ROOT / "data" / "calibration_snapshots.json",
            paper_path=ROOT / "data" / "paper_trades.json",
            output_path=ROOT / "data" / "market_ledger" / "derived" / "market-memory-v1.json",
        )
        archived = market_ledger.rotate_archives(root=ROOT / "data" / "market_ledger")
        print(
            "Market Memory atualizado: "
            f"{report['observation_count']} observações; {len(archived)} dia(s) arquivado(s)."
        )
        green = green_strong_validation.build_and_write(
            memory_report=report,
            manual_path=ROOT / "data" / "manual_paper_22bet.json",
            output_path=ROOT / "data" / "validation" / "green-strong-v1.json",
        )
        print(f"GREEN_STRONG_V1 atualizado: {green['metrics']['sample_size']} candidato(s).")
    except Exception as exc:
        # O contrato do CHANGE exige degradação aberta: settlement e PAPER
        # continuam válidos; apenas Market Memory/CLV fica indisponível.
        print(f"[market-memory] atualização não bloqueante indisponível: {type(exc).__name__}: {exc}")
