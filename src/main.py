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
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Optional

from dateutil import parser as date_parser

from .config import (
    ALLOWED_TOURNAMENT_TIERS,
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
from .report_html import build_report_html
from .telegram_bot import send_message
from .config import SITE_BASE_URL, SITE_OUTPUT_DIR, SITE_REPORTS_SUBDIR


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
    seen_ids: dict = {}
    deduplicated = []
    duplicate_examples = []

    for m in matches:
        match_id = m.get("id")
        if match_id is not None and match_id in seen_ids:
            duplicate_examples.append(
                f"id={match_id}, date_original={seen_ids[match_id]}, date_repetido={m.get('date')}"
            )
            continue
        if match_id is not None:
            seen_ids[match_id] = m.get("date")
        deduplicated.append(m)

    removed = len(matches) - len(deduplicated)
    if removed > 0:
        print(f"[aviso] {removed} jogo(s) duplicado(s) removido(s) (mesmo id do matchstat repetido).")
        print("[diagnóstico] primeiros 5 exemplos de duplicados (para perceber se vêm da mesma data ou de datas diferentes):")
        for example in duplicate_examples[:5]:
            print(f"  - {example}")
    return deduplicated


def _parse_utc(date_str: str) -> datetime:
    """
    B1 da auditoria (28/07/2026): se a API devolver uma data sem timezone,
    comparações com datetimes timezone-aware rebentam com TypeError.
    Assumimos UTC quando falta (as datas do matchstat vêm em UTC).
    """
    parsed = date_parser.isoparse(date_str)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _filter_matches_in_window(matches: list[dict]) -> list[dict]:
    now = datetime.now(timezone.utc)
    window_start = now + timedelta(hours=LOOKAHEAD_HOURS_MIN)
    window_end = now + timedelta(hours=LOOKAHEAD_HOURS_MAX)

    eligible = []
    for m in matches:
        try:
            start = _parse_utc(m["date"])
        except (KeyError, ValueError, TypeError):
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
    start = _parse_utc(match["date"])

    odds = fetch_data.find_market_odds(ODDS_API_TENNIS_SPORT_KEYS, player_a, player_b)

    # H2H rico via matchstat (independente do Sackmann) — só para WTA por
    # agora, decisão explícita (28/07/2026): o ATP já funciona bem com o
    # histórico da TennisMyLife/Sackmann, e isto usa a mesma quota
    # limitada (50/dia) da RapidAPI que já usamos para fixtures.
    h2h_rich_stats = None
    if tour == "wta":
        player1_id = match.get("player1Id")
        player2_id = match.get("player2Id")
        if player1_id is not None and player2_id is not None:
            h2h_rich_stats = fetch_data.fetch_h2h_stats(tour, player1_id, player2_id)

    h2h = fetch_data.compute_h2h(history, player_a, player_b, surface)
    form_a = fetch_data.compute_recent_form(history, player_a, RECENT_FORM_MATCHES)
    season_a = fetch_data.compute_current_season_record(history, player_a)
    season_b = fetch_data.compute_current_season_record(history, player_b)
    form_b = fetch_data.compute_recent_form(history, player_b, RECENT_FORM_MATCHES)
    surface_a = fetch_data.compute_surface_stats(history, player_a)
    surface_b = fetch_data.compute_surface_stats(history, player_b)
    fatigue_a = fetch_data.compute_fatigue(history, player_a, start)
    fatigue_b = fetch_data.compute_fatigue(history, player_b, start)
    injury_a = fetch_data.compute_injury_signal(history, player_a, INJURY_SIGNAL_LOOKBACK_MATCHES)
    injury_b = fetch_data.compute_injury_signal(history, player_b, INJURY_SIGNAL_LOOKBACK_MATCHES)
    serve_a = fetch_data.compute_serve_return_stats(history, player_a, SERVE_RETURN_STATS_MATCHES)
    serve_b = fetch_data.compute_serve_return_stats(history, player_b, SERVE_RETURN_STATS_MATCHES)
    # Ranking: preferir o oficial ao vivo (via matchstat, cache semanal),
    # que está sempre atualizado; cair para o derivado do histórico se o
    # jogador não estiver na lista oficial (ex: fora do ranking, ou nome
    # que não cruza). O oficial resolve o problema do ranking "as of"
    # desatualizado para quem não joga há semanas.
    official = fetch_data.fetch_official_ranking(tour)

    def _resolve_ranking(player_name: str):
        if official:
            key = fetch_data._normalize_name(player_name)
            if key in official:
                r = official[key]
                return {"rank": r["rank"], "points": r["points"], "as_of": "oficial (ao vivo)"}
        return fetch_data.get_player_ranking(history, player_name)

    rank_a = _resolve_ranking(player_a)
    rank_b = _resolve_ranking(player_b)
    set1_comeback_a = fetch_data.compute_set1_comeback_stats(history, player_a)
    set1_comeback_b = fetch_data.compute_set1_comeback_stats(history, player_b)
    handedness_a = fetch_data.compute_handedness_matchup_stats(history, player_a)
    handedness_b = fetch_data.compute_handedness_matchup_stats(history, player_b)
    layoff_return_a = fetch_data.compute_return_from_layoff_stats(history, player_a)
    layoff_return_b = fetch_data.compute_return_from_layoff_stats(history, player_b)
    deciding_set_a = fetch_data.compute_deciding_set_stats(history, player_a)
    deciding_set_b = fetch_data.compute_deciding_set_stats(history, player_b)
    round_stage_a = fetch_data.compute_round_stage_stats(history, player_a)
    round_stage_b = fetch_data.compute_round_stage_stats(history, player_b)
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
        "h2h_rich_stats": h2h_rich_stats,  # só WTA: stats de serviço/resposta/sets decisivos específicas deste confronto, via matchstat
        "recent_form_a": form_a,
        "current_season_a": season_a,  # jogos/vitórias esta época — distingue ativo de ex-campeão parado
        "current_season_b": season_b,
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
        "handedness_matchup_a": handedness_a,  # taxa vs canhotos/destros
        "handedness_matchup_b": handedness_b,
        "layoff_return_stats_a": layoff_return_a,  # desempenho no 1º jogo após paragem longa (60+ dias)
        "layoff_return_stats_b": layoff_return_b,
        "deciding_set_stats_a": deciding_set_a,  # taxa de vitória quando o jogo vai até ao set decisivo
        "deciding_set_stats_b": deciding_set_b,
        "round_stage_stats_a": round_stage_a,  # rondas iniciais vs finais
        "round_stage_stats_b": round_stage_b,
        "weather": weather,  # None para indoor ou se a geocodificação/previsão falhar
    }


