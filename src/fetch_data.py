"""
Recolha de dados a partir de várias fontes gratuitas/documentadas.

Filosofia (igual à do bot de futebol): nunca inventar. Se uma fonte falhar
ou não tiver o dado, a função devolve None / lista vazia e quem chama regista
isso como "dado em falta" — nunca preenche com um palpite.

Fontes usadas (todas gratuitas, todas documentadas — nada de scraping
não-oficial tipo Sofascore):

1. RapidAPI "Tennis API - ATP/WTA/ITF" (matchstat) -> fonte PRIMÁRIA de
   fixtures (que jogos existem) + info de torneio (tier/piso), com cache
   local para poupar pedidos (plano free = 50/dia).
2. The Odds API      -> fonte SECUNDÁRIA/opcional, só para odds de mercado
   quando o jogo também aparecer lá (por nomes dos jogadores). Nunca decide
   que jogos existem — isso sub-representava torneios menores (ex: Umag).
3. TennisMyLife       -> histórico ATP apenas (dataset "vivo", inclui
                          torneio da semana atual). Confirmado
                          (15/07/2026): é uma base de dados só de ATP, não
                          tem WTA — por isso o WTA vai direto ao Sackmann.
                          NOTA sobre licença: a documentação deles refere-se
                          como inspirada no tennis_atp do Sackmann (CC
                          BY-NC-SA — não comercial). Não confirmámos os
                          termos exatos de uso da própria TennisMyLife; para
                          uso pessoal como este projeto não é preocupação,
                          mas antes de qualquer uso comercial, ler os termos
                          deles diretamente em stats.tennismylife.org.
4. Jeff Sackmann GitHub -> histórico ATP (fallback) e WTA (fonte principal
                          para este tour). Licença CC BY-NC-SA.
5. tennis-data.co.uk  -> CSV semanal com resultados + odds + piso,
                          terceira fonte de cruzamento para stats por piso
"""

from __future__ import annotations

import difflib
import io
import json
import os
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
import requests

from .config import (
    FIXTURES_CACHE_MAX_AGE_HOURS,
    FIXTURES_CACHE_PATH,
    HISTORY_YEARS_TO_LOAD,
    MAX_FIXTURE_PAGES,
    RAPIDAPI_BASE,
    RAPIDAPI_HOST,
    SURFACES,
    TOURNAMENT_CACHE_PATH,
    TOURS_TO_FOLLOW,
)

ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
ODDS_API_BASE = "https://api.the-odds-api.com/v4"

RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "")
_RAPIDAPI_HEADERS = {
    "X-RapidAPI-Key": RAPIDAPI_KEY,
    "X-RapidAPI-Host": RAPIDAPI_HOST,
}

# Alguns servidores (raw.githubusercontent.com incluído, aparentemente)
# bloqueiam/disfarçam como 404 pedidos com o User-Agent genérico da lib
# requests. Um UA de browser normal resolve isto sem custo nenhum.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

TENNISMYLIFE_FILES_ENDPOINT = "https://stats.tennismylife.org/api/data-files"
# Usamos o jsDelivr (espelho gratuito de repositórios GitHub) em vez de
# raw.githubusercontent.com diretamente — descobrimos na prática (16/07/2026)
# que os runners do GitHub Actions apanhavam 404 consistente no raw.githubusercontent
# para estes repositórios específicos, mesmo com User-Agent de browser, o
# que sugere algum bloqueio a nível de IP/rede da própria GitHub. O jsDelivr
# serve o mesmo conteúdo sem esse problema.
SACKMANN_RAW_BASE = "https://cdn.jsdelivr.net/gh/JeffSackmann/tennis_atp@master"
SACKMANN_RAW_BASE_WTA = "https://cdn.jsdelivr.net/gh/JeffSackmann/tennis_wta@master"



REQUEST_TIMEOUT = 20


# --------------------------------------------------------------------- #
# 0. Odds de mercado (The Odds API) — fonte SECUNDÁRIA/opcional
# --------------------------------------------------------------------- #
_odds_api_cache: Optional[list[dict]] = None


def fetch_market_odds_snapshot(sport_keys: list[str]) -> list[dict]:
    """
    Junta as odds de todos os torneios "in season" na Odds API, uma única
    vez por execução (cacheado em memória). Usado depois só para tentar
    casar por nome de jogador — nunca para decidir que jogos existem.
    """
    global _odds_api_cache
    if _odds_api_cache is not None:
        return _odds_api_cache

    if not ODDS_API_KEY:
        print("[aviso] ODDS_API_KEY não definido — sem odds de mercado.")
        _odds_api_cache = []
        return _odds_api_cache

    all_matches = []
    for sport_key in sport_keys:
        url = f"{ODDS_API_BASE}/sports/{sport_key}/odds"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "eu",
            "markets": "h2h",
            "oddsFormat": "decimal",
        }
        try:
            resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 404:
                # torneio fora de época — normal, não é falha
                continue
            resp.raise_for_status()
            data = resp.json()
            for match in data:
                match["_sport_key"] = sport_key
            all_matches.extend(data)
        except requests.RequestException as exc:
            print(f"[aviso] falha a obter odds para {sport_key}: {exc}")
            continue

    _odds_api_cache = all_matches
    return _odds_api_cache


