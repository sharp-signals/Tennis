"""Reconsulta leve de mercados RapidAPI que estavam pendentes no pré-live.

Não descobre fixtures, não calcula o índice Fenzobot, não cria relatórios e
nunca usa LLM. Serve apenas para voltar a obter a identidade validada e a
Moneyline de jogos que o bot já analisou mas cujo fornecedor ainda não tinha
publicado uma resposta bilateral utilizável.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from src import fetch_data


QUEUE_PATH = Path("data/cache/pending_market_checks.json")
MAX_ATTEMPTS_PER_RUN = int(os.environ.get("PENDING_MARKET_RETRY_MAX_PER_RUN", "20"))


def _parse_utc(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _pending_matches() -> list[dict]:
    try:
        document = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    entries = document.get("entries") if isinstance(document, dict) else None
    if not isinstance(entries, dict):
        return []
    now = datetime.now(timezone.utc)
    matches: list[dict] = []
    for entry in entries.values():
        data = entry.get("data") if isinstance(entry, dict) else None
        if not isinstance(data, dict) or data.get("status") != "PENDING":
            continue
        match = data.get("match")
        if not isinstance(match, dict):
            continue
        start = _parse_utc(match.get("date"))
        # Não gastamos chamadas em eventos já iniciados nem em fixtures sem
        # data verificável; o bot completo irá tratá-los no próximo ciclo.
        if start is None or start <= now:
            continue
        matches.append(match)
    return matches[:MAX_ATTEMPTS_PER_RUN]


def main() -> int:
    if not fetch_data.RAPIDAPI_KEY:
        print("[retry] RAPIDAPI_KEY ausente; nada a consultar.")
        return 0
    matches = _pending_matches()
    if not matches:
        print("[retry] Sem mercados pendentes pré-live.")
        return 0

    resolved = 0
    for match in matches:
        players = " vs ".join(str((match.get(side) or {}).get("name") or "?") for side in ("player1", "player2"))
        odds, provenance = fetch_data.fetch_rapidapi_recent_moneyline_with_provenance(match)
        if odds:
            resolved += 1
            print(f"[retry] RESOLVIDO | {players}")
        else:
            print(f"[retry] ainda pendente | {players} | {(provenance or {}).get('unavailable_reason', 'sem detalhe')}")
    print(json.dumps({
        "pending_checked": len(matches),
        "resolved": resolved,
        "rapidapi_calls": fetch_data.get_rapidapi_call_count(),
        "llm_calls": 0,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
