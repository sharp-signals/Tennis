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

import html
from datetime import datetime, timedelta, timezone
from typing import Optional

from dateutil import parser as date_parser

from .config import (
    ALLOWED_TOURNAMENT_TIERS,
    FIXTURES_LOOKAHEAD_DAYS,
    FLAG_ROUTINE,
    FLAG_UNCERTAIN,
    INDOOR_SURFACE_PREFIX,
    INJURY_SIGNAL_LOOKBACK_MATCHES,
    LOOKAHEAD_HOURS_MAX,
    LOOKAHEAD_HOURS_MIN,
    ODDS_API_TENNIS_SPORT_KEYS,
    RECENT_FORM_MATCHES,
    SERVE_RETURN_STATS_MATCHES,
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

    Importante: processamos os tournamentId por ordem decrescente de
    frequência (quantos jogos desse torneio aparecem hoje/amanhã) antes de
    gastar pedidos de info. Um ATP 250 como Umag tem uma dezena de jogos
    no mesmo dia; um Futures disperso tem 1-2. Isto garante que, se a
    quota diária (50/dia no plano free) se esgotar a meio, já resolvemos
    os torneios que realmente interessam antes dos Futures aleatórios.
    """
    from collections import Counter

    tournament_ids_in_order = [
        tid for tid, _ in Counter(m.get("tournamentId") for m in raw_matches if m.get("tournamentId")).most_common()
    ]

    tour_by_tournament_id = {}
    for match in raw_matches:
        tid = match.get("tournamentId")
        if tid is not None and tid not in tour_by_tournament_id:
            tour_by_tournament_id[tid] = match["_tour"]

    resolved_info = {}
    for tournament_id in tournament_ids_in_order:
        info = fetch_data.get_tournament_info(tournament_id, tour_by_tournament_id[tournament_id])
        if info is not None:
            resolved_info[tournament_id] = info

    eligible = []
    for match in raw_matches:
        tournament_id = match.get("tournamentId")
        info = resolved_info.get(tournament_id)
        if info is None:
            # sem info disponível (falha da API, sem cache, ou quota
            # esgotada antes de chegar a este torneio) — não arriscamos
            # incluir um Challenger/ITF por engano.
            continue

        tier = info.get("tier")
        if tier not in ALLOWED_TOURNAMENT_TIERS:
            continue

        match["tournament_name"] = info.get("name") or f"Torneio {tournament_id}"
        match["surface"] = info.get("surface") or "Desconhecido"
        match["tier"] = tier
        match["country"] = info.get("country")
        eligible.append(match)

    return eligible


def _deduplicate_matches(matches: list[dict]) -> list[dict]:
    """
    O matchstat pode devolver o mesmo jogo mais do que uma vez — confirmado
    na prática (27/07/2026) durante um torneio com dados a mudar em tempo
    real ao longo das várias páginas da paginação. Deduplicamos pelo
    campo 'id' do próprio matchstat (identificador único do jogo).
    """
    seen_ids = set()
    deduplicated = []
    for m in matches:
        match_id = m.get("id")
        if match_id is not None and match_id in seen_ids:
            continue
        if match_id is not None:
            seen_ids.add(match_id)
        deduplicated.append(m)

    removed = len(matches) - len(deduplicated)
    if removed > 0:
        print(f"[aviso] {removed} jogo(s) duplicado(s) removido(s) (mesmo id do matchstat repetido).")
    return deduplicated


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


def _get_weather_for_match(match: dict, start: datetime) -> Optional[dict]:
    """
    Só pede meteorologia para jogos ao ar livre. Geocodifica a partir do
    nome do torneio (a parte depois do último ' - ', que costuma ser a
    cidade) + país. Devolve None em qualquer falha — nunca inventa.
    """
    surface = match.get("surface", "")
    if surface.startswith(INDOOR_SURFACE_PREFIX):
        return None

    tournament_name = match.get("tournament_name", "")
    city = tournament_name.rsplit(" - ", 1)[-1] if " - " in tournament_name else tournament_name
    country = match.get("country") or ""
    place_query = f"{city}, {country}".strip(", ")

    coords = fetch_data.geocode_location(place_query)
    if coords is None:
        return None
    return fetch_data.get_weather_forecast(coords["lat"], coords["lon"], start)


def _enforce_minimum_flag(payload: dict, result: dict) -> dict:
    """
    Regra determinística, não deixada ao critério do Claude: se faltarem
    peças centrais (odds de mercado E H2H de carreira), o jogo nunca pode
    sair como 🟢 (sem sinais especiais) — no mínimo 🟡 (incerteza/dados
    incompletos). O Claude continua a decidir o texto e pode escolher 🔴
    por conta própria; isto só sobe o mínimo, nunca desce o que o modelo
    já tinha decidido.
    """
    missing_odds = payload.get("market_odds_decimal") is None
    missing_h2h = payload.get("h2h") is None

    if missing_odds and missing_h2h and result.get("flag") == FLAG_ROUTINE:
        result["flag"] = FLAG_UNCERTAIN
        result["summary_line"] = f"{result.get('summary_line', '')} (sem odds nem H2H — dados insuficientes para 🟢)"

    return result


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
    surface_a = fetch_data.compute_surface_stats(history, player_a)
    surface_b = fetch_data.compute_surface_stats(history, player_b)
    fatigue_a = fetch_data.compute_fatigue(history, player_a, start)
    fatigue_b = fetch_data.compute_fatigue(history, player_b, start)
    injury_a = fetch_data.compute_injury_signal(history, player_a, INJURY_SIGNAL_LOOKBACK_MATCHES)
    injury_b = fetch_data.compute_injury_signal(history, player_b, INJURY_SIGNAL_LOOKBACK_MATCHES)
    serve_a = fetch_data.compute_serve_return_stats(history, player_a, SERVE_RETURN_STATS_MATCHES)
    serve_b = fetch_data.compute_serve_return_stats(history, player_b, SERVE_RETURN_STATS_MATCHES)
    rank_a = fetch_data.get_player_ranking(history, player_a)
    rank_b = fetch_data.get_player_ranking(history, player_b)
    set1_comeback_a = fetch_data.compute_set1_comeback_stats(history, player_a)
    set1_comeback_b = fetch_data.compute_set1_comeback_stats(history, player_b)
    weather = _get_weather_for_match(match, start)

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
        "injury_signal_a": injury_a,  # baseado em RET/W-O reais, não é relatório médico
        "injury_signal_b": injury_b,
        "serve_return_stats_a": serve_a,
        "serve_return_stats_b": serve_b,
        "ranking_a": rank_a,
        "ranking_b": rank_b,
        "set1_comeback_stats_a": set1_comeback_a,  # para aplicares em live: taxa histórica de reviravolta após perder o 1º set
        "set1_comeback_stats_b": set1_comeback_b,
        "weather": weather,  # None para indoor ou se a geocodificação/previsão falhar
    }


def run() -> None:
    raw_matches = fetch_data.fetch_all_upcoming_fixtures(FIXTURES_LOOKAHEAD_DAYS)
    print(f"[info] {len(raw_matches)} jogo(s) devolvidos pelo matchstat antes da deduplicação.")
    raw_matches = _deduplicate_matches(raw_matches)
    print(f"[info] {len(raw_matches)} jogo(s) após deduplicação, antes de qualquer outro filtro.")

    windowed = _filter_matches_in_window(raw_matches)
    eligible = _filter_and_enrich_with_tournament_info(windowed)
    fetch_data.flush_tournament_cache()
    fetch_data.flush_fixtures_cache()

    if not eligible:
        print("[info] Sem jogos elegíveis nesta janela (fora do tier permitido ou fora de horas). Nada a enviar.")
        return

    analyses = []
    for match in eligible:
        payload = _build_match_payload(match)
        result = analyze_match(payload)
        result = _enforce_minimum_flag(payload, result)
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
    # A frase de cada jogo vem do Claude em texto livre — tem de ser
    # escapada antes de entrar numa mensagem com parse_mode=HTML, senão
    # um "<" ou "&" na frase parte a mensagem toda (erro 400 silencioso).
    summary_lines = [f"<b>🎾 Resumo Pré-Live — {today_str}</b>\n"]
    for payload, result in analyses:
        flag = html.escape(result.get("flag", ""))
        line = html.escape(result.get("summary_line", ""))
        summary_lines.append(f"{flag} {line}")
    summary_lines.append(f"\n📄 Relatório completo: {html.escape(telegraph_url)}")

    send_message("\n".join(summary_lines))
    print(f"[info] Enviado com sucesso. {len(analyses)} jogo(s). Relatório: {telegraph_url}")


if __name__ == "__main__":
    run()
