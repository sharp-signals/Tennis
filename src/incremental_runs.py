"""Seleção incremental para execuções pré-live frequentes.

Uma execução adicional não deve recriar relatórios imutáveis que já são
válidos. Este módulo decide, de forma determinística, se uma fixture precisa
de pipeline completo: é nova, estava pendente e ganhou mercado, ou sofreu uma
mudança material de preço. Não calcula odds nem altera PAPER.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping


STATE_PATH = Path("data/cache/incremental_pre_live_state.json")
SNAPSHOTS_PATH = Path("data/calibration_snapshots.json")
SCHEMA_VERSION = 1
MATERIAL_IMPLIED_MOVE_PP = 3.0


def match_key(match: Mapping[str, object]) -> str:
    tour = str(match.get("_tour") or match.get("tour") or "unknown").casefold()
    match_id = match.get("id") or match.get("match_id")
    if match_id not in (None, ""):
        return f"{tour}:{match_id}"
    players = []
    for side in ("player1", "player2"):
        player = match.get(side) if isinstance(match.get(side), Mapping) else {}
        players.append(str((player or {}).get("name") or "").casefold().strip())
    return f"{tour}:{'|'.join(sorted(players))}:{str(match.get('date') or '')[:10]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load() -> dict:
    try:
        document = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {"schema_version": SCHEMA_VERSION, "entries": {}}
    if document.get("schema_version") != SCHEMA_VERSION or not isinstance(document.get("entries"), dict):
        return {"schema_version": SCHEMA_VERSION, "entries": {}}
    return document


def _write(document: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_name(f".{STATE_PATH.name}.tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(STATE_PATH)


def _implied_move_pp(previous: Mapping[str, object], current: Mapping[str, object]) -> float | None:
    moves: list[float] = []
    for player, old_odd in previous.items():
        try:
            old = float(old_odd)
            new = float(current.get(player))
        except (TypeError, ValueError):
            continue
        if old <= 1 or new <= 1 or not (math.isfinite(old) and math.isfinite(new)):
            continue
        moves.append(abs((1 / new - 1 / old) * 100))
    return max(moves) if moves else None


def bootstrap_from_snapshot(match: Mapping[str, object], snapshots: Mapping[str, Mapping[str, object]]) -> dict | None:
    """Aproveita o primeiro snapshot imutável para não duplicar relatórios."""
    snapshot = snapshots.get(match_key(match))
    if not isinstance(snapshot, Mapping):
        return None
    odds = snapshot.get("market_odds_decimal")
    return {
        "status": "AVAILABLE" if isinstance(odds, Mapping) and odds else "PENDING",
        "odds": dict(odds) if isinstance(odds, Mapping) else {},
        "source": "immutable_snapshot",
    }


def snapshot_entries() -> dict[str, dict]:
    """Lê apenas a chave e o preço do snapshot imutável já existente."""
    try:
        document = json.loads(SNAPSHOTS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    snapshots = document.get("snapshots") if isinstance(document, dict) else None
    if not isinstance(snapshots, list):
        return {}
    return {
        str(item["key"]): item for item in snapshots
        if isinstance(item, dict) and item.get("key")
    }


def decide(
    match: Mapping[str, object],
    current_odds: Mapping[str, object] | None,
    state_entry: Mapping[str, object] | None,
    *,
    threshold_pp: float = MATERIAL_IMPLIED_MOVE_PP,
) -> tuple[bool, str]:
    """Devolve ``(processar, razão)`` sem efeitos laterais."""
    has_market = isinstance(current_odds, Mapping) and len(current_odds) >= 2
    if not state_entry:
        return True, "new_fixture"
    was_available = state_entry.get("status") == "AVAILABLE"
    if not was_available:
        return (has_market, "pending_market_resolved" if has_market else "pending_market_still_unavailable")
    if not has_market:
        # Um preço antes válido que desapareceu não cria relatório novo; a
        # fila de mercado trata a reconsulta sem retirar o relatório válido.
        return False, "valid_market_temporarily_unavailable"
    move = _implied_move_pp(
        state_entry.get("odds") if isinstance(state_entry.get("odds"), Mapping) else {},
        current_odds,
    )
    if move is not None and move >= threshold_pp:
        return True, "material_market_move"
    return False, "valid_report_unchanged"


def read_entries() -> dict[str, dict]:
    return dict(_load().get("entries") or {})


def record_processed(match: Mapping[str, object], odds: Mapping[str, object] | None) -> None:
    document = _load()
    entries = document.setdefault("entries", {})
    entries[match_key(match)] = {
        "status": "AVAILABLE" if isinstance(odds, Mapping) and len(odds) >= 2 else "PENDING",
        "odds": dict(odds) if isinstance(odds, Mapping) else {},
        "updated_at_utc": _now(),
    }
    document["updated_at_utc"] = _now()
    _write(document)