def _slugify(text: str) -> str:
    """Nome de ficheiro seguro: sem acentos, minúsculas, só letras/números/hífen."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def _write_site_index(match_reports: list, today_str: str, reports_dir: str) -> None:
    """Página-índice simples (mesma estética escura) que lista os jogos do dia."""
    from .report_html import COLORS

    cards = []
    for payload, result, url in match_reports:
        if not url:
            continue
        flag = html.escape(result.get("flag", ""))
        a = html.escape(payload.get("player_a", "?"))
        b = html.escape(payload.get("player_b", "?"))
        tour = html.escape(payload.get("tournament", ""))
        line = html.escape(result.get("summary_line", ""))
        href = html.escape(url)
        cards.append(
            f'<a class="idx-card" href="{href}">'
            f'<div class="idx-flag">{flag}</div>'
            f'<div class="idx-body"><div class="idx-players">{a} <span>vs</span> {b}</div>'
            f'<div class="idx-tour">{tour}</div>'
            f'<div class="idx-line">{line}</div></div></a>'
        )

    index_html = f"""<!DOCTYPE html>
<html lang="pt"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Relatórios Pré-Live — {today_str}</title>
<style>
body{{background:{COLORS['bg']};color:{COLORS['text']};font-family:'Segoe UI',system-ui,sans-serif;margin:0;padding:0 16px 50px;}}
.head{{max-width:760px;margin:0 auto;padding:28px 0 10px;border-bottom:2px solid {COLORS['steel']};}}
.head h1{{font-size:22px;margin:0;}} .head p{{color:{COLORS['text_dim']};margin:6px 0 0;font-size:14px;}}
.list{{max-width:760px;margin:20px auto;display:flex;flex-direction:column;gap:10px;}}
.idx-card{{display:flex;gap:12px;align-items:center;background:{COLORS['surface']};border:1px solid {COLORS['line']};border-radius:10px;padding:14px;text-decoration:none;color:inherit;transition:border-color .15s;}}
.idx-card:hover{{border-color:{COLORS['steel']};}}
.idx-flag{{font-size:20px;}}
.idx-players{{font-weight:700;font-size:16px;}} .idx-players span{{color:{COLORS['text_dim']};font-weight:400;font-size:13px;}}
.idx-tour{{color:{COLORS['text_dim']};font-size:12px;margin:2px 0 4px;text-transform:uppercase;letter-spacing:.05em;}}
.idx-line{{font-size:14px;color:{COLORS['text']};}}
</style></head>
<body>
<div class="head"><h1>🎾 Relatórios Pré-Live</h1><p>{today_str} · {len([m for m in match_reports if m[2]])} jogos</p></div>
<div class="list">{"".join(cards) if cards else "<p style='max-width:760px;margin:20px auto;color:#9aa3b2'>Sem jogos hoje.</p>"}</div>
</body></html>"""

    # o índice do dia e o índice-raiz (index.html na raiz do site)
    with open(os.path.join(reports_dir, f"index-{today_str}.html"), "w", encoding="utf-8") as f:
        f.write(index_html)
    with open(os.path.join(SITE_OUTPUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_html)


def run() -> None:
    raw_matches = fetch_data.fetch_tracked_tournament_fixtures()
    print(f"[info] {len(raw_matches)} jogo(s) devolvidos pelos torneios seguidos, antes da deduplicação.")
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
        try:
            payload = _build_match_payload(match)
            result = analyze_match(payload)
            result = _enforce_minimum_flag(payload, result)
            analyses.append((payload, result))
        except Exception as exc:
            # Uma falha num jogo (ex: API da Anthropic sem créditos, erro
            # transitório de rede) não deve matar a execução inteira — os
            # jogos já analisados continuam a ser entregues, e este fica
            # registado no log para diagnóstico.
            p1 = (match.get("player1") or {}).get("name", "?")
            p2 = (match.get("player2") or {}).get("name", "?")
            print(f"[aviso] falha ao analisar {p1} vs {p2}: {exc}")

    if not analyses:
        # A3 da auditoria (28/07/2026): terminar "verde" sem qualquer
        # análise concluída esconderia uma falha total (ex: API da
        # Anthropic sem créditos). Alertamos e saímos com erro para o
        # GitHub Actions ficar vermelho e o alerta de falha disparar.
        error_msg = (
            f"⚠️ Tennis Bot: {len(eligible)} jogo(s) elegível(is), mas NENHUMA "
            "análise foi concluída — provável falha da API (créditos? rede?). "
            "Verifica os logs do GitHub Actions."
        )
        print(f"[erro] {error_msg}")
        try:
            send_message(error_msg)
        except Exception as exc:
            print(f"[aviso] também falhou o envio do alerta ao Telegram: {exc}")
        raise SystemExit(1)

    # --- Relatório completo: UMA página do Telegra.ph POR JOGO ---
    # (Antes era uma única página com todos os jogos — com muitos jogos
    # de uma vez (torneio inteiro), isso excede o limite de tamanho do
    # Telegra.ph e falha tudo com CONTENT_TOO_BIG. Páginas separadas por
    # jogo são sempre pequenas o suficiente, e nunca deixam um erro de
    # publicação de UM jogo impedir os restantes de serem entregues.)
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    reports_dir = os.path.join(SITE_OUTPUT_DIR, SITE_REPORTS_SUBDIR)
    os.makedirs(reports_dir, exist_ok=True)

    match_reports = []  # (payload, result, url_ou_None)
    generated_slugs = []
    for payload, result in analyses:
        # nome de ficheiro único e estável por jogo+dia
        slug = _slugify(f"{payload['player_a']}-vs-{payload['player_b']}-{today_str}")
        filename = f"{slug}.html"
        try:
            html_page = build_report_html(payload, result)
            with open(os.path.join(reports_dir, filename), "w", encoding="utf-8") as f:
                f.write(html_page)
            url = f"{SITE_BASE_URL}/{SITE_REPORTS_SUBDIR}/{filename}"
            generated_slugs.append((payload, result, slug))
        except Exception as exc:
            print(f"[aviso] falha a gerar HTML para {payload['player_a']} vs {payload['player_b']}: {exc}")
            url = None
        match_reports.append((payload, result, url))

    # Índice do dia: uma página que lista todos os jogos, para o Netlify
    # ter uma raiz navegável (e evitar o "Page not found").
    try:
        _write_site_index(match_reports, today_str, reports_dir)
    except Exception as exc:
        print(f"[aviso] falha a gerar índice do site: {exc}")

    # --- Resumo curto (Telegram) — um link por jogo ---
    # A frase de cada jogo vem do Claude em texto livre — tem de ser
    # escapada antes de entrar numa mensagem com parse_mode=HTML, senão
    # um "<" ou "&" na frase parte a mensagem toda (erro 400 silencioso).
    summary_lines = [f"<b>🎾 Resumo Pré-Live — {today_str}</b>\n"]
    for payload, result, url in match_reports:
        flag = html.escape(result.get("flag", ""))
        line = html.escape(result.get("summary_line", ""))
        summary_lines.append(f"{flag} {line}")
        if url:
            summary_lines.append(f"📄 {html.escape(url)}\n")
        else:
            summary_lines.append("⚠️ Relatório completo indisponível para este jogo.\n")

    # B3 da auditoria (28/07/2026): o Telegram limita mensagens a 4096
    # caracteres — com um torneio inteiro (20+ jogos com links), uma
    # mensagem única excede o limite e falha por completo. Dividimos em
    # blocos, quebrando apenas em fronteiras de linha.
    TELEGRAM_SAFE_LIMIT = 3900  # margem sob os 4096 oficiais
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in summary_lines:
        line_len = len(line) + 1  # +1 pelo \n
        if current and current_len + line_len > TELEGRAM_SAFE_LIMIT:
            chunks.append("\n".join(current))
            current, current_len = [], 0
        current.append(line)
        current_len += line_len
    if current:
        chunks.append("\n".join(current))

    for i, chunk in enumerate(chunks):
        prefix = f"(parte {i + 1}/{len(chunks)})\n" if len(chunks) > 1 and i > 0 else ""
        send_message(prefix + chunk)
    print(f"[info] Enviado com sucesso. {len(analyses)} jogo(s).")


if __name__ == "__main__":
    run()
