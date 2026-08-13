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
4. Enriquecer com Moneyline atual da RapidAPI Extend, por eventId.
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
    RECENT_FORM_MATCHES,
    SERVE_RETURN_STATS_MATCHES,
    SKIP_ANALYSIS_ODDS_THRESHOLD,
)
from . import fetch_data
from . import run_metrics
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


def _fontes_divergem(sack, rapid, tol_pct=15):
    """Compara o mesmo dado das duas fontes (Sackmann vs RapidAPI). Devolve
    True se divergem significativamente (win% difere mais que tol_pct pontos).
    Ambos no formato {wins, losses, matches}. Usado só para REGISTAR a
    discrepância — a decisão de qual usar é sempre RapidAPI."""
    def _pct(d):
        if not d or not d.get("matches"):
            return None
        return 100 * d["wins"] / d["matches"]
    pa, pb = _pct(sack), _pct(rapid)
    if pa is None or pb is None:
        return False  # falta uma fonte -> nada a comparar
    return abs(pa - pb) > tol_pct


def _fontes_divergem_serve(sack, rapid, tol_pct=10):
    """Compara o 1º serviço ganho entre Sackmann e RapidAPI."""
    if not sack or not rapid:
        return False
    sa = sack.get("avg_first_serve_won_pct")
    ra = rapid.get("avg_first_serve_won_pct")
    if sa is None or ra is None:
        return False
    # Sackmann pode estar em fração (0-1) ou %; normalizar
    if sa <= 1:
        sa *= 100
    return abs(sa - ra) > tol_pct


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
    # CORREÇÃO (12/08/2026, feedback de teste): também guardar os PONTOS de
    # ranking, não só a posição. #1 vs #5 é uma diferença de posição pequena
    # (4) mas de pontos enorme; #200 vs #204 tem a mesma diferença de posição
    # mas é irrelevante. Um limiar fixo de posições não distingue os dois
    # casos — os pontos sim.
    pa_pts = (payload.get("ranking_a") or {}).get("points")
    pb_pts = (payload.get("ranking_b") or {}).get("points")
    if ra and rb:
        feats["ranking"] = {"lider": a if ra < rb else (b if rb < ra else "igual"),
                            "diff": abs(ra - rb), "valor_a": ra, "valor_b": rb,
                            "pontos_a": pa_pts, "pontos_b": pb_pts}

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
        # CORREÇÃO (12/08/2026): `basic` (surface_stats_a/b) é um dicionário
        # POR PISO — {"Hard": {...}, "Clay": {...}, "Grass": {...}} — mas
        # ia inteiro para _pct(), que espera um dict PLANO {"matches",
        # "wins"}. _pct(basic) procurava "matches" na chave de topo (que
        # não existe ali, só existem os nomes dos pisos) e devolvia sempre
        # None. Ou seja: o fallback NUNCA funcionava — "piso" só tinha dados
        # quando a fonte "rica" (limitada por orçamento) estava disponível,
        # o que exclui a maioria dos jogadores fora do top do ranking.
        # Corrigido para extrair primeiro a célula do piso certo.
        basic_key = None
        if "clay" in s: basic_key = "Clay"
        elif "grass" in s: basic_key = "Grass"
        elif "hard" in s: basic_key = "Hard"
        basic_cell = (basic or {}).get(basic_key) if basic_key else None
        p = _pct(basic_cell)
        return p, (basic_cell or {}).get("matches")
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

    # H2H (quem lidera o confronto direto) — global E por piso, separados
    # (auditoria 11/08/2026: o "on_surface" já vinha calculado em compute_h2h
    # mas nunca era usado por ninguém — dado morto).
    h2h_obj = payload.get("h2h") or {}
    h2h = h2h_obj.get("overall") or {}
    if h2h.get("total_matches"):
        aw, bw = h2h.get("a_wins", 0), h2h.get("b_wins", 0)
        feats["h2h"] = {"lider": a if aw > bw else (b if bw > aw else "igual"),
                        "a_wins": aw, "b_wins": bw, "total": h2h["total_matches"]}
    h2h_surf = h2h_obj.get("on_surface") or {}
    if h2h_surf.get("total_matches"):
        aw_s, bw_s = h2h_surf.get("a_wins", 0), h2h_surf.get("b_wins", 0)
        feats["h2h_piso"] = {"lider": a if aw_s > bw_s else (b if bw_s > aw_s else "igual"),
                             "a_wins": aw_s, "b_wins": bw_s, "total": h2h_surf["total_matches"]}

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

    odds = fetch_data.fetch_rapidapi_moneyline(match)

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

    # Guardar os valores do Sackmann ANTES de a RapidAPI os sobrepor, para
    # comparar as duas fontes e registar discrepâncias. A RapidAPI ganha
    # sempre (paga, mais completa), mas queremos SABER quando divergem — é
    # sinal de que uma fonte anda a falhar (tipicamente o Sackmann).
    _sack = {
        "h2h": h2h, "forma": (form_a, form_b), "epoca": (season_a, season_b),
        "piso": (surface_a, surface_b),
    }
    _discrepancias = []  # lista de nomes de stats onde as fontes divergiram

    # Fonte RapidAPI para dados básicos em falta (WTA ou jogador ausente do histórico)
    _recent_a_cache = _recent_b_cache = None
    if _pid_a is not None and _pid_b is not None:
        # RapidAPI é agora a fonte PRINCIPAL de forma/época/piso (o Sackmann
        # anda partido e dava valores errados — ex: 20% quando o real era 40%).
        # Por isso buscamos SEMPRE que há player IDs, não só quando o Sackmann
        # falha. O Sackmann fica como fallback quando a RapidAPI não tem o dado.
        precisa_api = True
        if precisa_api:
            # H2H via API — RapidAPI é a fonte PRINCIPAL (mesmo motivo da
            # forma: o Sackmann partido pode dar H2H errados). Só fica o
            # Sackmann se a RapidAPI não devolver H2H.
            _h2h_matches = fetch_data.fetch_h2h_matches(tour, _pid_a, _pid_b)
            _h2h_api = fetch_data.compute_h2h_from_api(_h2h_matches, _pid_a, _pid_b, surface)
            if _h2h_api:
                h2h = _h2h_api
            # forma/época/piso via jogos recentes da API
            _recent_a_cache = fetch_data.fetch_player_recent_matches(tour, _pid_a)
            _recent_b_cache = fetch_data.fetch_player_recent_matches(tour, _pid_b)
            _fa = fetch_data.compute_form_from_recent(_recent_a_cache, _pid_a, start, RECENT_FORM_MATCHES, surface)
            _fb = fetch_data.compute_form_from_recent(_recent_b_cache, _pid_b, start, RECENT_FORM_MATCHES, surface)
            # PRIORIDADE À RAPIDAPI (fonte fiável). Só cai no valor anterior
            # (Sackmann) se a RapidAPI não tiver o dado. Antes era ao contrário
            # — e o Sackmann partido, por devolver valores errados mas não
            # vazios, ganhava sempre. Agora a RapidAPI manda.
            if _fa.get("form"): form_a = _fa["form"]
            if _fb.get("form"): form_b = _fb["form"]
            if _fa.get("season"): season_a = _fa["season"]
            if _fb.get("season"): season_b = _fb["season"]
            if _fa.get("surface"): surface_a = _fa["surface"]
            if _fb.get("surface"): surface_b = _fb["surface"]

            # COMPARAÇÃO DE FONTES: registar onde Sackmann e RapidAPI divergem
            # (a RapidAPI já ganhou acima; isto é só para SABER). Compara o
            # win% de cada stat/jogador; se diferir >15 p.p., regista.
            _sf_a, _sf_b = _sack["forma"]
            if _fontes_divergem(_sf_a, _fa.get("form")) or _fontes_divergem(_sf_b, _fb.get("form")):
                _discrepancias.append("forma recente")
            _ss_a, _ss_b = _sack["epoca"]
            if _fontes_divergem(_ss_a, _fa.get("season")) or _fontes_divergem(_ss_b, _fb.get("season")):
                _discrepancias.append("época atual")
            _sp_a, _sp_b = _sack["piso"]
            if _fontes_divergem(_sp_a, _fa.get("surface")) or _fontes_divergem(_sp_b, _fb.get("surface")):
                _discrepancias.append("desempenho no piso")
            # H2H: comparar total de jogos (se diferirem, as fontes divergem)
            _sh = _sack["h2h"]
            if _sh and _h2h_api:
                _st = (_sh.get("a_wins", 0) + _sh.get("b_wins", 0))
                _rt = (_h2h_api.get("a_wins", 0) + _h2h_api.get("b_wins", 0))
                if _st != _rt:
                    _discrepancias.append("confronto direto (H2H)")

            # LOG das discrepâncias (só aparece quando há divergência real):
            # avisa-te que o Sackmann e a RapidAPI não bateram certo neste jogo.
            # A RapidAPI foi usada (é a fiável); isto é só para monitorizares.
            if _discrepancias:
                print(f"[fontes] {player_a} vs {player_b} | "
                      f"Sackmann≠RapidAPI em: {', '.join(_discrepancias)} "
                      f"(usada a RapidAPI)")

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
    handedness_a = fetch_data.compute_handedness_matchup_stats(history, player_a, tour=tour)
    handedness_b = fetch_data.compute_handedness_matchup_stats(history, player_b, tour=tour)
    layoff_return_a = fetch_data.compute_return_from_layoff_stats(history, player_a)
    layoff_return_b = fetch_data.compute_return_from_layoff_stats(history, player_b)
    deciding_set_a = fetch_data.compute_deciding_set_stats(history, player_a)
    deciding_set_b = fetch_data.compute_deciding_set_stats(history, player_b)
    round_stage_a = fetch_data.compute_round_stage_stats(history, player_a)
    round_stage_b = fetch_data.compute_round_stage_stats(history, player_b)

    # ===== FASE 2: RapidAPI como fonte PRINCIPAL destas stats =====
    # (serviço, sets decisivos, mão, recuperação 1º set, lesão). O Sackmann
    # calculado acima fica como FALLBACK. Comparamos as fontes e registamos
    # divergências no log (a RapidAPI ganha sempre).
    if _pid_a is not None and _pid_b is not None:
        _rs_a = fetch_data.fetch_recent_stats(tour, _pid_a)
        _rs_b = fetch_data.fetch_recent_stats(tour, _pid_b)
        # -- Serviço/resposta --
        _srv_a = fetch_data.compute_serve_return_from_recent_stats(_rs_a) if _rs_a else None
        _srv_b = fetch_data.compute_serve_return_from_recent_stats(_rs_b) if _rs_b else None
        if _srv_a:
            if serve_a and _fontes_divergem_serve(serve_a, _srv_a):
                _discrepancias.append("serviço")
            serve_a = _srv_a
        if _srv_b:
            serve_b = _srv_b
        # -- Sets decisivos --
        _ds_a = fetch_data.compute_deciding_set_from_recent_stats(_rs_a) if _rs_a else None
        _ds_b = fetch_data.compute_deciding_set_from_recent_stats(_rs_b) if _rs_b else None
        if _ds_a:
            deciding_set_a = _ds_a
        if _ds_b:
            deciding_set_b = _ds_b
        # -- Recuperação de 1º set (past-matches, reaproveita cache) --
        _pm_a = _recent_a_cache if _recent_a_cache is not None else fetch_data.fetch_player_recent_matches(tour, _pid_a)
        _pm_b = _recent_b_cache if _recent_b_cache is not None else fetch_data.fetch_player_recent_matches(tour, _pid_b)
        _sc_a = fetch_data.compute_scenarios_from_past_matches(_pm_a, _pid_a) if _pm_a else None
        _sc_b = fetch_data.compute_scenarios_from_past_matches(_pm_b, _pid_b) if _pm_b else None
        if _sc_a:
            set1_comeback_a = _sc_a
        if _sc_b:
            set1_comeback_b = _sc_b
        # -- Regresso de lesão --
        _lay_a = fetch_data.compute_layoff_from_past_matches(_pm_a, _pid_a, start) if _pm_a else None
        _lay_b = fetch_data.compute_layoff_from_past_matches(_pm_b, _pid_b, start) if _pm_b else None
        if _lay_a:
            layoff_return_a = _lay_a
        if _lay_b:
            layoff_return_b = _lay_b
        # -- Matchup de mão (perfil por nome) --
        _prof_a = fetch_data.fetch_player_profile(player_a)
        _prof_b = fetch_data.fetch_player_profile(player_b)
        _hand_a = fetch_data.compute_hand_from_profile(_prof_a) if _prof_a else None
        _hand_b = fetch_data.compute_hand_from_profile(_prof_b) if _prof_b else None
        # DIAGNÓSTICO (13/08/2026, a pedido — matchup de mão "sem dados" em
        # alguns jogos WTA apesar do pré-aquecimento): há DOIS pontos onde
        # isto pode falhar — a mão de HOJE dos dois jogadores (_hand_a/_b,
        # perfil por nome) ou a reconstrução HISTÓRICA de cada um
        # (handedness_a/_b, calculada mais acima a partir do histórico +
        # cache). Esta linha diz qual dos dois, em vez de adivinhar.
        if not (_hand_a and _hand_b) or not (handedness_a and handedness_b):
            print(f"[diag:mao] {player_a} vs {player_b} | "
                  f"mão hoje: A={_hand_a!r} B={_hand_b!r} | "
                  f"reconstrução histórica: A={'OK' if handedness_a else 'None'} "
                  f"B={'OK' if handedness_b else 'None'}")
        # guardar as mãos no payload (o motor usa para o matchup)
        if _hand_a and _hand_b:
            payload_hands = {"a": _hand_a, "b": _hand_b}
            # CORREÇÃO (11/08/2026): resolver para a taxa de vitória
            # específica contra a mão REAL do adversário deste jogo — ver
            # resolve_handedness_matchup para o porquê (o motor lia uma
            # chave "win_pct" que nunca existia nos dados crus).
            handedness_a = fetch_data.resolve_handedness_matchup(handedness_a, _hand_b)
            handedness_b = fetch_data.resolve_handedness_matchup(handedness_b, _hand_a)
        else:
            payload_hands = None
            handedness_a = None
            handedness_b = None
        if _discrepancias and ("serviço" in _discrepancias):
            print(f"[fontes] {player_a} vs {player_b} | serviço divergiu Sackmann≠RapidAPI (usada RapidAPI)")
    else:
        payload_hands = None

    weather = _get_weather_for_match(match, start)

    payload = {
        "player_a": player_a,
        "player_b": player_b,
        "tournament": tournament,
        "tier": match["tier"],
        "surface": surface,
        "commence_time_utc": start.isoformat(),
        "market_odds_decimal": odds,  # None se a RapidAPI não tiver Moneyline para o evento
        "fontes_divergentes": _discrepancias,  # stats onde Sackmann≠RapidAPI (RapidAPI ganhou)
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
        "player_hands": payload_hands,  # {"a":"R","b":"L"} da RapidAPI (mão real)
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
        div = payload.get("divergencia") or {}
        level = (div.get("classificacao") or {}).get("nivel", -1)
        tour_key = html.escape(str(payload.get("_tour") or "").lower(), quote=True)
        cards.append(
            f'<a class="idx-card" href="{href}" data-level="{level}" data-tour="{tour_key}">'
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
.filters{{max-width:760px;margin:16px auto 0;display:grid;grid-template-columns:1fr 170px;gap:10px;}}
.filters input,.filters select{{background:{COLORS['surface']};color:{COLORS['text']};border:1px solid {COLORS['line']};border-radius:8px;padding:10px 12px;font:inherit;}}
.filters input:focus,.filters select:focus{{outline:2px solid {COLORS['steel']};outline-offset:1px;}}
.filter-status{{max-width:760px;margin:8px auto 0;color:{COLORS['text_dim']};font-size:13px;}}
.list{{max-width:760px;margin:20px auto;display:flex;flex-direction:column;gap:10px;}}
.idx-card{{display:flex;gap:12px;align-items:center;background:{COLORS['surface']};border:1px solid {COLORS['line']};border-radius:10px;padding:14px;text-decoration:none;color:inherit;transition:border-color .15s;}}
.idx-card:hover{{border-color:{COLORS['steel']};}}
.idx-flag{{font-size:20px;}}
.idx-players{{font-weight:700;font-size:16px;}} .idx-players span{{color:{COLORS['text_dim']};font-weight:400;font-size:13px;}}
.idx-tour{{color:{COLORS['text_dim']};font-size:12px;margin:2px 0 4px;text-transform:uppercase;letter-spacing:.05em;}}
.idx-line{{font-size:14px;color:{COLORS['text']};}}
@media(max-width:600px){{.filters{{grid-template-columns:1fr;}}.idx-card{{align-items:flex-start;}}}}
</style></head>
<body>
<div class="head"><h1>🎾 Relatórios Pré-Live</h1><p>{today_str} · {len([m for m in match_reports if m[2]])} jogos</p></div>
<div class="filters">
  <input id="search" type="search" placeholder="Pesquisar jogador ou torneio" aria-label="Pesquisar relatórios"/>
  <select id="priority" aria-label="Filtrar por prioridade">
    <option value="all">Todas as prioridades</option>
    <option value="3">Prioridade alta</option><option value="2">Valor a analisar</option>
    <option value="1">A acompanhar</option><option value="0">Sem divergência</option>
  </select>
</div>
<div class="filter-status" id="filter-status" aria-live="polite"></div>
<div class="list">{"".join(cards) if cards else "<p style='max-width:760px;margin:20px auto;color:#9aa3b2'>Sem jogos hoje.</p>"}</div>
<script>
const cards=[...document.querySelectorAll('.idx-card')];
const search=document.getElementById('search'), priority=document.getElementById('priority');
const status=document.getElementById('filter-status');
function applyFilters(){{
  const q=search.value.trim().toLocaleLowerCase('pt'); const level=priority.value;
  let visible=0;
  for(const card of cards){{
    const show=(!q||card.textContent.toLocaleLowerCase('pt').includes(q))&&(level==='all'||card.dataset.level===level);
    card.hidden=!show; if(show) visible++;
  }}
  status.textContent=`${{visible}} de ${{cards.length}} jogos visíveis`;
}}
search.addEventListener('input',applyFilters); priority.addEventListener('change',applyFilters); applyFilters();
</script>
</body></html>"""

    # o índice do dia e o índice-raiz (index.html na raiz do site)
    with open(os.path.join(reports_dir, f"index-{today_str}.html"), "w", encoding="utf-8") as f:
        f.write(index_html)
    with open(os.path.join(SITE_OUTPUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_html)


def run() -> None:
    run_metrics.reset()
    # O contador RapidAPI é opcional; versões anteriores de fetch_data.py podem não expor estas funções.
    reset_calls = getattr(fetch_data, "reset_rapidapi_call_count", None)
    if callable(reset_calls):
        reset_calls()
    else:
        print("[info] contador RapidAPI local não disponível em fetch_data.py; a execução continua.")
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

    # Preparar uma única vez o índice eventId da RapidAPI Extend.
    # Os fixtures normais usam o match ID principal; os endpoints de odds
    # usam o eventId da camada Extend. O índice evita uma chamada /event/get
    # por jogo e mantém o consumo de RapidAPI controlado.
    fetch_data.prepare_rapidapi_odds_index(eligible)

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

    # Nunca publicar um relatório parcial como se fosse uma execução normal
    # quando o circuit breaker de quota foi ativado.
    if fetch_data.rapidapi_budget_exceeded():
        raise RuntimeError(
            "Execução interrompida pelo orçamento RapidAPI; nenhum relatório "
            "parcial foi publicado. Consulta o contador nos logs."
        )

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

    # --- Resumo Telegram: prioridade visual + links clicáveis ---
    # Usa a mesma divergência calculada para o relatório HTML. Não faz
    # chamadas adicionais ao Claude.
    def _linha_telegram(payload, result):
        div = payload.get("divergencia") or {}
        clf = div.get("classificacao") or {}
        nivel = clf.get("nivel", -1)
        fav = div.get("favorecido")
        a = payload.get("player_a", "?")
        b = payload.get("player_b", "?")
        # As odds reais estão no payload (RapidAPI), não em div["market"].
        # div["market"] não é um campo obrigatório do motor de divergência e,
        # por isso, não pode ser usado para decidir se o jogo tem odds.
        odds = payload.get("market_odds_decimal") or {}
        numeric = {}
        try:
            for k, v in odds.items():
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    continue
                if fv > 1:
                    numeric[k] = fv
        except AttributeError:
            numeric = {}

        if not numeric:
            return (-1, "⚠️", f"{a} vs {b} — <b>SEM ODDS</b> · análise limitada")

        # Cores do Telegram = nível determinístico do Python (auditoria p.17):
        # 🟢 forte, 🟡 acompanhar, ⚪ sem sinal, ⚠️ sem odds/dados.
        bola = {3: "🟢", 2: "🟢", 1: "🟡", 0: "⚪"}.get(nivel, "⚪")

        tipo = div.get("tipo", "")
        # rótulo do lado (favorito/underdog) a partir das odds
        lado = "Moneyline"
        try:
            if fav in numeric and len(numeric) >= 2:
                favorite = min(numeric, key=numeric.get)
                lado = "Moneyline Favorito" if fav == favorite else "Moneyline Underdog"
        except Exception:
            pass

        _txt_motor = (clf.get("texto") or "").lower()
        if nivel >= 1 and fav:
            txt = f"{a} vs {b} — <b>{lado}: {_txt_motor}</b> a favor de {html.escape(str(fav))}"
        else:
            txt = f"{a} vs {b} — sem divergência relevante"
        return (nivel, bola, txt)

    # Construir e ordenar: fortes primeiro, sem odds no fim.
    linhas_dados = []
    for payload, result, url in match_reports:
        nivel, bola, txt = _linha_telegram(payload, result)
        linhas_dados.append((nivel, bola, txt, url))
    linhas_dados.sort(key=lambda x: x[0], reverse=True)

    n_high = sum(1 for n, _, _, _ in linhas_dados if n >= 3)
    n_value = sum(1 for n, _, _, _ in linhas_dados if n == 2)
    n_watch = sum(1 for n, _, _, _ in linhas_dados if n == 1)
    n_none = sum(1 for n, _, _, _ in linhas_dados if n == 0)
    n_no_odds = sum(1 for n, _, _, _ in linhas_dados if n < 0)

    cabecalho = (
        f"<b>🎾 Resumo Pré-Live — {today_str}</b>\n"
        f"🔴 {n_high} prioridade alta · 🟢 {n_value} valor a analisar · "
        f"🟡 {n_watch} acompanhar · ⚪ {n_none} sem edge"
    )
    if n_no_odds:
        cabecalho += f"\n⚠️ {n_no_odds} sem odds"
    cabecalho += "\n"
    summary_lines = [cabecalho]

    # Separadores tornam a lista muito mais legível sem repetir informação.
    previous_group = None
    group_names = {3: "🔴 PRIORIDADE ALTA", 2: "🟢 VALOR A ANALISAR",
                   1: "🟡 ACOMPANHAR", 0: "⚪ SEM PRIORIDADE", -1: "⚠️ SEM ODDS"}
    for nivel, bola, txt, url in linhas_dados:
        group = nivel if nivel in group_names else 0
        if group != previous_group:
            if previous_group is not None:
                summary_lines.append("")
            summary_lines.append(f"<b>{group_names[group]}</b>")
            previous_group = group
        summary_lines.append(f"{bola} {txt}")
        if url:
            safe_url = html.escape(url, quote=True)
            summary_lines.append(f'<a href="{safe_url}">📄 ABRIR RELATÓRIO</a>')
        else:
            summary_lines.append("⚠️ Relatório indisponível.")

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

    reports_ok = sum(1 for _, _, url in match_reports if url)
    print(
        "[run_summary] "
        f"eligible={len(eligible)} processed={len(analyses)} "
        f"analysis_failed={len(eligible) - len(analyses)} "
        f"reports_ok={reports_ok} reports_failed={len(match_reports) - reports_ok} "
        f"telegram_chunks={len(chunks)}"
    )

    # Registo do consumo da RapidAPI nesta execução (medição de quota).
    # Imprime o total no log e guarda o histórico dia a dia num ficheiro,
    # para se poder decidir com dados reais qual o plano necessário.
    try:
        get_calls = getattr(fetch_data, "get_rapidapi_call_count", None)
        n_calls = get_calls() if callable(get_calls) else None
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

    try:
        metrics = run_metrics.append_run(context={
            "eligible": len(eligible),
            "processed": len(analyses),
            "analysis_failed": len(eligible) - len(analyses),
            "reports_ok": reports_ok,
            "reports_failed": len(match_reports) - reports_ok,
            "telegram_chunks": len(chunks),
            "rapidapi_calls": fetch_data.get_rapidapi_call_count(),
        })
        print(f"[metrics] {json.dumps(metrics, ensure_ascii=False, sort_keys=True)}")
    except Exception as exc:
        print(f"[aviso] falha ao persistir métricas operacionais: {exc}")


if __name__ == "__main__":
    run()