def find_market_odds(sport_keys: list[str], player_a: str, player_b: str) -> Optional[dict]:
    """
    Tenta casar um jogo (por nomes dos jogadores) com o snapshot da Odds
    API. Devolve None se não encontrar — o que é esperado e normal para
    torneios que a Odds API não cobre (ex: Umag).
    """
    snapshot = fetch_market_odds_snapshot(sport_keys)
    names = {player_a.lower(), player_b.lower()}
    for match in snapshot:
        match_names = {match.get("home_team", "").lower(), match.get("away_team", "").lower()}
        if names == match_names:
            bookmakers = match.get("bookmakers") or []
            if bookmakers:
                outcomes = bookmakers[0].get("markets", [{}])[0].get("outcomes", [])
                if outcomes:
                    return {o["name"]: o["price"] for o in outcomes}
    return None


# --------------------------------------------------------------------- #
# 2. Histórico / H2H / forma / piso (TennisMyLife, com fallback Sackmann)
# --------------------------------------------------------------------- #
_HISTORY_CACHE: dict[str, pd.DataFrame] = {}


def _load_tennismylife(tour: str) -> Optional[pd.DataFrame]:
    """
    A TennisMyLife é confirmadamente só ATP. Os jogos do QUADRO PRINCIPAL
    vêm em ficheiros simples por ano, ex: "2026.csv", SEM qualquer prefixo
    "atp" no nome (descoberto na prática — ver histórico do projeto).

    Carrega os últimos HISTORY_YEARS_TO_LOAD anos e junta tudo num único
    DataFrame, para o H2H cobrir a carreira inteira de um jogador, não só
    o ano corrente. Cada ano em falta é ignorado com aviso — não impede
    os restantes de carregar.

    Ficheiros a evitar mesmo que existam: "*_challenger.csv" (nível
    Challenger, não é o que seguimos), "atp_quali/*" (qualifying),
    "ATP_Database.csv" (não é histórico de jogos), "ongoing_tourneys.csv"
    / "challenger_ongoing_tourneys.csv" (formato diferente, não jogos).
    """
    if tour != "atp":
        return None  # confirmado: sem WTA nesta fonte

    try:
        resp = requests.get(TENNISMYLIFE_FILES_ENDPOINT, headers=_BROWSER_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        files = resp.json().get("files", [])
        by_name = {f.get("name"): f for f in files}
    except Exception as exc:
        print(f"[aviso] TennisMyLife (listagem de ficheiros) indisponível: {exc}")
        return None

    current_year = datetime.now(timezone.utc).year
    frames = []
    for offset in range(HISTORY_YEARS_TO_LOAD):
        year = current_year - offset
        name = f"{year}.csv"
        if name not in by_name:
            print(f"[aviso] TennisMyLife não tem ficheiro para o ano {year} — a saltar.")
            continue
        try:
            csv_resp = requests.get(by_name[name]["url"], headers=_BROWSER_HEADERS, timeout=REQUEST_TIMEOUT)
            csv_resp.raise_for_status()
            df_year = pd.read_csv(io.StringIO(csv_resp.text))
            frames.append(df_year)
        except Exception as exc:
            print(f"[aviso] falha a carregar TennisMyLife {name}: {exc}")

    if not frames:
        return None

    combined = pd.concat(frames, ignore_index=True)
    print(f"[info] TennisMyLife: {len(frames)}/{HISTORY_YEARS_TO_LOAD} anos carregados, {len(combined)} jogos no total.")
    return combined


def _load_sackmann(tour: str, year: int) -> Optional[pd.DataFrame]:
    """
    Fallback: ficheiro anual do repositório de Jeff Sackmann. Tenta o ano
    pedido e, se ainda não existir (ex: o ficheiro do ano corrente só é
    publicado a meio da época), tenta o ano anterior automaticamente.
    """
    base = SACKMANN_RAW_BASE if tour == "atp" else SACKMANN_RAW_BASE_WTA
    for candidate_year in (year, year - 1):
        url = f"{base}/{tour}_matches_{candidate_year}.csv"
        try:
            resp = requests.get(url, headers=_BROWSER_HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            print(f"[info] Sackmann {tour} carregado do ano {candidate_year}.")
            return pd.read_csv(io.StringIO(resp.text))
        except requests.RequestException as exc:
            print(f"[aviso] Sackmann indisponível para {tour} {candidate_year}: {exc}")
            continue
    return None


def _load_tennisdata_couk(tour: str, year: int) -> Optional[pd.DataFrame]:
    """
    Terceira fonte de cruzamento: ficheiro Excel (não CSV!) anual com
    resultados + odds + piso. Formato real confirmado (27/07/2026): o
    ATP fica em "{year}/{year}.xlsx" e o WTA em "{year}w/{year}.xlsx" —
    nada de "atp.csv"/"wta.csv" (isso era um palpite errado anterior).
    """
    folder = str(year) if tour == "atp" else f"{year}w"
    url = f"http://www.tennis-data.co.uk/{folder}/{year}.xlsx"
    try:
        resp = requests.get(url, headers=_BROWSER_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return pd.read_excel(io.BytesIO(resp.content))
    except Exception as exc:
        print(f"[aviso] tennis-data.co.uk indisponível para {tour} {year}: {exc}")
        return None


def get_history(tour: str) -> pd.DataFrame:
    """
    Devolve o histórico de jogos disponível para o tour ('atp'/'wta'),
    tentando as fontes por ordem até uma funcionar. Cacheia em memória
    durante a execução do script (o workflow corre e termina, por isso
    não há necessidade de cache persistente).
    """
    if tour in _HISTORY_CACHE:
        return _HISTORY_CACHE[tour]

    year = datetime.now(timezone.utc).year

    if tour == "atp":
        df = _load_tennismylife(tour)
        source = "tennismylife"
    else:
        # Confirmado (15/07/2026): a TennisMyLife é uma base de dados só
        # de ATP (mesmo nome do repositório: "ATP tournaments matches").
        # Nunca teve WTA — não vale a pena gastar um pedido a tentar.
        df = None
        source = None

    if df is None or df.empty:
        df = _load_sackmann(tour, year)
        source = "sackmann"
    if df is None or df.empty:
        df = _load_tennisdata_couk(tour, year)
        source = "tennisdata.co.uk"
    if df is None:
        print(f"[aviso] nenhuma fonte histórica disponível para {tour}.")
        df = pd.DataFrame()
        source = "nenhuma"

    print(f"[info] histórico {tour} carregado de: {source} ({len(df)} linhas)")
    if not df.empty:
        print(f"[info] colunas disponíveis: {list(df.columns)}")
    _HISTORY_CACHE[tour] = df
    return df


# --------------------------------------------------------------------- #
# 2b. Correspondência de nomes com tolerância (acentos, maiúsculas, e
#     pequenas variações de grafia entre o matchstat e o histórico)
# --------------------------------------------------------------------- #
_NAME_INDEX_CACHE: dict[int, dict[str, str]] = {}


def _normalize_name(name: str) -> str:
    if not name:
        return ""
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_name = "".join(c for c in nfkd if not unicodedata.combining(c))
    return ascii_name.lower().strip()


def _build_name_index(history: pd.DataFrame) -> dict[str, str]:
    """Índice nome_normalizado -> nome tal como aparece no histórico. Cacheado por dataframe."""
    key = id(history)
    if key in _NAME_INDEX_CACHE:
        return _NAME_INDEX_CACHE[key]

    names = set()
    if "winner_name" in history.columns:
        names.update(history["winner_name"].dropna().unique())
    if "loser_name" in history.columns:
        names.update(history["loser_name"].dropna().unique())

    index = {_normalize_name(n): n for n in names}
    _NAME_INDEX_CACHE[key] = index
    return index


def resolve_player_name(history: pd.DataFrame, name: str) -> Optional[str]:
    """
    Devolve o nome tal como aparece no histórico, tolerando acentos,
    maiúsculas/minúsculas diferentes, e pequenas variações de grafia
    (via correspondência aproximada). None se não houver nada suficiente-
    mente parecido — preferimos "sem dados" a arriscar juntar dois
    jogadores diferentes.
    """
    if history.empty:
        return None

    index = _build_name_index(history)
    normalized_input = _normalize_name(name)

    if normalized_input in index:
        return index[normalized_input]

    close = difflib.get_close_matches(normalized_input, index.keys(), n=1, cutoff=0.88)
    if close:
        return index[close[0]]

    return None


# --------------------------------------------------------------------- #
# 3. Features derivadas do histórico (H2H, forma, piso, fadiga)
# --------------------------------------------------------------------- #
def compute_h2h(history: pd.DataFrame, player_a: str, player_b: str, surface: Optional[str] = None) -> Optional[dict]:
    """
    Devolve {'overall': {...} ou None, 'on_surface': {...} ou None,
    'surface': str} — SEMPRE os dois números separados (carreira toda e
    específico do piso), nunca só um a substituir o outro, para o Claude
    poder comentar a diferença (ex: equilibrados na carreira, mas um
    domina claramente neste piso). None se não houver H2H nenhum.
    """
    if history.empty or "winner_name" not in history.columns:
        return None

    resolved_a = resolve_player_name(history, player_a)
    resolved_b = resolve_player_name(history, player_b)
    if resolved_a is None or resolved_b is None:
        return None
    player_a, player_b = resolved_a, resolved_b

    mask = (
        ((history["winner_name"] == player_a) & (history["loser_name"] == player_b))
        | ((history["winner_name"] == player_b) & (history["loser_name"] == player_a))
    )
    subset = history[mask]
    if subset.empty:
        return None

    def _tally(df: pd.DataFrame) -> dict:
        return {
            "a_wins": int((df["winner_name"] == player_a).sum()),
            "b_wins": int((df["winner_name"] == player_b).sum()),
            "total_matches": len(df),
        }

    overall = _tally(subset)

    on_surface = None
    if surface and "surface" in history.columns:
        subset_surface = subset[subset["surface"].str.lower() == surface.lower()]
        if not subset_surface.empty:
            on_surface = _tally(subset_surface)

    return {"overall": overall, "on_surface": on_surface, "surface": surface}


def compute_recent_form(history: pd.DataFrame, player: str, n_matches: int) -> Optional[dict]:
    """Últimos n_matches jogos do jogador (qualquer piso). None se não há dados."""
    if history.empty or "winner_name" not in history.columns:
        return None

    resolved = resolve_player_name(history, player)
    if resolved is None:
        return None
    player = resolved

    played = history[(history["winner_name"] == player) | (history["loser_name"] == player)]
    if played.empty:
        return None

    if "tourney_date" in played.columns:
        played = played.sort_values("tourney_date")
    played = played.tail(n_matches)

    wins = int((played["winner_name"] == player).sum())
    return {"matches": len(played), "wins": wins, "losses": len(played) - wins}


def compute_surface_stats(history: pd.DataFrame, player: str) -> Optional[dict]:
    """
    Devolve o perfil completo do jogador em CADA piso (Hard/Clay/Grass),
    não só no piso do jogo que está a ser analisado — para o Claude poder
    comparar especialização por piso (ex: muito forte em terra, fraco em
    relva). Cada piso vem com {'matches','wins','losses'} ou None se não
    houver jogos nesse piso.
    """
    if history.empty or "surface" not in history.columns:
        return None

    resolved = resolve_player_name(history, player)
    if resolved is None:
        return None
    player = resolved

    played = history[(history["winner_name"] == player) | (history["loser_name"] == player)]
    if played.empty:
        return None

    result: dict = {}
    for surface_name in SURFACES:
        subset = played[played["surface"].str.lower() == surface_name.lower()]
        if subset.empty:
            result[surface_name] = None
        else:
            wins = int((subset["winner_name"] == player).sum())
            result[surface_name] = {"matches": len(subset), "wins": wins, "losses": len(subset) - wins}

    return result


def compute_fatigue(history: pd.DataFrame, player: str, match_date: datetime) -> Optional[dict]:
    """
    Sinal de fadiga mais rico do que só "jogos nos últimos N dias":
    - dias desde o último jogo
    - jogos nos últimos 3, 7 e 14 dias
    - minutos jogados nos últimos 7 dias (quando a fonte tiver a coluna)
    - sets jogados nos últimos 7 dias (estimado a partir da coluna 'score')

    Continua a ser uma aproximação (não é o calendário exato do torneio),
    mas mais informativo do que a versão anterior. Campos individuais
    podem ficar None se a fonte não tiver a coluna correspondente.
    """
    if history.empty or "tourney_date" not in history.columns:
        return None

    resolved = resolve_player_name(history, player)
    if resolved is None:
        return None
    player = resolved

    played = history[(history["winner_name"] == player) | (history["loser_name"] == player)].copy()
    if played.empty:
        return None

    played["tourney_date"] = pd.to_datetime(played["tourney_date"], format="%Y%m%d", errors="coerce")

    # O histórico (tourney_date) é tz-naive; a data do jogo (match_date)
    # vem tz-aware (UTC) do matchstat. Normalizamos para tz-naive antes de
    # comparar, senão o pandas recusa a comparação.
    match_date_naive = pd.Timestamp(match_date)
    if match_date_naive.tzinfo is not None:
        match_date_naive = match_date_naive.tz_localize(None)

    past_matches = played[played["tourney_date"] < match_date_naive]

    days_since_last_match = None
    if not past_matches.empty:
        last_date = past_matches["tourney_date"].max()
        if pd.notna(last_date):
            days_since_last_match = int((match_date_naive - last_date).days)

    result: dict = {"days_since_last_match": days_since_last_match}

    for window_days in (3, 7, 14):
        window_start = match_date_naive - pd.Timedelta(days=window_days)
        subset = played[(played["tourney_date"] >= window_start) & (played["tourney_date"] < match_date_naive)]
        result[f"matches_last_{window_days}d"] = len(subset)

    # Minutos e sets jogados nos últimos 7 dias (só se a fonte tiver as colunas)
    window_7d_start = match_date_naive - pd.Timedelta(days=7)
    subset_7d = played[(played["tourney_date"] >= window_7d_start) & (played["tourney_date"] < match_date_naive)]

    minutes_played_7d = None
    if "minutes" in subset_7d.columns and not subset_7d.empty:
        valid_minutes = pd.to_numeric(subset_7d["minutes"], errors="coerce").dropna()
        if not valid_minutes.empty:
            minutes_played_7d = int(valid_minutes.sum())
    result["minutes_played_last_7d"] = minutes_played_7d

    def _count_sets(score) -> int:
        if not isinstance(score, str) or not score.strip():
            return 0
        return len([tok for tok in score.split() if "-" in tok and any(ch.isdigit() for ch in tok)])

    sets_played_7d = None
    if "score" in subset_7d.columns and not subset_7d.empty:
        sets_played_7d = int(subset_7d["score"].apply(_count_sets).sum())
    result["sets_played_last_7d"] = sets_played_7d

    return result


def _first_set_winner_is_match_winner(score) -> Optional[bool]:
    """
    Lê o primeiro set da coluna 'score' (ex: '6-4 3-6 6-2', sempre escrito
    da perspetiva de quem GANHOU o jogo). Devolve True se quem ganhou o
    jogo também ganhou o 1º set, False se perdeu o 1º set mas recuperou,
    None se não for possível interpretar (ex: 'W/O', formato inesperado).
    """
    if not isinstance(score, str) or not score.strip():
        return None
    first_set = score.strip().split()[0]
    first_set_clean = first_set.split("(")[0]  # remove tiebreak, ex: "7-6(4)" -> "7-6"
    parts = first_set_clean.split("-")
    if len(parts) != 2:
        return None
    try:
        winner_games, loser_games = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if winner_games == loser_games:
        return None
    return winner_games > loser_games


def compute_set1_comeback_stats(history: pd.DataFrame, player: str) -> Optional[dict]:
    """
    Entre os jogos em que o jogador PERDEU o 1º set, em quantos ainda
    assim ganhou o jogo? Separado por melhor-de-3 (Masters/500) e
    melhor-de-5 (Slams), porque a taxa de recuperação é estruturalmente
    diferente nos dois formatos. None se não houver dados suficientes.
    """
    required_cols = {"score", "best_of"}
    if history.empty or not required_cols.issubset(history.columns):
        return None

    resolved = resolve_player_name(history, player)
    if resolved is None:
        return None
    player = resolved

    played = history[(history["winner_name"] == player) | (history["loser_name"] == player)]
    if played.empty:
        return None

    result: dict = {}
    for best_of, label in ((3, "bo3"), (5, "bo5")):
        subset = played[played["best_of"] == best_of]
        lost_set1 = 0
        lost_set1_won_match = 0

        for _, row in subset.iterrows():
            set1_winner_is_match_winner = _first_set_winner_is_match_winner(row.get("score"))
            if set1_winner_is_match_winner is None:
                continue
            is_match_winner = row.get("winner_name") == player
            player_lost_set1 = (
                (is_match_winner and not set1_winner_is_match_winner)
                or (not is_match_winner and set1_winner_is_match_winner)
            )
            if player_lost_set1:
                lost_set1 += 1
                if is_match_winner:
                    lost_set1_won_match += 1

        if lost_set1 > 0:
            result[label] = {
                "matches_lost_set1": lost_set1,
                "matches_lost_set1_won_overall": lost_set1_won_match,
                "comeback_rate_pct": round(100 * lost_set1_won_match / lost_set1, 1),
            }
        else:
            result[label] = None

    if result.get("bo3") is None and result.get("bo5") is None:
        return None
    return result


def compute_injury_signal(history: pd.DataFrame, player: str, lookback_matches: int = 5) -> Optional[dict]:
    """
    Sinal aproximado de lesão a partir de desistências/walkovers reais nos
    últimos jogos do histórico (coluna 'score' costuma conter 'RET',
    'W/O' ou 'DEF' quando um jogo termina assim). Não é um relatório
    médico — é um facto verificável extraído dos próprios resultados.
    None se não houver dados suficientes para avaliar.
    """
    if history.empty or "score" not in history.columns or "tourney_date" not in history.columns:
        return None

    resolved = resolve_player_name(history, player)
    if resolved is None:
        return None
    player = resolved

    played = history[(history["winner_name"] == player) | (history["loser_name"] == player)].copy()
    if played.empty:
        return None

    played["tourney_date"] = pd.to_datetime(played["tourney_date"], format="%Y%m%d", errors="coerce")
    played = played.sort_values("tourney_date").tail(lookback_matches)

    markers = ("RET", "W/O", "WO", "DEF")
    retirements = []
    for _, row in played.iterrows():
        score = str(row.get("score", ""))
        if any(marker in score.upper() for marker in markers):
            # só conta como sinal de lesão do próprio jogador se ele foi
            # quem desistiu (perdeu esse jogo) — se ganhou por W/O do
            # adversário, o sinal de lesão é do outro jogador, não deste.
            if row.get("loser_name") == player:
                retirements.append({
                    "date": str(row.get("tourney_date")),
                    "opponent": row.get("winner_name"),
                    "score": score,
                })

    return {
        "matches_checked": len(played),
        "recent_retirements": retirements,  # lista vazia = nenhuma desistência encontrada
    }


def compute_serve_return_stats(history: pd.DataFrame, player: str, n_matches: int) -> Optional[dict]:
    """
    Médias de serviço/resposta nos últimos n_matches, agregadas a partir
    das colunas w_/l_ (que dependem de o jogador ter sido vencedor ou
    vencido em cada jogo). None se as colunas não existirem na fonte
    (ex: tennis-data.co.uk não tem estes detalhes) ou não houver jogos.
    """
    required_cols = {"w_ace", "w_df", "w_svpt", "w_1stIn", "w_1stWon", "w_2ndWon", "w_bpSaved", "w_bpFaced"}
    if history.empty or not required_cols.issubset(history.columns):
        return None

    resolved = resolve_player_name(history, player)
    if resolved is None:
        return None
    player = resolved

    played = history[(history["winner_name"] == player) | (history["loser_name"] == player)].copy()
    if played.empty:
        return None

    if "tourney_date" in played.columns:
        played["tourney_date"] = pd.to_datetime(played["tourney_date"], format="%Y%m%d", errors="coerce")
        played = played.sort_values("tourney_date")
    played = played.tail(n_matches)

    def _safe_float(value) -> Optional[float]:
        try:
            f = float(value)
            return None if pd.isna(f) else f
        except (ValueError, TypeError):
            return None

    def _safe_ratio(numerator_key: str, denominator_key: str, row) -> Optional[float]:
        num = _safe_float(row.get(numerator_key))
        den = _safe_float(row.get(denominator_key))
        if num is None or den is None or den <= 0:
            return None
        return num / den

    rows = []
    for _, row in played.iterrows():
        prefix = "w_" if row.get("winner_name") == player else "l_"
        svpt = _safe_float(row.get(f"{prefix}svpt"))
        if svpt is None or svpt <= 0:
            continue
        rows.append({
            "ace_pct": _safe_ratio(f"{prefix}ace", f"{prefix}svpt", row),
            "df_pct": _safe_ratio(f"{prefix}df", f"{prefix}svpt", row),
            "first_in_pct": _safe_ratio(f"{prefix}1stIn", f"{prefix}svpt", row),
            "first_won_pct": _safe_ratio(f"{prefix}1stWon", f"{prefix}1stIn", row),
            "bp_saved_pct": _safe_ratio(f"{prefix}bpSaved", f"{prefix}bpFaced", row),
        })

    if not rows:
        return None

    def _avg(key):
        values = [r[key] for r in rows if r[key] is not None]
        return round(sum(values) / len(values), 3) if values else None

    return {
        "matches_used": len(rows),
        "avg_ace_pct": _avg("ace_pct"),
        "avg_double_fault_pct": _avg("df_pct"),
        "avg_first_serve_in_pct": _avg("first_in_pct"),
        "avg_first_serve_won_pct": _avg("first_won_pct"),
        "avg_break_points_saved_pct": _avg("bp_saved_pct"),
    }


# --------------------------------------------------------------------- #
# 5. Rankings (derivado do próprio histórico de jogos, ver função abaixo)
# --------------------------------------------------------------------- #
def get_player_ranking(history: pd.DataFrame, player: str) -> Optional[dict]:
    """
    Devolve {'rank', 'points', 'as_of'} com o ranking do jogador no seu
    jogo mais recente do histórico (as colunas 'winner_rank'/'loser_rank'
    e '..._rank_points' já vêm em cada jogo da TennisMyLife — não depende
    do Sackmann, que está indisponível). None se não houver dados de
    ranking válidos no jogo mais recente encontrado.
    """
    required_cols = {"winner_rank", "loser_rank", "tourney_date"}
    if history.empty or not required_cols.issubset(history.columns):
        return None

    resolved = resolve_player_name(history, player)
    if resolved is None:
        return None
    player = resolved

    played = history[(history["winner_name"] == player) | (history["loser_name"] == player)].copy()
    if played.empty:
        return None

    played["tourney_date"] = pd.to_datetime(played["tourney_date"], format="%Y%m%d", errors="coerce")
    played = played.sort_values("tourney_date")
    latest = played.iloc[-1]

    is_winner = latest.get("winner_name") == player
    rank_col = "winner_rank" if is_winner else "loser_rank"
    points_col = "winner_rank_points" if is_winner else "loser_rank_points"

    rank_value = latest.get(rank_col)
    if pd.isna(rank_value):
        return None

    points_value = latest.get(points_col)
    return {
        "rank": int(rank_value),
        "points": int(points_value) if not pd.isna(points_value) else None,
        "as_of": str(latest.get("tourney_date")),
    }


# --------------------------------------------------------------------- #
# 6. Meteorologia (Open-Meteo — gratuita, documentada, sem key)
# --------------------------------------------------------------------- #
_GEOCODE_CACHE: dict = {}


def geocode_location(place_name: str) -> Optional[dict]:
    """
    Devolve {'lat', 'lon'} para um nome de cidade/torneio, ou None.
    Cacheado em memória durante a execução — vários jogos do mesmo
    torneio partilham a mesma cidade, não vale a pena repetir o pedido
    (e reduz o risco de timeout/rate-limit por pedidos repetidos seguidos).
    """
    if place_name in _GEOCODE_CACHE:
        return _GEOCODE_CACHE[place_name]

    url = "https://geocoding-api.open-meteo.com/v1/search"
    try:
        resp = requests.get(url, params={"name": place_name, "count": 1}, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        results = resp.json().get("results")
        coords = {"lat": results[0]["latitude"], "lon": results[0]["longitude"]} if results else None
        _GEOCODE_CACHE[place_name] = coords
        return coords
    except requests.RequestException as exc:
        print(f"[aviso] falha a geocodificar '{place_name}': {exc}")
        # não cacheamos falhas — pode ser um timeout pontual, vale a pena tentar outra vez no próximo jogo
        return None


_WEATHER_CACHE: dict = {}


def get_weather_forecast(lat: float, lon: float, match_date: "datetime") -> Optional[dict]:
    """
    Previsão para o dia do jogo (temperatura máx/mín, vento, precipitação).
    Só faz sentido para jogos ao ar livre — quem chama decide se pede isto
    consoante o piso ('I.hard' = indoor, não vale a pena pedir).
    Cacheado por (lat, lon, dia) — vários jogos no mesmo torneio/dia
    partilham a mesma previsão, não vale a pena repetir o pedido.
    """
    date_str = match_date.strftime("%Y-%m-%d")
    cache_key = (round(lat, 2), round(lon, 2), date_str)
    if cache_key in _WEATHER_CACHE:
        return _WEATHER_CACHE[cache_key]

    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,windspeed_10m_max",
        "timezone": "UTC",
        "start_date": date_str,
        "end_date": date_str,
    }
    for attempt in (1, 2):
        try:
            resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            daily = resp.json().get("daily")
            if not daily or not daily.get("time"):
                return None
            result = {
                "temp_max_c": daily["temperature_2m_max"][0],
                "temp_min_c": daily["temperature_2m_min"][0],
                "precipitation_mm": daily["precipitation_sum"][0],
                "wind_max_kmh": daily["windspeed_10m_max"][0],
            }
            _WEATHER_CACHE[cache_key] = result
            return result
        except (requests.RequestException, KeyError, IndexError) as exc:
            print(f"[aviso] falha a obter meteorologia, tentativa {attempt}: {exc}")
    return None


# --------------------------------------------------------------------- #
# 4. Fixtures (fonte primária): RapidAPI / matchstat
# --------------------------------------------------------------------- #
def _load_fixtures_cache() -> dict:
    if not os.path.exists(FIXTURES_CACHE_PATH):
        return {}
    try:
        with open(FIXTURES_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_fixtures_cache(cache: dict) -> None:
    os.makedirs(os.path.dirname(FIXTURES_CACHE_PATH), exist_ok=True)
    with open(FIXTURES_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2, sort_keys=True)


_fixtures_cache = _load_fixtures_cache()
_fixtures_cache_dirty = False


def fetch_date_fixtures(date: "datetime", tour: str) -> list[dict]:
    """
    Devolve os jogos agendados para um dia específico, para um tour
    ('atp' ou 'wta'). Lista vazia se a chave não estiver configurada ou
    se o pedido falhar — nunca levanta exceção para não parar o resto do
    pipeline por causa de um único dia sem dados.

    Usa cache local (data/fixtures_cache.json) por até
    FIXTURES_CACHE_MAX_AGE_HOURS horas, para não repetir o mesmo pedido
    nas duas execuções diárias (poupa quota do plano free, 50/dia).
    """
    global _fixtures_cache_dirty
    date_str = date.strftime("%Y-%m-%d")
    cache_key = f"{tour}:{date_str}"

    cached = _fixtures_cache.get(cache_key)
    if cached is not None:
        fetched_at = datetime.fromisoformat(cached["fetched_at"])
        age_hours = (datetime.now(timezone.utc) - fetched_at).total_seconds() / 3600
        if age_hours < FIXTURES_CACHE_MAX_AGE_HOURS:
            print(f"[info] fixtures {cache_key} vindas da cache local (idade: {age_hours:.1f}h).")
            return cached["data"]

    if not RAPIDAPI_KEY:
        print("[aviso] RAPIDAPI_KEY não definido — sem fixtures desta fonte.")
        return []

    url = f"{RAPIDAPI_BASE}/{tour}/fixtures/{date_str}"
    all_data: list[dict] = []
    pages_fetched = 0
    try:
        page = 1
        while True:
            params = {"page": page} if page > 1 else None
            resp = requests.get(url, headers=_RAPIDAPI_HEADERS, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            pages_fetched += 1
            payload = resp.json()
            page_data = payload.get("data", [])
            all_data.extend(page_data)

            if not payload.get("hasNextPage"):
                break
            page += 1
            if page > MAX_FIXTURE_PAGES:
                print(
                    f"[aviso] fixtures {cache_key}: atingido o limite de {MAX_FIXTURE_PAGES} páginas "
                    "(hasNextPage ainda true) — pode haver jogos por buscar, mas paramos para poupar quota."
                )
                break

        for match in all_data:
            match["_tour"] = tour

        _fixtures_cache[cache_key] = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "data": all_data,
        }
        _fixtures_cache_dirty = True
        if len(all_data) > 0:
            print(f"[info] fixtures {cache_key}: {len(all_data)} jogo(s) em {pages_fetched} pedido(s).")
        return all_data
    except requests.RequestException as exc:
        print(f"[aviso] falha a obter fixtures ({tour}, {date_str}): {exc}")
        return []


def flush_fixtures_cache() -> None:
    """Grava a cache de fixtures em disco só se algo mudou nesta execução."""
    if _fixtures_cache_dirty:
        _save_fixtures_cache(_fixtures_cache)
        print(f"[info] cache de fixtures atualizada ({len(_fixtures_cache)} entradas).")


def fetch_all_upcoming_fixtures(lookahead_days: int) -> list[dict]:
    """Junta fixtures dos tours configurados (TOURS_TO_FOLLOW) para os próximos `lookahead_days` dias (incl. hoje)."""
    all_matches = []
    today = datetime.now(timezone.utc)
    for offset in range(lookahead_days):
        day = today + timedelta(days=offset)
        for tour in TOURS_TO_FOLLOW:
            all_matches.extend(fetch_date_fixtures(day, tour))
    return all_matches


# --- Cache local de info de torneio (tier, piso, nome) ------------------
def _load_tournament_cache() -> dict:
    if not os.path.exists(TOURNAMENT_CACHE_PATH):
        return {}
    try:
        with open(TOURNAMENT_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_tournament_cache(cache: dict) -> None:
    os.makedirs(os.path.dirname(TOURNAMENT_CACHE_PATH), exist_ok=True)
    with open(TOURNAMENT_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2, sort_keys=True)


_tournament_cache = _load_tournament_cache()
_tournament_cache_dirty = False


def get_tournament_info(tournament_id: int, tour: str) -> Optional[dict]:
    """
    Devolve {'name', 'tier', 'surface'} para um tournamentId, usando cache
    local sempre que possível para poupar pedidos (plano free = 50/dia).
    None se o pedido falhar e não houver nada em cache.
    """
    global _tournament_cache_dirty
    key = str(tournament_id)
    if key in _tournament_cache:
        return _tournament_cache[key]

    if not RAPIDAPI_KEY:
        return None

    url = f"{RAPIDAPI_BASE}/{tour}/tournament/info/{tournament_id}"
    try:
        resp = requests.get(url, headers=_RAPIDAPI_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json().get("data", {})
        info = {
            "name": data.get("name"),
            "tier": data.get("tier"),
            "surface": (data.get("court") or {}).get("name"),
            "country": (data.get("country") or {}).get("name"),
        }
        _tournament_cache[key] = info
        _tournament_cache_dirty = True
        return info
    except requests.RequestException as exc:
        print(f"[aviso] falha a obter info do torneio {tournament_id}: {exc}")
        return None


def flush_tournament_cache() -> None:
    """Grava a cache em disco só se algo mudou nesta execução."""
    if _tournament_cache_dirty:
        _save_tournament_cache(_tournament_cache)
        print(f"[info] cache de torneios atualizada ({len(_tournament_cache)} torneios).")
