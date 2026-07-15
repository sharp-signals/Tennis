"""
Ponto de entrada do bot. Corre via `python -m src.main` (é isto que o
workflow do GitHub Actions invoca).

Fluxo:
1. Buscar jogos próximos (The Odds API) dentro da janela configurada.
2. Para cada jogo, juntar features do histórico (H2H, forma, piso, fadiga)
   a partir de múltiplas fontes gratuitas, com fallback entre elas.
3. Pedir ao Claude uma análise estruturada por jogo (JSON), só com dados reais.
4. Montar o resumo curto (1 linha + emoji por jogo) e o relatório completo.
5. Publicar o relatório completo no Telegra.ph.
6. Enviar o resumo curto para o Telegram, com link no fim para o Telegra.ph.

Se não houver jogos elegíveis nesta janela, o script termina sem enviar
nada — não faz sentido mandar uma mensagem vazia.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from dateutil import parser as date_parser

from .config import (
    ODDS_API_TENNIS_SPORT_KEYS,
    LOOKAHEAD_HOURS_MIN,
    LOOKAHEAD_HOURS_MAX,
    RECENT_FORM_MATCHES,
    FATIGUE_LOOKBACK_DAYS,
)
from . import fetch_data
from .analyze import analyze_match
from .telegraph import publish_report
from .telegram_bot import send_message


def _tour_from_sport_key(sport_key: str) -> str:
    return "wta" if "wta" in sport_key else "atp"


def _surface_guess(tournament_name: str) -> str:
    """
    A The Odds API não indica sempre o piso explicitamente. Aproximação
    simples por nome de torneio; sinaliza-se no relatório quando o piso
    não pôde ser confirmado por dados estruturados.
    """
    name = tournament_name.lower()
    if any(k in name for k in ["french open", "roland garros", "madrid", "rome", "monte carlo"]):
        return "Clay"
    if any(k in name for k in ["wimbledon", "queen", "halle"]):
        return "Grass"
    return "Hard"


def _filter_matches_in_window(matches: list[dict]) -> list[dict]:
    now = datetime.now(timezone.utc)
    window_start = now + timedelta(hours=LOOKAHEAD_HOURS_MIN)
    window_end = now + timedelta(hours=LOOKAHEAD_HOURS_MAX)

    eligible = []
    for m in matches:
        try:
            start = date_parser.isoparse(m["commence_time"])
        except (KeyError, ValueError):
            continue
        if window_start <= start <= window_end:
            eligible.append(m)
    return eligible


def _build_match_payload(match: dict) -> dict:
    tour = _tour_from_sport_key(match["_sport_key"])
    history = fetch_data.get_history(tour)

    player_a = match.get("home_team", "?")
    player_b = match.get("away_team", "?")
    tournament = match.get("sport_title", match["_sport_key"])
    surface = _surface_guess(tournament)
    start = date_parser.isoparse(match["commence_time"])

    odds = None
    bookmakers = match.get("bookmakers") or []
    if bookmakers:
        outcomes = bookmakers[0].get("markets", [{}])[0].get("outcomes", [])
        if outcomes:
            odds = {o["name"]: o["price"] for o in outcomes}

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
        "surface": surface,
        "surface_confirmed_by_data": False,  # aproximado por nome; ajusta se tiveres fonte melhor
        "commence_time_utc": start.isoformat(),
        "market_odds_decimal": odds,
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
    raw_matches = fetch_data.fetch_upcoming_matches(ODDS_API_TENNIS_SPORT_KEYS)
    eligible = _filter_matches_in_window(raw_matches)

    if not eligible:
        print("[info] Sem jogos elegíveis nesta janela. Nada a enviar.")
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
            f"({payload['tournament']}, {payload['surface']})\n\n"
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
