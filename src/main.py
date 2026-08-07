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
import json
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
    MATCH_PROCESSING_WORKERS,
    ODDS_API_TENNIS_SPORT_KEYS,
    RECENT_FORM_MATCHES,
    SERVE_RETURN_STATS_MATCHES,
    SKIP_ANALYSIS_ODDS_THRESHOLD,
)
from . import fetch_data
from .analyze import analyze_match
from .report_html import build_report_html, calcular_divergencia_publico
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


# Orçamento de buscas de dados ricos à RapidAPI por execução. Cada jogador
# novo (sem ficha) custa 2 pedidos (career + perf-breakdown). Limitamos o
# nº de jogadores novos buscados por execução para não rebentar a quota
# (erro 429) — os restantes usam só o histórico. Como as fichas ficam
# guardadas, ao longo dos dias todos acabam cobertos (construção incremental).
_RICH_FETCH_BUDGET = {"remaining": 200}  # praticamente sem limite: a proteção
# contra o 429 é agora a pausa entre pedidos (_rapidapi_get), não um teto rígido.
# Assim TODOS os jogos recebem dados ricos (antes só os primeiros 6). As fichas
# ficam em cache, por isso o custo de quota é temporário (só no 1º encontro).


def _get_rich_player_data(tour: str, player_name: str, official: Optional[dict]) -> Optional[dict]:
    """
    Devolve os dados ricos de um jogador (métricas de resposta de carreira
    + desempenho por nível de ranking do adversário), com estratégia
    HÍBRIDA para poupar quota:
      1. Se existir um JSON de dados guardado em knowledge/players/<slug>.json,
         lê de lá — sem custo de API.
      2. Senão, e se ainda houver orçamento de pedidos nesta execução, busca
         à RapidAPI e grava o JSON para reutilização futura.
      3. Se o orçamento acabou, devolve None (o relatório usa o histórico).
    """
    slug = _slugify(player_name)
    json_path = os.path.join("knowledge", "players", f"{slug}.json")

    # 1) tentar a ficha guardada
    try:
        if os.path.exists(json_path):
            with open(json_path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass

    # 2) orçamento esgotado? não força novos pedidos (evita o 429)
    if _RICH_FETCH_BUDGET["remaining"] <= 0:
        return None

    # 3) resolver ID e buscar à API
    player_id = fetch_data.get_player_id_from_ranking(tour, player_name)
    if not player_id:
        return None

    _RICH_FETCH_BUDGET["remaining"] -= 1  # consome orçamento (mesmo se falhar, evita insistir)
    career = fetch_data.fetch_player_career_stats(tour, player_id)
    perf = fetch_data.fetch_player_perf_breakdown(tour, player_id)
    if not career and not perf:
        return None

    # extrair os dados ricos das career stats (getH2HVsAllOppStats).
    # Nomes de campo confirmados contra a resposta real da API (31/07).
    stats = (career or {}).get("playerStats") or (career or {}).get("player1Stats") or (career or {})
    scenarios = {}      # cenários de jogo (1º set, decisivo, tiebreaks, Bo3/Bo5)
    response = {}       # métricas de resposta
    style = {}          # estilo de jogo (aces, winners, erros, rede, duração)
    if isinstance(stats, dict):
        # cenários (percentagens já calculadas pela API)
        for src, dst in (
            ("firstSetWinMatchWinPercentage", "first_set_win_then_win_pct"),
            ("firstSetLoseMatchWinPercentage", "first_set_lose_then_win_pct"),
            ("decidingSetWinPercentage", "deciding_set_win_pct"),
            ("totalTBWinPercentage", "tiebreak_win_pct"),
            ("bestOfThreeWonPercentage", "bo3_win_pct"),
            ("bestOfFiveWonPercentage", "bo5_win_pct"),
        ):
            if stats.get(src) is not None:
                scenarios[dst] = stats[src]
        # amostras (para o Claude saber a fiabilidade)
        scenarios["first_set_win_count"] = stats.get("firstSetWinCount")
        scenarios["first_set_lose_count"] = stats.get("firstSetLoseCount")
        scenarios["deciding_set_count"] = stats.get("decidingSetCount")
        scenarios["tiebreak_count"] = stats.get("tiebreakCount")

        # resposta
        for src, dst in (
            ("returnPtsWinPercentage", "return_pts_won_pct"),
            ("breakpointsWonPercentage", "break_points_converted_pct"),
        ):
            if stats.get(src) is not None:
                response[dst] = stats[src]

        # estilo de jogo
        style["aces"] = stats.get("aces")
        style["double_faults"] = stats.get("doubleFaults")
        style["winners"] = stats.get("winners")
        style["unforced_errors"] = stats.get("unforcedErrors")
        style["avg_time"] = stats.get("avgTime")
        na, nao = stats.get("netApproaches"), stats.get("netApproachesOf")
        if na is not None and nao:
            style["net_success_pct"] = round(100 * na / nao)
        style["matches_played"] = stats.get("statMatchesPlayed")

    # Frente 1: opponentStats — o que os ADVERSÁRIOS fazem contra este
    # jogador. Comparar com o playerStats diz se ele "domina" (ganha os
    # seus pontos) ou "beneficia de erros do outro". Campos confirmados no
    # JSON real (31/07).
    opp = (career or {}).get("opponentStats") or {}
    domination = {}
    if isinstance(opp, dict) and isinstance(stats, dict):
        # 1º serviço: quanto ELE ganha vs quanto os adversários ganham no 1º serviço deles
        if stats.get("winningOnFirstServePercentage") is not None and opp.get("winningOnFirstServePercentage") is not None:
            domination["own_first_serve_won_pct"] = stats["winningOnFirstServePercentage"]
            domination["opp_first_serve_won_pct"] = opp["winningOnFirstServePercentage"]
        # erros não forçados: dele vs dos adversários (quem erra mais)
        if stats.get("unforcedErrors") is not None and opp.get("unforcedErrors") is not None:
            domination["own_unforced_errors"] = stats["unforcedErrors"]
            domination["opp_unforced_errors"] = opp["unforcedErrors"]
        # winners: dele vs dos adversários (quem é mais agressivo/eficaz)
        if stats.get("winners") is not None and opp.get("winners") is not None:
            domination["own_winners"] = stats["winners"]
            domination["opp_winners"] = opp["winners"]

    rich = {
        "response_stats": response or None,
        "vs_rank_level": (perf or {}).get("vs_rank_level"),
        "by_surface": (perf or {}).get("by_surface"),
        "by_level": (perf or {}).get("by_level"),
        "scenarios": {k: v for k, v in scenarios.items() if v is not None} or None,
        "style": {k: v for k, v in style.items() if v is not None} or None,
        "domination": domination or None,
    }

    # gravar para reutilização (best-effort). Escrita ATÓMICA (tmp + rename)
    # para não corromper o ficheiro se duas threads escreverem em paralelo.
    try:
        os.makedirs(os.path.join("knowledge", "players"), exist_ok=True)
        tmp_path = f"{json_path}.{os.getpid()}.{id(rich)}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(rich, f, ensure_ascii=False)
        os.replace(tmp_path, json_path)  # rename atómico
    except Exception:
        pass

    return rich


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


def _compute_features(payload: dict) -> dict:
    """
    Pré-calcula SINAIS comparativos a partir dos dados brutos, para o Claude
    receber já digerido (compara vantagens, direções e sinais) e se concentrar
    na LEITURA DE MERCADO em vez de fazer aritmética. Não substitui a análise —
    dá-lhe o trabalho de comparação já feito. Cada feature indica quem lidera e
    a magnitude, com a amostra quando relevante. Campos None quando faltam dados.
    """
    a = payload.get("player_a", "A")
    b = payload.get("player_b", "B")
    feats = {}

    def _pct(d):
        if isinstance(d, dict) and d.get("matches"):
            return 100.0 * d["wins"] / d["matches"]
        return None

    def _edge(va, vb, nome, unidade="%", amostra_a=None, amostra_b=None):
        """Regista a vantagem (diferença) entre A e B numa métrica."""
        if va is None or vb is None:
            return
        diff = va - vb
        lider = a if diff > 0 else (b if diff < 0 else "igual")
        feats[nome] = {
            "lider": lider,
            "diff": round(abs(diff), 1),
            "unidade": unidade,
            "valor_a": round(va, 1),
            "valor_b": round(vb, 1),
        }
        if amostra_a is not None:
            feats[nome]["amostra_a"] = amostra_a
        if amostra_b is not None:
            feats[nome]["amostra_b"] = amostra_b

    # Ranking (menor = melhor)
    ra = (payload.get("ranking_a") or {}).get("rank")
    rb = (payload.get("ranking_b") or {}).get("rank")
    if ra and rb:
        feats["ranking"] = {"lider": a if ra < rb else (b if rb < ra else "igual"),
                            "diff": abs(ra - rb), "valor_a": ra, "valor_b": rb}

    # Forma recente (win%)
    _edge(_pct(payload.get("recent_form_a")), _pct(payload.get("recent_form_b")),
          "forma_recente",
          amostra_a=(payload.get("recent_form_a") or {}).get("matches"),
          amostra_b=(payload.get("recent_form_b") or {}).get("matches"))

    # Época atual (win%)
    _edge(_pct(payload.get("current_season_a")), _pct(payload.get("current_season_b")),
          "epoca_atual",
          amostra_a=(payload.get("current_season_a") or {}).get("matches"),
          amostra_b=(payload.get("current_season_b") or {}).get("matches"))

    # Piso (win%) — preferir o rico by_surface, senão surface_stats
    def _surf_pct(rich, basic, surface):
        bs = (rich or {}).get("by_surface") or {}
        skey = None
        s = (surface or "").lower()
        if "clay" in s: skey = "clay"
        elif "grass" in s: skey = "grass"
        elif "indoor" in s and "hard" in s: skey = "hard_indoor"
        elif "hard" in s: skey = "hard"
        cell = bs.get(skey) if skey else None
        if cell and cell.get("matches"):
            return cell["win_pct"], cell["matches"]
        p = _pct(basic)
        return p, (basic or {}).get("matches")
    surf = payload.get("surface")
    pa, na = _surf_pct(payload.get("rich_stats_a"), payload.get("surface_stats_a"), surf)
    pb, nb = _surf_pct(payload.get("rich_stats_b"), payload.get("surface_stats_b"), surf)
    _edge(pa, pb, "piso", amostra_a=na, amostra_b=nb)

    # Serviço (1º serviço ganho %) — do serve_return_stats
    sa = (payload.get("serve_return_stats_a") or {}).get("avg_first_serve_won_pct")
    sb = (payload.get("serve_return_stats_b") or {}).get("avg_first_serve_won_pct")
    if sa is not None and sb is not None:
        _edge(sa * 100 if sa <= 1 else sa, sb * 100 if sb <= 1 else sb, "servico")

    # Fadiga (menos jogos recentes = mais fresco) — sinal de frescura
    fa = payload.get("fatigue_signal_a") or {}
    fb = payload.get("fatigue_signal_b") or {}
    if fa.get("matches_last_7d") is not None and fb.get("matches_last_7d") is not None:
        ma, mb = fa["matches_last_7d"], fb["matches_last_7d"]
        feats["frescura"] = {
            "mais_fresco": a if ma < mb else (b if mb < ma else "igual"),
            "jogos_7d_a": ma, "jogos_7d_b": mb,
            "sets_7d_a": fa.get("sets_last_7d"), "sets_7d_b": fb.get("sets_last_7d"),
        }

    # H2H (quem lidera o confronto direto)
    h2h = (payload.get("h2h") or {}).get("overall") or {}
    if h2h.get("total_matches"):
        aw, bw = h2h.get("a_wins", 0), h2h.get("b_wins", 0)
        feats["h2h"] = {"lider": a if aw > bw else (b if bw > aw else "igual"),
                        "a_wins": aw, "b_wins": bw, "total": h2h["total_matches"]}

    return feats or None


def _factual_key_points(payload: dict) -> list:
    """
    Gera os PONTOS-CHAVE FACTUAIS a partir das features pré-calculadas — o
    trabalho que antes o Claude fazia a escrever ("A é #6", "lidera o H2H").
    Passa a ser gerado pelo Python (opção B): o Claude deixa de gastar tokens
    a narrar factos e concentra-se na leitura de mercado. Devolve uma lista de
    frases curtas e factuais, na "voz" do bot.
    """
    f = payload.get("features") or {}
    a = payload.get("player_a", "A")
    b = payload.get("player_b", "B")
    pts = []

    # Ranking
    rk = f.get("ranking")
    if rk and rk.get("lider") != "igual":
        pts.append(f"**{rk['lider']}** superior no ranking (#{rk['valor_a']} vs #{rk['valor_b']}).")

    # Força geral: contar quantas dimensões correlacionadas cada um lidera
    dims = ["forma_recente", "epoca_atual", "piso", "servico"]
    lideres = [f[d]["lider"] for d in dims if f.get(d) and f[d].get("lider") not in (None, "igual")]
    if lideres:
        from collections import Counter
        cont = Counter(lideres)
        dominante, n = cont.most_common(1)[0]
        if n >= 2:
            quais = []
            nomes = {"forma_recente": "forma", "epoca_atual": "época", "piso": "piso", "servico": "serviço"}
            for d in dims:
                if f.get(d) and f[d].get("lider") == dominante:
                    quais.append(nomes[d])
            pts.append(f"**{dominante}** melhor em {', '.join(quais)} (força geral a favor).")

    # H2H
    h = f.get("h2h")
    if h and h.get("lider") != "igual":
        pts.append(f"**{h['lider']}** lidera o confronto direto ({h['a_wins']}-{h['b_wins']} em {h['total']}).")

    # Frescura
    fr = f.get("frescura")
    if fr and fr.get("mais_fresco") != "igual":
        pts.append(f"**{fr['mais_fresco']}** mais fresco ({fr['jogos_7d_a']} vs {fr['jogos_7d_b']} jogos nos últimos 7 dias).")

    # Recuperação após 1º set (dado rico com valor de trading)
    ra = (payload.get("rich_stats_a") or {}).get("scenarios") or {}
    rb = (payload.get("rich_stats_b") or {}).get("scenarios") or {}
    if ra.get("first_set_win_then_win_pct") is not None:
        pts.append(f"{a} fecha {ra['first_set_win_then_win_pct']}% dos jogos após ganhar o 1º set.")
    if rb.get("first_set_lose_then_win_pct") is not None:
        pts.append(f"{b} recupera {rb['first_set_lose_then_win_pct']}% quando perde o 1º set.")

    return pts[:6]  # limite


def _factual_only_result(payload: dict) -> dict:
    """
    Resultado para jogos que NÃO passam pelo Claude (superfavoritos <=1.09).
    Só factos (do Python), sem leitura de mercado. Flag verde (rotina).
    """
    a = payload.get("player_a", "A")
    b = payload.get("player_b", "B")
    return {
        "flag": FLAG_ROUTINE,
        "signal_strength": 0,
        "confidence_reason": "Superfavorito (odd ≤1.09): sem valor de mercado a observar; análise saltada.",
        "summary_line": f"{a} vs {b}: superfavorito claro, sem mercado de valor.",
        "key_points": _factual_key_points(payload),
        "discrepancies": [],
        "risks": [],
        "verdict": "Superfavorito a odd muito baixa — sem valor de aposta a observar. Jogo incluído para registo, sem leitura de mercado.",
        "_no_llm": True,
    }


def _build_match_payload(match: dict) -> dict:
    tour = match["_tour"]
    history = fetch_data.get_history(tour)

    player_a = (match.get("player1") or {}).get("name", "?")
    player_b = (match.get("player2") or {}).get("name", "?")
    tournament = match["tournament_name"]
    surface = match["surface"]
    start = _parse_utc(match["date"])

    odds = fetch_data.find_market_odds(ODDS_API_TENNIS_SPORT_KEYS, player_a, player_b)

    _pid_a = match.get("player1Id")
    _pid_b = match.get("player2Id")
    _tournament_id = match.get("tournamentId") or match.get("tournament_id")

    # H2H rico via matchstat (stats de serviço/resposta específicas do confronto)
    h2h_rich_stats = None
    if tour == "wta" and _pid_a is not None and _pid_b is not None:
        h2h_rich_stats = fetch_data.fetch_h2h_stats(tour, _pid_a, _pid_b)

    # Dados básicos: do histórico (ATP, via TennisMyLife). Para WTA — ou
    # sempre que o histórico não tiver o jogador — usamos a RapidAPI, que
    # cobre ambos os tours e não depende do Sackmann (que anda partido p/ WTA).
    h2h = fetch_data.compute_h2h(history, player_a, player_b, surface)
    form_a = fetch_data.compute_recent_form(history, player_a, RECENT_FORM_MATCHES)
    form_b = fetch_data.compute_recent_form(history, player_b, RECENT_FORM_MATCHES)
    season_a = fetch_data.compute_current_season_record(history, player_a)
    season_b = fetch_data.compute_current_season_record(history, player_b)
    surface_a = fetch_data.compute_surface_stats(history, player_a)
    surface_b = fetch_data.compute_surface_stats(history, player_b)

    # Fonte RapidAPI para dados básicos em falta (WTA ou jogador ausente do histórico)
    _recent_a_cache = _recent_b_cache = None
    if _pid_a is not None and _pid_b is not None:
        precisa_api = (tour == "wta") or not h2h or not form_a or not form_b
        if precisa_api:
            # H2H via API
            if not h2h:
                _h2h_matches = fetch_data.fetch_h2h_matches(tour, _pid_a, _pid_b)
                _h2h_api = fetch_data.compute_h2h_from_api(_h2h_matches, _pid_a, _pid_b, surface)
                if _h2h_api:
                    h2h = _h2h_api
            # forma/época/piso via jogos recentes da API
            _recent_a_cache = fetch_data.fetch_player_recent_matches(tour, _pid_a)
            _recent_b_cache = fetch_data.fetch_player_recent_matches(tour, _pid_b)
            _fa = fetch_data.compute_form_from_recent(_recent_a_cache, _pid_a, start, RECENT_FORM_MATCHES, surface)
            _fb = fetch_data.compute_form_from_recent(_recent_b_cache, _pid_b, start, RECENT_FORM_MATCHES, surface)
            if not form_a and _fa.get("form"): form_a = _fa["form"]
            if not form_b and _fb.get("form"): form_b = _fb["form"]
            if not season_a and _fa.get("season"): season_a = _fa["season"]
            if not season_b and _fb.get("season"): season_b = _fb["season"]
            if not surface_a and _fa.get("surface"): surface_a = _fa["surface"]
            if not surface_b and _fb.get("surface"): surface_b = _fb["surface"]

    # Fadiga: fonte REAL (jogos recentes da API, inclui torneio em curso),
    # com fallback para o histórico. Reaproveita os jogos recentes já buscados.
    fatigue_a = fetch_data.compute_fatigue(history, player_a, start)  # fallback base
    fatigue_b = fetch_data.compute_fatigue(history, player_b, start)
    if _pid_a is not None:
        _recent_a = _recent_a_cache if _recent_a_cache is not None else fetch_data.fetch_player_recent_matches(tour, _pid_a)
        _fa = fetch_data.compute_fatigue_from_recent(_recent_a, _pid_a, start, _tournament_id)
        if _fa:
            fatigue_a = _fa
    if _pid_b is not None:
        _recent_b = _recent_b_cache if _recent_b_cache is not None else fetch_data.fetch_player_recent_matches(tour, _pid_b)
        _fb = fetch_data.compute_fatigue_from_recent(_recent_b, _pid_b, start, _tournament_id)
        if _fb:
            fatigue_b = _fb
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

    # Onda 2 (dados ricos por jogador): desempenho vs qualidade do
    # adversário (perf-breakdown) + métricas de resposta de carreira
    # (h2h-vs-all). Estratégia HÍBRIDA: primeiro tenta ler da ficha
    # guardada em knowledge/players/ (grátis); só se não existir é que
    # busca à RapidAPI (gasta quota). À medida que as fichas do top 100
    # forem construídas, o custo tende a zero.
    rich_a = _get_rich_player_data(tour, player_a, official)
    rich_b = _get_rich_player_data(tour, player_b, official)

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

    payload = {
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
        "rich_stats_a": rich_a,  # Onda 2: resposta de carreira + desempenho vs nível do adversário (ficha ou API)
        "rich_stats_b": rich_b,
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
    # Frente 4/5: pré-calcular sinais comparativos (o bot compara, o Claude
    # interpreta). Adiciona 'features' com quem lidera cada dimensão e a
    # magnitude — o Claude recebe as comparações prontas.
    payload["features"] = _compute_features(payload)
    # Motor de divergência V3: calcula UMA vez aqui e partilha via payload
    # com o analyze (Claude escreve alinhado) e o report_html (mostra o mesmo).
    # Fonte única de verdade — bola, veredicto e Model vs Market coerentes.
    try:
        payload["divergencia"] = calcular_divergencia_publico(payload)
    except Exception:
        payload["divergencia"] = None
    return payload


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
    fetch_data.reset_rapidapi_call_count()  # zerar o contador de chamadas desta execução
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

    # Processar os jogos em PARALELO (resolve a lentidão: antes era um loop
    # sequencial que com muitos jogos chegava a ~30 min). Poucos workers para
    # não sobrecarregar a API — a pausa anti-429 no _rapidapi_get serializa
    # o espaçamento entre threads. A ordem final é reposta a seguir.
    from concurrent.futures import ThreadPoolExecutor

    def _process_one(match):
        try:
            payload = _build_match_payload(match)
            # Saltar a análise do Claude para SUPERFAVORITOS (odd <= 1.09):
            # a esse preço não há valor de mercado a observar, por isso gastar
            # tokens do Claude não se justifica. O jogo continua a sair no
            # relatório (com todos os dados factuais do Python), apenas sem a
            # leitura de mercado — que não faria sentido a 1.09.
            odds = payload.get("market_odds_decimal") or {}
            odds_vals = [v for v in odds.values() if isinstance(v, (int, float)) and v > 1]
            if odds_vals and min(odds_vals) <= SKIP_ANALYSIS_ODDS_THRESHOLD:
                result = _factual_only_result(payload)
                return (payload, result)
            result = analyze_match(payload)
            result = _enforce_minimum_flag(payload, result)
            # Opção B: os pontos-chave factuais são gerados pelo BOT (não pelo
            # Claude, que já não os escreve). Injetamos aqui a partir das features.
            result["key_points"] = _factual_key_points(payload)
            return (payload, result)
        except Exception as exc:
            p1 = (match.get("player1") or {}).get("name", "?")
            p2 = (match.get("player2") or {}).get("name", "?")
            print(f"[aviso] falha ao analisar {p1} vs {p2}: {exc}")
            return None

    analyses = []
    with ThreadPoolExecutor(max_workers=MATCH_PROCESSING_WORKERS) as executor:
        for res in executor.map(_process_one, eligible):
            if res is not None:
                analyses.append(res)

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

    # O GitHub Pages usa Jekyll por omissão, que ignora ficheiros/pastas
    # com certos nomes. Um .nojekyll vazio desativa isso e garante que
    # todas as páginas HTML são servidas tal como estão.
    try:
        open(os.path.join(SITE_OUTPUT_DIR, ".nojekyll"), "w").close()
    except Exception:
        pass

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

    # Registo do consumo da RapidAPI nesta execução (medição de quota).
    # Imprime o total no log e guarda o histórico dia a dia num ficheiro,
    # para se poder decidir com dados reais qual o plano necessário.
    try:
        n_calls = fetch_data.get_rapidapi_call_count()
        print(f"[rapidapi_usage] Total desta execução: {n_calls} chamadas ({len(analyses)} jogo(s)).")

        usage_path = os.path.join("data", "rapidapi_usage_log.json")
        history = []
        try:
            if os.path.exists(usage_path):
                with open(usage_path, "r", encoding="utf-8") as f:
                    history = json.load(f)
        except Exception:
            history = []

        history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "calls": n_calls,
            "matches": len(analyses),
        })
        # média das últimas execuções do mesmo dia (informativo)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        today_calls = sum(e["calls"] for e in history if e["timestamp"].startswith(today))
        print(f"[rapidapi_usage] Acumulado hoje ({today}): {today_calls} chamadas.")

        try:
            os.makedirs("data", exist_ok=True)
            with open(usage_path, "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    except Exception as exc:
        print(f"[aviso] falha ao registar uso da RapidAPI: {exc}")


if __name__ == "__main__":
    run()
