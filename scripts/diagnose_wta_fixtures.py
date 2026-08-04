"""Diagnóstico isolado das fixtures WTA.

Não chama Anthropic, Odds API, Telegram, HTML ou o pipeline de análise.
Apenas consulta fixtures WTA e informação dos torneios encontrados.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src import fetch_data
from src.config import ALLOWED_TOURNAMENT_TIERS, TRACKED_TOURNAMENT_IDS


LOOKAHEAD_DAYS = 2
MAX_TOURNAMENT_INFO_REQUESTS = 20
OUTPUT_PATH = Path("wta-fixtures-diagnostic.json")


def player_name(match: dict[str, Any], key: str) -> str:
    player = match.get(key) or {}
    if isinstance(player, dict):
        return str(player.get("name") or "?")
    return "?"


def main() -> None:
    now = datetime.now(timezone.utc)
    all_matches: list[dict[str, Any]] = []
    day_results: list[dict[str, Any]] = []

    print("=" * 72)
    print("DIAGNÓSTICO ISOLADO DE FIXTURES WTA")
    print("=" * 72)
    print(f"UTC atual: {now.isoformat(timespec='seconds')}")
    print(f"Dias consultados: {LOOKAHEAD_DAYS}")
    print("Anthropic: BLOQUEADO")
    print("Odds API: NÃO UTILIZADA")
    print("Telegram: NÃO UTILIZADO")
    print()

    for offset in range(LOOKAHEAD_DAYS):
        day = now + timedelta(days=offset)
        day_label = day.strftime("%Y-%m-%d")

        try:
            matches = fetch_data._fetch_date_fixtures(day, "wta")
        except Exception as exc:
            print(f"[WTA] {day_label} | ERRO nas fixtures: {type(exc).__name__}: {exc}")
            day_results.append(
                {
                    "date": day_label,
                    "error": f"{type(exc).__name__}: {exc}",
                    "fixtures": 0,
                }
            )
            continue

        matches = matches or []

        for match in matches:
            match.setdefault("_tour", "wta")

        all_matches.extend(matches)

        tournament_counts = Counter(
            str(match.get("tournamentId"))
            for match in matches
            if match.get("tournamentId") is not None
        )

        print(
            f"[WTA] {day_label} | Fixtures: {len(matches)} | "
            f"Torneios: {len(tournament_counts)}"
        )

        day_results.append(
            {
                "date": day_label,
                "fixtures": len(matches),
                "tournaments": dict(tournament_counts),
            }
        )

    # Deduplicação por ID de jogo.
    deduplicated: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for match in all_matches:
        match_id = match.get("id")

        if match_id is None:
            deduplicated.append(match)
            continue

        key = str(match_id)
        if key in seen_ids:
            continue

        seen_ids.add(key)
        deduplicated.append(match)

    print()
    print(f"[WTA] Fixtures totais: {len(all_matches)}")
    print(f"[WTA] Fixtures após deduplicação: {len(deduplicated)}")

    by_tournament: dict[int, list[dict[str, Any]]] = {}

    for match in deduplicated:
        tournament_id = match.get("tournamentId")
        if tournament_id is None:
            continue

        try:
            normalized_id = int(tournament_id)
        except (TypeError, ValueError):
            continue

        by_tournament.setdefault(normalized_id, []).append(match)

    ordered_tournaments = sorted(
        by_tournament.items(),
        key=lambda item: len(item[1]),
        reverse=True,
    )

    tracked_wta_ids = {
        int(tournament_id)
        for tournament_id, tour in TRACKED_TOURNAMENT_IDS.items()
        if str(tour).lower() == "wta"
    }

    print()
    print("IDs WTA atualmente configurados:")
    print(sorted(tracked_wta_ids) or "Nenhum")
    print()
    print("Torneios encontrados no feed WTA:")
    print("-" * 72)

    tournament_results: list[dict[str, Any]] = []

    for index, (tournament_id, matches) in enumerate(ordered_tournaments):
        info = None
        info_error = None

        if index < MAX_TOURNAMENT_INFO_REQUESTS:
            try:
                info = fetch_data.get_tournament_info(tournament_id, "wta")
            except Exception as exc:
                info_error = f"{type(exc).__name__}: {exc}"

        info = info or {}

        tier = info.get("tier")
        eligible_tier = tier in ALLOWED_TOURNAMENT_TIERS
        is_tracked = tournament_id in tracked_wta_ids

        example = matches[0]
        example_players = (
            f"{player_name(example, 'player1')} vs "
            f"{player_name(example, 'player2')}"
        )

        dates = sorted(
            {
                str(match.get("date"))
                for match in matches
                if match.get("date")
            }
        )

        status = []

        if is_tracked:
            status.append("TRACKED")

        if eligible_tier:
            status.append("TIER PERMITIDO")
        elif tier:
            status.append("TIER EXCLUÍDO")
        else:
            status.append("TIER DESCONHECIDO")

        status_text = ", ".join(status)

        print(
            f"ID={tournament_id} | jogos={len(matches)} | "
            f"nome={info.get('name') or '?'} | "
            f"tier={tier or '?'} | "
            f"piso={info.get('surface') or '?'} | "
            f"{status_text}"
        )
        print(f"  Exemplo: {example_players}")
        print(f"  Datas: {dates[:4]}")

        tournament_results.append(
            {
                "tournament_id": tournament_id,
                "fixtures": len(matches),
                "tracked": is_tracked,
                "name": info.get("name"),
                "tier": tier,
                "surface": info.get("surface"),
                "country": info.get("country"),
                "eligible_tier": eligible_tier,
                "information_requested": index < MAX_TOURNAMENT_INFO_REQUESTS,
                "information_error": info_error,
                "example_players": example_players,
                "dates": dates,
            }
        )

    if not ordered_tournaments:
        print("Nenhum torneio WTA foi devolvido pelo feed global.")

    active_allowed = [
        item
        for item in tournament_results
        if item["eligible_tier"] and item["fixtures"] > 0
    ]

    print()
    print("=" * 72)
    print("CONCLUSÃO AUTOMÁTICA")
    print("=" * 72)
    print(f"Torneios WTA encontrados: {len(ordered_tournaments)}")
    print(f"Torneios WTA de tier permitido: {len(active_allowed)}")

    if active_allowed:
        print("IDs candidatos a adicionar a TRACKED_TOURNAMENT_IDS:")
        for item in active_allowed:
            print(
                f"  {item['tournament_id']}: 'wta' "
                f"# {item['name']} — {item['tier']}"
            )
    else:
        print(
            "Não foi encontrado nenhum torneio WTA de tier permitido "
            "nos dias consultados."
        )

    payload = {
        "generated_at": now.isoformat(timespec="seconds"),
        "lookahead_days": LOOKAHEAD_DAYS,
        "tracked_wta_ids": sorted(tracked_wta_ids),
        "allowed_tournament_tiers": sorted(ALLOWED_TOURNAMENT_TIERS),
        "fixtures_total": len(all_matches),
        "fixtures_deduplicated": len(deduplicated),
        "days": day_results,
        "tournaments": tournament_results,
        "candidate_tracked_tournaments": active_allowed,
    }

    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    print()
    print(f"Diagnóstico gravado em: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
