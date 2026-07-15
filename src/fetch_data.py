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
3. TennisMyLife       -> histórico de resultados/rankings (MIT license,
                          dataset "vivo", inclui torneio da semana atual)
4. Jeff Sackmann GitHub -> histórico de resultados/rankings (CC BY-NC-SA,
                          usado como fonte de verificação cruzada / backup
                          se a TennisMyLife estiver em baixo)
5. tennis-data.co.uk  -> CSV semanal com resultados + odds + piso,
                          terceira fonte de cruzamento para stats por piso
"""

from __future__ import annotations

import io
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
import requests

from .config import (
    RAPIDAPI_BASE,
    RAPIDAPI_HOST,
    TOURNAMENT_CACHE_PATH,
)

ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
ODDS_API_BASE = "https://api.the-odds-api.com/v4"

RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "")
_RAPIDAPI_HEADERS = {
    "X-RapidAPI-Key": RAPIDAPI_KEY,
    "X-RapidAPI-Host": RAPIDAPI_HOST,
}

TENNISMYLIFE_FILES_ENDPOINT = "https://stats.tennismylife.org/api/data-files"
SACKMANN_RAW_BASE = "https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master"
SACKMANN_RAW_BASE_WTA = "https://raw.githubusercontent.com/JeffSackmann/tennis_wta/master"

TENNISDATA_COUK_URL_TEMPLATE = "http://www.tennis-data.co.uk/{year}/{filename}"

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
    """tour: 'atp' ou 'wta'. Descarrega o CSV mais recente disponível."""
    try:
        resp = requests.get(TENNISMYLIFE_FILES_ENDPOINT, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        files = resp.json().get("files", [])
        candidates = [
            f for f in files
            if tour in f.get("name", "").lower() and f.get("name", "").endswith(".csv")
        ]
        if not candidates:
            return None
        # assume o mais recente por nome (normalmente inclui o ano)
        candidates.sort(key=lambda f: f["name"])
        latest = candidates[-1]
        csv_resp = requests.get(latest["url"], timeout=REQUEST_TIMEOUT)
        csv_resp.raise_for_status()
        return pd.read_csv(io.StringIO(csv_resp.text))
    except Exception as exc:
        print(f"[aviso] TennisMyLife indisponível para {tour}: {exc}")
        return None


def _load_sackmann(tour: str, year: int) -> Optional[pd.DataFrame]:
    """Fallback: ficheiro anual do repositório de Jeff Sackmann."""
    base = SACKMANN_RAW_BASE if tour == "atp" else SACKMANN_RAW_BASE_WTA
    url = f"{base}/{tour}_matches_{year}.csv"
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return pd.read_csv(io.StringIO(resp.text))
    except Exception as exc:
        print(f"[aviso] Sackmann indisponível para {tour} {year}: {exc}")
        return None


def _load_tennisdata_couk(tour: str, year: int) -> Optional[pd.DataFrame]:
    """Terceira fonte de cruzamento: CSV semanal com odds + piso."""
    filename = "atp.csv" if tour == "atp" else "wta.csv"
    url = TENNISDATA_COUK_URL_TEMPLATE.format(year=year, filename=filename)
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return pd.read_csv(io.StringIO(resp.text), encoding="latin1")
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

    df = _load_tennismylife(tour)
    source = "tennismylife"
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
    _HISTORY_CACHE[tour] = df
    return df


# --------------------------------------------------------------------- #
# 3. Features derivadas do histórico (H2H, forma, piso, fadiga)
# --------------------------------------------------------------------- #
def compute_h2h(history: pd.DataFrame, player_a: str, player_b: str, surface: Optional[str] = None) -> Optional[dict]:
    """Devolve {'a_wins': int, 'b_wins': int, 'surface_filtered': bool} ou None se não há dados."""
    if history.empty or "winner_name" not in history.columns:
        return None

    mask = (
        ((history["winner_name"] == player_a) & (history["loser_name"] == player_b))
        | ((history["winner_name"] == player_b) & (history["loser_name"] == player_a))
    )
    subset = history[mask]
    surface_filtered = False
    if surface and "surface" in history.columns:
        subset_surface = subset[subset["surface"].str.lower() == surface.lower()]
        if not subset_surface.empty:
            subset = subset_surface
            surface_filtered = True

    if subset.empty:
        return None

    a_wins = int((subset["winner_name"] == player_a).sum())
    b_wins = int((subset["winner_name"] == player_b).sum())
    return {"a_wins": a_wins, "b_wins": b_wins, "surface_filtered": surface_filtered}


def compute_recent_form(history: pd.DataFrame, player: str, n_matches: int) -> Optional[dict]:
    """Últimos n_matches jogos do jogador (qualquer piso). None se não há dados."""
    if history.empty or "winner_name" not in history.columns:
        return None

    played = history[(history["winner_name"] == player) | (history["loser_name"] == player)]
    if played.empty:
        return None

    if "tourney_date" in played.columns:
        played = played.sort_values("tourney_date")
    played = played.tail(n_matches)

    wins = int((played["winner_name"] == player).sum())
    return {"matches": len(played), "wins": wins, "losses": len(played) - wins}


def compute_surface_stats(history: pd.DataFrame, player: str, surface: str) -> Optional[dict]:
    if history.empty or "surface" not in history.columns:
        return None

    played = history[
        ((history["winner_name"] == player) | (history["loser_name"] == player))
        & (history["surface"].str.lower() == surface.lower())
    ]
    if played.empty:
        return None

    wins = int((played["winner_name"] == player).sum())
    return {"matches": len(played), "wins": wins, "losses": len(played) - wins}


def compute_fatigue(history: pd.DataFrame, player: str, match_date: datetime, lookback_days: int) -> Optional[dict]:
    """
    Sinal aproximado de fadiga: quantos jogos o jogador disputou nos
    últimos `lookback_days` antes da data do jogo. Não é uma métrica
    oficial de "dias consecutivos" (isso exigiria o calendário completo
    do torneio) — é uma aproximação honesta a partir do que temos.
    """
    if history.empty or "tourney_date" not in history.columns:
        return None

    played = history[(history["winner_name"] == player) | (history["loser_name"] == player)].copy()
    if played.empty:
        return None

    played["tourney_date"] = pd.to_datetime(played["tourney_date"], format="%Y%m%d", errors="coerce")
    window_start = match_date - pd.Timedelta(days=lookback_days)
    recent = played[(played["tourney_date"] >= window_start) & (played["tourney_date"] < match_date)]

    return {"matches_last_n_days": len(recent), "lookback_days": lookback_days}


# --------------------------------------------------------------------- #
# 4. Fixtures (fonte primária): RapidAPI / matchstat
# --------------------------------------------------------------------- #
def fetch_date_fixtures(date: "datetime", tour: str) -> list[dict]:
    """
    Devolve os jogos agendados para um dia específico, para um tour
    ('atp' ou 'wta'). Lista vazia se a chave não estiver configurada ou
    se o pedido falhar — nunca levanta exceção para não parar o resto do
    pipeline por causa de um único dia sem dados.
    """
    if not RAPIDAPI_KEY:
        print("[aviso] RAPIDAPI_KEY não definido — sem fixtures desta fonte.")
        return []

    url = f"{RAPIDAPI_BASE}/{tour}/fixtures/{date.strftime('%Y-%m-%d')}"
    try:
        resp = requests.get(url, headers=_RAPIDAPI_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        for match in data:
            match["_tour"] = tour
        return data
    except requests.RequestException as exc:
        print(f"[aviso] falha a obter fixtures ({tour}, {date.strftime('%Y-%m-%d')}): {exc}")
        return []


def fetch_all_upcoming_fixtures(lookahead_days: int) -> list[dict]:
    """Junta fixtures de ATP e WTA para os próximos `lookahead_days` dias (incl. hoje)."""
    all_matches = []
    today = datetime.now(timezone.utc)
    for offset in range(lookahead_days):
        day = today + timedelta(days=offset)
        for tour in ("atp", "wta"):
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
