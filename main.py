"""
Ponto de entrada do bot. Corre via `python -m src.main` (é isto que o
workflow do GitHub Actions invoca).

Fluxo (v2, depois de descobrirmos que a Odds API sub-representava
torneios menores como o Umag):
1. Buscar TODOS os jogos dos próximos dias via RapidAPI/matchstat
   (getDateFixtures) — esta fonte não filtra por interesse de bookmaker,
   por isso apanha também ATP/WTA 250.
2. Para cada torneio envolvido, buscar o tier + piso (com cache local em
   data/tournament_cache.json) e filtrar pelos tiers que queremos.
3. Para cada jogo elegível, juntar features do histórico (H2H, forma,
   piso, fadiga) a partir das fontes gratuitas com fallback entre elas.
4. Tentar enriquecer com odds de mercado (Odds API) — opcional, por nome.
5. Pedir ao Claude uma análise estruturada por jogo (JSON), só com dados reais.
6. Montar o resumo curto (1 linha + emoji por jogo) e o relatório completo.
7. Publicar o relatório completo no Telegra.ph.
8. Enviar o resumo curto para o Telegram, com link no fim para o Telegra.ph.

Se não houver jogos elegíveis nesta janela, o script termina sem enviar
nada — não faz sentido mandar uma mensagem vazia.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from dateutil import parser as date_parser

from .config import (
    ALLOWED_TOURNAMENT_TIERS,
    FATIGUE_LOOKBACK_DAYS,
    FIXTURES_LOOKAHEAD_DAYS,
    LOOKAHEAD_HOURS_MAX,
    LOOKAHEAD_HOURS_MIN,
    ODDS_API_TENNIS_SPORT_KEYS,
    RECENT_FORM_MATCHES,
)
from . import fetch_data
from .analyze import analyze_match
from .telegraph import publish_report
from .telegram_bot import send_message


def _filter_and_enrich_with_tournament_info(raw_matches: list[dict]) -> list[dict]:
    """
    Para cada jogo, busca a info do torneio (cache-first) e só mantém os
    que pertencem a um tier permitido. Anexa 'tournament_name' e 'surface'
    diretamente no dict do jogo.
    """
    eligible = []
    for match in raw_matches:
        tour = match["_tour"]
        tournament_id = match.get("tournamentId")
        if tournament_id is None:
            continue

        info = fetch_data.get_tournament_info(tournament_id, tour)
        if info is None:
            # sem info de torneio disponível (falha da API e sem cache) —
            # não arriscamos incluir um Challenger/ITF por engano.
            print(f"[aviso] sem info do torneio {tournament_id}, jogo ignorado.")
            continue

        tier = info.get("tier")
        if tier not in ALLOWED_TOURNAMENT_TIERS:
            continue

        match["tournament_name"] = info.get("name") or f"Torneio {tournament_id}"
        match["surface"] = info.get("surface") or "Desconhecido"
        match["tier"] = tier
        eligible.append(match)

    return eligible


def _filter_matches_in_window(matches: list[dict]) -> list[dict]:
    now = datetime.now(timezone.utc)
    window_start = now + timedelta(hours=LOOKAHEAD_HOURS_MIN)
    window_end = now + timedelta(hours=LOOKAHEAD_HOURS_MAX)

    eligible = []
    for m in matches:
        try:
            start = date_parser.isoparse(m["date"])
        except (KeyError, ValueError):
            continue
        if window_start <= start <= window_end:
            eligible.append(m)
    return eligible


def _build_match_payload(match: dict) -> dict:
    tour = match["_tour"]
    history = fetch_data.get_history(tour)

    player_a = (match.get("player1") or {}).get("name", "?")
    player_b = (match.get("player2") or {}).get("name", "?")
    tournament = match["tournament_name"]
    surface = match["surface"]
    start = date_parser.isoparse(match["date"])

    odds = fetch_data.find_market_odds(ODDS_API_TENNIS_SPORT_KEYS, player_a, player_b)

    h2h = fetch_data.compute_h2h(history, player_a, player_b, surface)
    form_a = fetch_data.compute_recent_form(history, player_a, RECENT_FORM_MATCHES)
    form_b = fetch_data.compute_recent_form(history, player_b, RECENT_FORM_MATCHES)
    surface_a = fetch_data.compute_surface_stats(history, player_a, surface)
    surface_b = fetch_data.compute_surface_stats(history, player_b, surface)
    fatigue_a = fetch_data.compute_fatigue(history, player_a, start, FATIGUE_LOOKBACK_DAYS)
    fatigue_b = fetch_data.compute_fatigue(history, player_b, start, FATIGUE_LOOKBACK_DAYS)

    return {
        "player_a": player_a,
        "player_b": player_b,
        "tournament": tournament,
        "tier": match["tier"],
        "surface": surface,
        "commence_time_utc": start.isoformat(),
        "market_odds_decimal": odds,  # None é normal para torneios que a Odds API não cobre
        "h2h": h2h,
        "recent_form_a": form_a,
        "recent_form_b": form_b,
        "surface_stats_a": surface_a,
        "surface_stats_b": surface_b,
        "fatigue_signal_a": fatigue_a,
        "fatigue_signal_b": fatigue_b,
        "injury_data": None,  # nenhuma fonte gratuita fiável disponível — ver README
    }


def run() -> None:
    raw_matches = fetch_data.fetch_all_upcoming_fixtures(FIXTURES_LOOKAHEAD_DAYS)
    print(f"[info] {len(raw_matches)} jogo(s) devolvidos pelo matchstat antes de qualquer filtro.")

    windowed = _filter_matches_in_window(raw_matches)
    eligible = _filter_and_enrich_with_tournament_info(windowed)
    fetch_data.flush_tournament_cache()

    if not eligible:
        print("[info] Sem jogos elegíveis nesta janela (fora do tier permitido ou fora de horas). Nada a enviar.")
        return

    analyses = []
    for match in eligible:
        payload = _build_match_payload(match)
        result = analyze_match(payload)
        analyses.append((payload, result))

    # --- Relatório completo (Telegra.ph) ---
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report_parts = [f"# Relatório Pré-Live de Ténis — {today_str}\n"]
    for payload, result in analyses:
        report_parts.append(
            f"## {payload['player_a']} vs {payload['player_b']} "
            f"({payload['tournament']}, {payload['tier']}, {payload['surface']})\n\n"
            f"{result['full_report_markdown']}\n"
        )
    full_report_md = "\n".join(report_parts)

    telegraph_url = publish_report(f"Ténis Pré-Live — {today_str}", full_report_md)

    # --- Resumo curto (Telegram) ---
    summary_lines = [f"<b>🎾 Resumo Pré-Live — {today_str}</b>\n"]
    for payload, result in analyses:
        summary_lines.append(f"{result['flag']} {result['summary_line']}")
    summary_lines.append(f"\n📄 Relatório completo: {telegraph_url}")

    send_message("\n".join(summary_lines))
    print(f"[info] Enviado com sucesso. {len(analyses)} jogo(s). Relatório: {telegraph_url}")


if __name__ == "__main__":
    run()
