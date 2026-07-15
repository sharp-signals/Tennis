"""
Recolha de dados a partir de várias fontes gratuitas/documentadas.

Filosofia (igual à do bot de futebol): nunca inventar. Se uma fonte falhar
ou não tiver o dado, a função devolve None / lista vazia e quem chama regista
isso como "dado em falta" — nunca preenche com um palpite.

Fontes usadas (todas gratuitas, todas documentadas — nada de scraping
não-oficial tipo Sofascore):

1. The Odds API        -> fixtures (próximos jogos) + odds de mercado
2. TennisMyLife         -> histórico de resultados/rankings (MIT license,
                           dataset "vivo", inclui torneio da semana atual)
3. Jeff Sackmann GitHub -> histórico de resultados/rankings (CC BY-NC-SA,
                           usado como fonte de verificação cruzada / backup
                           se a TennisMyLife estiver em baixo)
4. tennis-data.co.uk    -> CSV semanal com resultados + odds + piso,
                           terceira fonte de cruzamento para stats por piso
"""

from __future__ import annotations

import io
import os
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import requests

ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
ODDS_API_BASE = "https://api.the-odds-api.com/v4"

TENNISMYLIFE_FILES_ENDPOINT = "https://stats.tennismylife.org/api/data-files"
SACKMANN_RAW_BASE = "https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master"
SACKMANN_RAW_BASE_WTA = "https://raw.githubusercontent.com/JeffSackmann/tennis_wta/master"

TENNISDATA_COUK_URL_TEMPLATE = "http://www.tennis-data.co.uk/{year}/{filename}"

REQUEST_TIMEOUT = 20


# --------------------------------------------------------------------- #
# 1. Fixtures + odds (The Odds API)
# --------------------------------------------------------------------- #
def fetch_upcoming_matches(sport_keys: list[str]) -> list[dict]:
    """
    Devolve uma lista de jogos próximos com odds, um dict por jogo.
    Cada torneio "fora de época" simplesmente não devolve nada — não é erro.
    """
    if not ODDS_API_KEY:
        print("[aviso] ODDS_API_KEY não definido — sem fixtures/odds desta fonte.")
        return []

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
            print(f"[aviso] falha a obter fixtures para {sport_key}: {exc}")
            continue

    return all_matches


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
