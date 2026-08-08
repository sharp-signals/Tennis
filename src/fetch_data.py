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
import threading
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
import requests

from .cache_store import JsonCacheStore
from .config import (
    FIXTURES_CACHE_MAX_AGE_HOURS,
    FIXTURES_CACHE_PATH,
    HISTORY_YEARS_TO_LOAD,
    MAX_FIXTURE_PAGES,
    RAPIDAPI_BASE,
    RAPIDAPI_HOST,
    SURFACES,
    TOURNAMENT_CACHE_PATH,
    TOURNAMENT_FIXTURES_PAGE_SIZE,
    TOURS_TO_FOLLOW,
    TRACKED_TOURNAMENT_IDS,
)

_PLAYER_CACHE_STORE = JsonCacheStore("data/cache")


def _player_cache_path(tour: str, player_id: int):
    return _PLAYER_CACHE_STORE.entity_path(
        "players",
        str(tour).strip().lower(),
        f"{int(player_id)}.json",
    )


def _read_player_cache_entry(
    tour: str,
    player_id: int,
    entry_name: str,
    max_age_hours: float,
):
    try:
        return _PLAYER_CACHE_STORE.get_entry(
            _player_cache_path(tour, player_id),
            entry_name,
            max_age_hours=max_age_hours,
        )
    except (OSError, TypeError, ValueError):
        return None


def _write_player_cache_entry(
    tour: str,
    player_id: int,
    entry_name: str,
    data,
) -> None:
    if data is None:
        return
    try:
        _PLAYER_CACHE_STORE.set_entry(
            _player_cache_path(tour, player_id),
            entry_name,
            data,
            metadata={
                "tour": str(tour).strip().lower(),
                "player_id": int(player_id),
            },
        )
    except (OSError, TypeError, ValueError):
        pass


ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
ODDS_API_BASE = "https://api.the-odds-api.com/v4"

RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "")
_RAPIDAPI_HEADERS = {
    "X-RapidAPI-Key": RAPIDAPI_KEY,
    "X-RapidAPI-Host": RAPIDAPI_HOST,
}

# Contador de chamadas à RapidAPI por execução.
_RAPIDAPI_CALL_COUNT = {"n": 0}
RAPIDAPI_MIN_INTERVAL = 0.35
_RAPIDAPI_LAST_CALL = {"t": 0.0}
_RAPIDAPI_LOCK = threading.Lock()


def _rapidapi_get(url, **kwargs):
    """Wrapper único para chamadas GET à RapidAPI, com contador, anti-429 e retry."""
    import time
    with _RAPIDAPI_LOCK:
        elapsed = time.monotonic() - _RAPIDAPI_LAST_CALL["t"]
        if elapsed < RAPIDAPI_MIN_INTERVAL:
            time.sleep(RAPIDAPI_MIN_INTERVAL - elapsed)
        _RAPIDAPI_LAST_CALL["t"] = time.monotonic()

    _RAPIDAPI_CALL_COUNT["n"] += 1
    for tentativa in range(3):
        resp = requests.get(url, headers=_RAPIDAPI_HEADERS, timeout=REQUEST_TIMEOUT, **kwargs)
        if resp.status_code == 429:
            espera = 2 * (tentativa + 1)
            print(f"[aviso] RapidAPI 429 (rate limit) — a aguardar {espera}s e a repetir...")
            time.sleep(espera)
            continue
        return resp
    return resp


def get_rapidapi_call_count() -> int:
    return _RAPIDAPI_CALL_COUNT["n"]


def reset_rapidapi_call_count() -> None:
    _RAPIDAPI_CALL_COUNT["n"] = 0


_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

TENNISMYLIFE_FILES_ENDPOINT = "https://stats.tennismylife.org/api/data-files"
SACKMANN_SOURCES_ATP = [
    "https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master",
    "https://cdn.jsdelivr.net/gh/JeffSackmann/tennis_atp@master",
]
SACKMANN_SOURCES_WTA = [
    "https://raw.githubusercontent.com/JeffSackmann/tennis_wta/master",
    "https://cdn.jsdelivr.net/gh/JeffSackmann/tennis_wta@master",
]
SACKMANN_RAW_BASE = SACKMANN_SOURCES_ATP[0]
SACKMANN_RAW_BASE_WTA = SACKMANN_SOURCES_WTA[0]

REQUEST_TIMEOUT = 20

RAPIDAPI_EXTEND_BASE = f"{RAPIDAPI_BASE}/extend/api"

# Índice de eventos da camada Extend da RapidAPI.
# As fixtures normais usam o ID principal do jogo (match ID), enquanto os
# endpoints de odds usam o eventId da camada Extend. O índice faz a ponte
# entre os dois sem ter de chamar /event/get individualmente para cada jogo.
_RAPIDAPI_EVENT_INDEX: dict[str, dict] = {}
_RAPIDAPI_EVENT_INDEX_READY: set[str] = set()
_RAPIDAPI_ODDS_CACHE: dict[str, Optional[dict]] = {}


def _event_match_key(player1_id, player2_id, tournament_id, round_id=None):
    if player1_id is None or player2_id is None or tournament_id is None:
        return None
    parts = [str(player1_id), str(player2_id), str(tournament_id)]
    if round_id is not None:
        parts.append(str(round_id))
    return "-".join(parts)


def _event_names_key(player1: str, player2: str) -> tuple[str, str]:
    return tuple(sorted((_normalize_name(player1), _normalize_name(player2))))


def _fetch_extend_upcoming_events(tour: str) -> list[dict]:
    """
    Carrega os eventos upcoming da camada Extend para obter o eventId que
    os endpoints de odds exigem. Faz paginação completa e só é chamado uma
    vez por tour nesta execução.
    """
    if not RAPIDAPI_KEY:
        return []

    events: list[dict] = []
    page = 1
    while True:
        url = f"{RAPIDAPI_EXTEND_BASE}/events/upcoming/{tour}"
        try:
            resp = _rapidapi_get(url, params={"page": page, "limit": 100})
            resp.raise_for_status()
            payload = resp.json() or {}
            page_results = payload.get("results") or []
            events.extend(e for e in page_results if isinstance(e, dict) and e.get("id"))
            pagination = payload.get("pagination") or {}
            if not pagination.get("hasNext"):
                break
            page += 1
            if page > MAX_FIXTURE_PAGES:
                print(f"[aviso] eventos upcoming {tour}: limite de {MAX_FIXTURE_PAGES} páginas atingido.")
                break
        except requests.RequestException as exc:
            print(f"[aviso] falha a obter eventos upcoming {tour} para odds: {exc}")
            break
    return events


def prepare_rapidapi_odds_index(matches: list[dict]) -> None:
    """
    Prepara, uma vez por execução, a correspondência entre cada fixture e o
    eventId da camada Extend. Isto evita uma chamada /event/get por jogo.
    """
    global _RAPIDAPI_EVENT_INDEX_READY

    tours = {m.get("_tour") for m in matches if m.get("_tour")}
    for tour in tours:
        if tour in _RAPIDAPI_EVENT_INDEX_READY:
            continue

        events = _fetch_extend_upcoming_events(tour)
        exact: dict[str, str] = {}
        names_dates: list[tuple[tuple[str, str], int, str]] = []

        for event in events:
            event_id = str(event.get("id"))
            match_id = str(event.get("matchId") or "")
            if match_id:
                exact[match_id] = event_id

            ts = event.get("startTimestamp")
            try:
                ts_int = int(ts) if ts is not None else 0
            except (TypeError, ValueError):
                ts_int = 0
            p1 = event.get("participant1") or ""
            p2 = event.get("participant2") or ""
            if p1 and p2:
                names_dates.append((_event_names_key(p1, p2), ts_int, event_id))

        for match in matches:
            if match.get("_tour") != tour:
                continue
            p1 = match.get("player1") or {}
            p2 = match.get("player2") or {}
            pid1 = match.get("player1Id", p1.get("id"))
            pid2 = match.get("player2Id", p2.get("id"))
            tid = match.get("tournamentId") or match.get("tournament_id")
            rid = match.get("roundId") or match.get("round_id")

            candidates = []
            key = _event_match_key(pid1, pid2, tid, rid)
            if key:
                candidates.append(key)
            reverse = _event_match_key(pid2, pid1, tid, rid)
            if reverse:
                candidates.append(reverse)

            event_id = None
            for candidate in candidates:
                event_id = exact.get(candidate)
                if event_id:
                    break

            # Fallback: algumas versões da API podem omitir o round no
            # matchId. Nesse caso casamos jogadores + torneio + hora aproximada.
            if not event_id:
                short_keys = {
                    _event_match_key(pid1, pid2, tid),
                    _event_match_key(pid2, pid1, tid),
                }
                for match_id, eid in exact.items():
                    if any(match_id.startswith(k + "-") for k in short_keys if k):
                        event_id = eid
                        break

            if not event_id:
                target_key = _event_names_key(p1.get("name", ""), p2.get("name", ""))
                try:
                    target_ts = int(datetime.fromisoformat(
                        str(match.get("date")).replace("Z", "+00:00")
                    ).timestamp())
                except (TypeError, ValueError, OverflowError):
                    target_ts = 0
                possible = [
                    (abs(ts - target_ts), eid)
                    for names_key, ts, eid in names_dates
                    if names_key == target_key and target_ts and ts and abs(ts - target_ts) <= 24 * 3600
                ]
                if possible:
                    possible.sort(key=lambda x: x[0])
                    event_id = possible[0][1]

            if event_id:
                # Chave estável por objeto de fixture para lookup posterior.
                fixture_key = _event_match_key(pid1, pid2, tid, rid) or _event_names_key(p1.get("name", ""), p2.get("name", ""))
                if fixture_key:
                    _RAPIDAPI_EVENT_INDEX[f"{tour}:{fixture_key}"] = event_id
                    short_key = _event_match_key(pid1, pid2, tid)
                    short_reverse = _event_match_key(pid2, pid1, tid)
                    if short_key:
                        _RAPIDAPI_EVENT_INDEX.setdefault(f"{tour}:{short_key}", event_id)
                    if short_reverse:
                        _RAPIDAPI_EVENT_INDEX.setdefault(f"{tour}:{short_reverse}", event_id)

        _RAPIDAPI_EVENT_INDEX_READY.add(tour)
        matched = sum(1 for m in matches if m.get("_tour") == tour and _rapidapi_event_id_for_match(m))
        print(f"[info] RapidAPI Extend {tour}: {matched}/{sum(1 for m in matches if m.get('_tour') == tour)} jogos com eventId para odds.")


def _rapidapi_event_id_for_match(match: dict) -> Optional[str]:
    tour = match.get("_tour")
    p1 = match.get("player1") or {}
    p2 = match.get("player2") or {}
    pid1 = match.get("player1Id", p1.get("id"))
    pid2 = match.get("player2Id", p2.get("id"))
    tid = match.get("tournamentId") or match.get("tournament_id")
    rid = match.get("roundId") or match.get("round_id")

    for key in (
        _event_match_key(pid1, pid2, tid, rid),
        _event_match_key(pid2, pid1, tid, rid),
        _event_match_key(pid1, pid2, tid),
        _event_match_key(pid2, pid1, tid),
    ):
        if key:
            event_id = _RAPIDAPI_EVENT_INDEX.get(f"{tour}:{key}")
            if event_id:
                return event_id
    return None


def fetch_rapidapi_moneyline(match: dict) -> Optional[dict]:
    """
    Obtém a Moneyline (Full Time Result) atual de um jogo pela RapidAPI.
    Usa o eventId da camada Extend e escolhe a melhor odd disponível por
    jogador entre os bookmakers devolvidos. Devolve apenas os números que o
    relatório já espera: {nome_jogador: odd}.
    """
    event_id = _rapidapi_event_id_for_match(match)
    if not event_id:
        return None

    if event_id in _RAPIDAPI_ODDS_CACHE:
        return _RAPIDAPI_ODDS_CACHE[event_id]

    url = f"{RAPIDAPI_EXTEND_BASE}/event/recent-odds/get/{event_id}"
    try:
        resp = _rapidapi_get(url)
        resp.raise_for_status()
        result = (resp.json() or {}).get("result") or {}
        market = result.get("Full Time Result") or {}
        if not market:
            _RAPIDAPI_ODDS_CACHE[event_id] = None
            return None

        player_a = (match.get("player1") or {}).get("name", "")
        player_b = (match.get("player2") or {}).get("name", "")
        best_a = None
        best_b = None

        for bookmaker, quote in market.items():
            if not isinstance(quote, dict):
                continue
            try:
                od1 = float(quote.get("od1"))
                od2 = float(quote.get("od2"))
            except (TypeError, ValueError):
                continue
            if od1 > 1 and (best_a is None or od1 > best_a):
                best_a = od1
            if od2 > 1 and (best_b is None or od2 > best_b):
                best_b = od2

        odds = {}
        if best_a is not None:
            odds[player_a] = best_a
        if best_b is not None:
            odds[player_b] = best_b
        odds = odds or None
        _RAPIDAPI_ODDS_CACHE[event_id] = odds
        if odds:
            print(f"[odds] {player_a} vs {player_b} | RapidAPI event {event_id} | {odds}")
        else:
            print(f"[aviso] RapidAPI sem Moneyline para {player_a} vs {player_b} (event {event_id}).")
        return odds
    except requests.RequestException as exc:
        print(f"[aviso] falha a obter odds RapidAPI para event {event_id}: {exc}")
        _RAPIDAPI_ODDS_CACHE[event_id] = None
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
        for attempt in (1, 2):
            try:
                csv_resp = requests.get(by_name[name]["url"], headers=_BROWSER_HEADERS, timeout=REQUEST_TIMEOUT)
                csv_resp.raise_for_status()
                df_year = pd.read_csv(io.StringIO(csv_resp.text))
                frames.append(df_year)
                break
            except Exception as exc:
                print(f"[aviso] falha a carregar TennisMyLife {name}, tentativa {attempt}: {exc}")

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


def _normalize_tennisdata_couk(df: pd.DataFrame) -> pd.DataFrame:
    """
    O tennis-data.co.uk usa nomes de colunas diferentes da TennisMyLife/
    Sackmann (ex: 'Winner' em vez de 'winner_name', 'Date' como datetime
    em vez de 'tourney_date' no formato YYYYMMDD). Sem esta normalização,
    todas as funções de compute_* (que procuram 'winner_name' etc.)
    devolvem None silenciosamente, mesmo com dados válidos carregados —
    confirmado na prática (27/07/2026) com o fallback WTA.

    Nota: colunas que o tennis-data.co.uk não tem (score combinado,
    w_ace/w_df/etc.) continuam None depois desta normalização — isso é
    uma limitação real da fonte, não um bug (compute_serve_return_stats,
    compute_injury_signal e compute_set1_comeback_stats precisam dessas
    colunas e vão continuar a devolver None para dados desta fonte).
    """
    df = df.rename(columns={
        "Winner": "winner_name",
        "Loser": "loser_name",
        "Surface": "surface",
        "WRank": "winner_rank",
        "LRank": "loser_rank",
        "WPts": "winner_rank_points",
        "LPts": "loser_rank_points",
        "Best of": "best_of",
    })
    if "Date" in df.columns:
        df["tourney_date"] = pd.to_datetime(df["Date"], errors="coerce").dt.strftime("%Y%m%d")
    return df


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
        df = pd.read_excel(io.BytesIO(resp.content))
        return _normalize_tennisdata_couk(df)
    except Exception as exc:
        print(f"[aviso] tennis-data.co.uk indisponível para {tour} {year}: {exc}")
        return None


def _load_tennisdata_couk_multi_year(tour: str, years_to_load: int) -> Optional[pd.DataFrame]:
    """
    Carrega vários anos do tennis-data.co.uk e junta-os. É a rede FIÁVEL
    para o WTA quando o Sackmann está indisponível (30/07/2026): o
    tennis-data.co.uk é estável e tem histórico de vários anos, ao
    contrário do repositório do Sackmann que anda com 404 intermitente.
    Grava também uma cópia local de cada ano em data/history_cache/ para
    reduzir dependência de rede em execuções futuras.
    """
    current_year = datetime.now(timezone.utc).year
    frames = []
    cache_dir = os.path.join("data", "history_cache")
    loaded_years = 0

    for offset in range(years_to_load):
        year = current_year - offset
        local_path = os.path.join(cache_dir, f"{tour}_tdcouk_{year}.csv")
        df_year = None

        # 1) tentar online
        df_year = _load_tennisdata_couk(tour, year)
        if df_year is not None and not df_year.empty:
            loaded_years += 1
            # gravar cópia local (best-effort)
            try:
                os.makedirs(cache_dir, exist_ok=True)
                df_year.to_csv(local_path, index=False)
            except Exception:
                pass
        # 2) se online falhou, tentar cópia local
        elif os.path.exists(local_path):
            try:
                df_year = pd.read_csv(local_path)
                loaded_years += 1
            except Exception:
                df_year = None

        if df_year is not None and not df_year.empty:
            frames.append(df_year)

    if not frames:
        return None

    combined = pd.concat(frames, ignore_index=True)
    print(f"[info] tennis-data.co.uk {tour}: {loaded_years}/{years_to_load} anos, {len(combined)} jogos.")
    return combined


def _load_sackmann_multi_year(tour: str, years_to_load: int) -> Optional[pd.DataFrame]:
    """
    Carrega os últimos `years_to_load` anos de jogos do Sackmann e junta
    tudo. Para cada ano, tenta as várias fontes por ordem (raw.github,
    jsDelivr) e usa a primeira que responder — assim não dependemos de
    saber qual espelho está a funcionar hoje. Reativado (28/07/2026)
    depois de o repositório tennis_wta voltar; tornado multi-fonte
    (29/07/2026) depois de o raw dar 404 intermitente nos runners.
    """
    sources = SACKMANN_SOURCES_ATP if tour == "atp" else SACKMANN_SOURCES_WTA
    current_year = datetime.now(timezone.utc).year
    frames = []
    source_hits = {src: 0 for src in sources}

    for offset in range(years_to_load):
        year = current_year - offset
        loaded = False
        for base in sources:
            if loaded:
                break
            url = f"{base}/{tour}_matches_{year}.csv"
            try:
                resp = requests.get(url, headers=_BROWSER_HEADERS, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
                df_year = pd.read_csv(io.StringIO(resp.text))
                frames.append(df_year)
                source_hits[base] += 1
                loaded = True
            except Exception:
                continue  # tenta a próxima fonte para este ano
        if not loaded:
            print(f"[aviso] Sackmann {tour}_matches_{year}.csv: falhou em todas as fontes.")

    if not frames:
        return None

    combined = pd.concat(frames, ignore_index=True)
    fontes_usadas = ", ".join(f"{src.split('//')[1].split('/')[0]}={n}" for src, n in source_hits.items() if n > 0)
    print(f"[info] Sackmann {tour}: {len(frames)}/{years_to_load} anos carregados, "
          f"{len(combined)} jogos ({fontes_usadas}).")
    return combined


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
        # Reativado (28/07/2026): o repositório tennis_wta do Sackmann
        # voltou a ficar disponível — confirmado ao vivo. Passa a ser a
        # fonte principal para WTA (a TennisMyLife nunca teve WTA).
        df = _load_sackmann_multi_year(tour, HISTORY_YEARS_TO_LOAD)
        source = "sackmann (multi-ano)"

    if df is None or df.empty:
        df = _load_sackmann(tour, year)
        source = "sackmann"
    if df is None or df.empty:
        df = _load_tennisdata_couk_multi_year(tour, HISTORY_YEARS_TO_LOAD)
        source = "tennisdata.co.uk (multi-ano)"
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


def compute_current_season_record(history: pd.DataFrame, player: str) -> Optional[dict]:
    """
    Jogos e vitórias do jogador na ÉPOCA ATUAL (ano corrente) — o dado que
    distingue um jogador em atividade de um ex-campeão que mal joga. Um
    "registo de carreira em hard de 66%" quer dizer pouco se o jogador só
    tem 1-2 jogos esta época. None se não houver dados de data.
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

    played["_date"] = pd.to_datetime(played["tourney_date"], format="%Y%m%d", errors="coerce")
    current_year = datetime.now(timezone.utc).year
    this_season = played[played["_date"].dt.year == current_year]

    matches = len(this_season)
    wins = int((this_season["winner_name"] == player).sum()) if matches else 0
    return {"season": current_year, "matches": matches, "wins": wins, "losses": matches - wins}


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
    # PARTE B (defensiva): o histórico (TennisMyLife/Sackmann) tem atraso
    # de dias — pode não incluir os jogos da 1ª/2ª ronda do próprio torneio
    # em curso. Se o "último jogo conhecido" for anterior ao início do
    # torneio deste jogo mas o jogo atual não for de 1ª ronda, é quase
    # certo que o jogador JÁ jogou nesta semana e o histórico não o tem.
    # Marcamos isso para o Claude não afirmar fadiga com base num dado
    # provavelmente errado. (A correção definitiva do valor vem da parte A,
    # via RapidAPI, quando disponível.)
    result["fatigue_data_maybe_stale"] = (
        days_since_last_match is not None and days_since_last_match > 20
    )

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


def compute_handedness_matchup_stats(history: pd.DataFrame, player: str) -> Optional[dict]:
    """
    Taxa de vitória do jogador especificamente contra adversários canhotos
    vs destros — alguns jogadores têm dificuldade estilística real contra
    canhotos, independentemente do nível geral. Usa as colunas
    'winner_hand'/'loser_hand' já presentes no histórico ('L'/'R'/'U').
    """
    required_cols = {"winner_hand", "loser_hand"}
    if history.empty or not required_cols.issubset(history.columns):
        return None

    resolved = resolve_player_name(history, player)
    if resolved is None:
        return None
    player = resolved

    played = history[(history["winner_name"] == player) | (history["loser_name"] == player)].copy()
    if played.empty:
        return None

    played["_opponent_hand"] = played.apply(
        lambda row: row["loser_hand"] if row["winner_name"] == player else row["winner_hand"], axis=1
    )

    result: dict = {}
    for hand_code, label in (("L", "vs_left_handed"), ("R", "vs_right_handed")):
        subset = played[played["_opponent_hand"] == hand_code]
        if subset.empty:
            result[label] = None
            continue
        wins = int((subset["winner_name"] == player).sum())
        result[label] = {"matches": len(subset), "wins": wins, "losses": len(subset) - wins}

    if result.get("vs_left_handed") is None and result.get("vs_right_handed") is None:
        return None
    return result


def compute_return_from_layoff_stats(history: pd.DataFrame, player: str, threshold_days: int = 60) -> Optional[dict]:
    """
    Como o jogador se sai historicamente no PRIMEIRO jogo depois de uma
    paragem longa (>= threshold_days). Alguns jogadores voltam fortes,
    outros precisam de 1-2 jogos para "aquecer". Diretamente relevante
    quando vemos um jogador a regressar de um hiato (ex: Alcaraz hoje).
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
    played = played.dropna(subset=["tourney_date"]).sort_values("tourney_date").reset_index(drop=True)
    if len(played) < 2:
        return None

    return_matches = 0
    return_wins = 0
    for i in range(1, len(played)):
        gap_days = (played.loc[i, "tourney_date"] - played.loc[i - 1, "tourney_date"]).days
        if gap_days >= threshold_days:
            return_matches += 1
            if played.loc[i, "winner_name"] == player:
                return_wins += 1

    if return_matches == 0:
        return None
    return {
        "threshold_days": threshold_days,
        "matches_after_layoff": return_matches,
        "wins_after_layoff": return_wins,
        "win_rate_pct": round(100 * return_wins / return_matches, 1),
    }


def _count_completed_sets(score) -> int:
    """
    Conta quantos sets têm resultado válido na coluna 'score'.
    B4 da auditoria (28/07/2026): jogos terminados em RET/W-O/DEF contam
    como 0 — "6-4 3-6 2-1 RET" NÃO é um encontro que completou 3 sets, e
    contá-lo distorcia a estatística de set decisivo.
    """
    if not isinstance(score, str) or not score.strip():
        return 0
    upper = score.upper()
    if "RET" in upper or "W/O" in upper or "DEF" in upper or "WO" == upper.strip():
        return 0
    count = 0
    for token in score.strip().split():
        clean = token.split("(")[0]
        parts = clean.split("-")
        if len(parts) == 2 and all(p.strip().isdigit() for p in parts):
            count += 1
    return count


def compute_deciding_set_stats(history: pd.DataFrame, player: str) -> Optional[dict]:
    """
    De entre os jogos que foram até ao set decisivo (3º em melhor-de-3,
    5º em melhor-de-5), em quantos o jogador venceu? Identifica quem é
    forte "na hora da verdade" vs quem tende a desmoronar em sets longos.
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
        deciding_matches = 0
        deciding_wins = 0
        for _, row in subset.iterrows():
            if _count_completed_sets(row.get("score")) == best_of:
                deciding_matches += 1
                if row.get("winner_name") == player:
                    deciding_wins += 1

        if deciding_matches > 0:
            result[label] = {
                "matches_went_the_distance": deciding_matches,
                "wins": deciding_wins,
                "win_rate_pct": round(100 * deciding_wins / deciding_matches, 1),
            }
        else:
            result[label] = None

    if result.get("bo3") is None and result.get("bo5") is None:
        return None
    return result


def compute_round_stage_stats(history: pd.DataFrame, player: str) -> Optional[dict]:
    """
    Compara a taxa de vitória em rondas iniciais (R128/R64/R32/R16) vs
    rondas finais (QF/SF/F) — identifica jogadores inconsistentes cedo
    mas fortes "quando é a sério", ou o inverso.
    """
    if history.empty or "round" not in history.columns:
        return None

    resolved = resolve_player_name(history, player)
    if resolved is None:
        return None
    player = resolved

    played = history[(history["winner_name"] == player) | (history["loser_name"] == player)]
    if played.empty:
        return None

    early_rounds = {"R128", "R64", "R32", "R16"}
    late_rounds = {"QF", "SF", "F"}

    result: dict = {}
    for round_set, label in ((early_rounds, "early_rounds"), (late_rounds, "late_rounds")):
        subset = played[played["round"].isin(round_set)]
        if subset.empty:
            result[label] = None
            continue
        wins = int((subset["winner_name"] == player).sum())
        result[label] = {"matches": len(subset), "wins": wins, "losses": len(subset) - wins}

    if result.get("early_rounds") is None and result.get("late_rounds") is None:
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
# --------------------------------------------------------------------- #
# 6. H2H rico via RapidAPI/matchstat (independente do Sackmann) — usado
#    para WTA, onde não temos histórico de carreira fiável por outra via.
# --------------------------------------------------------------------- #
_H2H_CACHE: dict = {}
H2H_CACHE_MAX_AGE_HOURS = 24  # H2H muda pouco de um dia para o outro


def _h2h_cache_key(tour: str, player1_id: int, player2_id: int) -> str:
    # ordem consistente independentemente de quem é "player1"/"player2"
    ids = sorted([int(player1_id), int(player2_id)])
    return f"{tour}:{ids[0]}:{ids[1]}"


def fetch_h2h_matches(tour: str, player1_id: int, player2_id: int) -> Optional[list]:
    """Lista de confrontos diretos passados entre dois jogadores, por ID matchstat."""
    cache_key = f"matches:{_h2h_cache_key(tour, player1_id, player2_id)}"
    cached = _H2H_CACHE.get(cache_key)
    if cached is not None:
        age_hours = (datetime.now(timezone.utc) - cached["fetched_at"]).total_seconds() / 3600
        if age_hours < H2H_CACHE_MAX_AGE_HOURS:
            return cached["data"]

    if not RAPIDAPI_KEY:
        return None

    url = f"{RAPIDAPI_BASE}/{tour}/h2h/matches/{player1_id}/{player2_id}/"
    try:
        resp = _rapidapi_get(url)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        _H2H_CACHE[cache_key] = {"fetched_at": datetime.now(timezone.utc), "data": data}
        return data
    except requests.RequestException as exc:
        print(f"[aviso] falha a obter h2h/matches ({tour}, {player1_id} vs {player2_id}): {exc}")
        return None


def fetch_h2h_stats(tour: str, player1_id: int, player2_id: int) -> Optional[dict]:
    """
    Stats agregadas do confronto direto (serviço, resposta, break points,
    sets decisivos, tiebreaks, por piso/tier) — específicas a este par de
    jogadores, via matchstat. Independente do Sackmann.
    """
    cache_key = f"stats:{_h2h_cache_key(tour, player1_id, player2_id)}"
    cached = _H2H_CACHE.get(cache_key)
    if cached is not None:
        age_hours = (datetime.now(timezone.utc) - cached["fetched_at"]).total_seconds() / 3600
        if age_hours < H2H_CACHE_MAX_AGE_HOURS:
            return cached["data"]

    if not RAPIDAPI_KEY:
        return None

    url = f"{RAPIDAPI_BASE}/{tour}/h2h/stats/{player1_id}/{player2_id}/"
    try:
        resp = _rapidapi_get(url)
        resp.raise_for_status()
        data = resp.json().get("data")
        _H2H_CACHE[cache_key] = {"fetched_at": datetime.now(timezone.utc), "data": data}
        return data
    except requests.RequestException as exc:
        print(f"[aviso] falha a obter h2h/stats ({tour}, {player1_id} vs {player2_id}): {exc}")
        return None


# --------------------------------------------------------------------- #
# 7. Ranking oficial ao vivo via matchstat (cache semanal — os rankings
#    ATP/WTA só mudam à segunda-feira, não vale buscar mais vezes).
# --------------------------------------------------------------------- #
_OFFICIAL_RANKING_CACHE: dict = {}
OFFICIAL_RANKING_CACHE_MAX_AGE_HOURS = 24 * 7  # 7 dias


def fetch_official_ranking(tour: str) -> Optional[dict]:
    """
    Devolve um dict {nome_normalizado: {'rank', 'points', 'player_id'}}
    com o ranking oficial atual do tour, ou None se falhar. Um só pedido
    traz a lista inteira. Cacheado 7 dias (rankings mudam à segunda).

    O nome é normalizado (minúsculas, sem acentos) para poder cruzar com
    os nomes que vêm das fixtures/histórico.
    """
    cached = _OFFICIAL_RANKING_CACHE.get(tour)
    if cached is not None:
        age_hours = (datetime.now(timezone.utc) - cached["fetched_at"]).total_seconds() / 3600
        if age_hours < OFFICIAL_RANKING_CACHE_MAX_AGE_HOURS:
            return cached["data"]

    if not RAPIDAPI_KEY:
        return None

    url = f"{RAPIDAPI_BASE}/{tour}/ranking/singles/"
    try:
        resp = _rapidapi_get(url)
        resp.raise_for_status()
        rows = resp.json().get("data", [])
        ranking_map: dict = {}
        for row in rows:
            player = row.get("player") or {}
            name = player.get("name")
            if not name:
                continue
            key = _normalize_name(name)
            ranking_map[key] = {
                "rank": row.get("position"),
                "points": row.get("point") or row.get("rankingPoints"),
                "player_id": player.get("id"),
            }
        _OFFICIAL_RANKING_CACHE[tour] = {"fetched_at": datetime.now(timezone.utc), "data": ranking_map}
        print(f"[info] ranking oficial {tour}: {len(ranking_map)} jogadores carregados.")
        return ranking_map
    except requests.RequestException as exc:
        print(f"[aviso] falha a obter ranking oficial {tour}: {exc}")
        return None


_CAREER_STATS_CACHE: dict = {}
CAREER_STATS_CACHE_MAX_AGE_HOURS = 24 * 7  # 7 dias — stats de carreira mudam devagar


def fetch_player_career_stats(tour: str, player_id: int) -> Optional[dict]:
    """
    Stats de carreira do jogador contra TODOS os adversários (endpoint
    getH2HVsAllOppStats), por ID matchstat. Rico: serviço, resposta,
    break points, 1º set (ganho/perdido → resultado), set decisivo,
    tiebreaks, duração média, por piso e por nível de torneio. Cobre ATP
    e WTA por igual. Cache 7 dias. None se falhar.
    """
    cache_key = f"{tour}:{player_id}"
    cached = _CAREER_STATS_CACHE.get(cache_key)
    if cached is not None:
        age_hours = (datetime.now(timezone.utc) - cached["fetched_at"]).total_seconds() / 3600
        if age_hours < CAREER_STATS_CACHE_MAX_AGE_HOURS:
            return cached["data"]

    persistent = _read_player_cache_entry(
        tour,
        player_id,
        "career_stats",
        CAREER_STATS_CACHE_MAX_AGE_HOURS,
    )
    if persistent is not None:
        _CAREER_STATS_CACHE[cache_key] = {
            "fetched_at": datetime.now(timezone.utc),
            "data": persistent,
        }
        return persistent

    if not RAPIDAPI_KEY:
        return None

    url = f"{RAPIDAPI_BASE}/{tour}/h2h/vs-all-stats/{player_id}/"
    try:
        resp = _rapidapi_get(url)
        resp.raise_for_status()
        data = resp.json().get("data")
        _CAREER_STATS_CACHE[cache_key] = {"fetched_at": datetime.now(timezone.utc), "data": data}
        _write_player_cache_entry(tour, player_id, "career_stats", data)
        return data
    except requests.RequestException as exc:
        print(f"[aviso] falha a obter career stats ({tour}, id {player_id}): {exc}")
        return None


_PERF_BREAKDOWN_CACHE: dict = {}
PERF_BREAKDOWN_CACHE_MAX_AGE_HOURS = 24 * 7  # 7 dias


_RECENT_MATCHES_CACHE: dict = {}
RECENT_MATCHES_CACHE_MAX_AGE_HOURS = 24  # 1 dia (jogos novos aparecem diariamente)


def fetch_player_recent_matches(tour: str, player_id: int) -> Optional[list]:
    """
    Jogos recentes do jogador (endpoint past-matches), por ID matchstat.
    Devolve uma lista de jogos (mais recente primeiro), cada um com date
    (ISO), tournamentId, match_winner, result, player1Id, player2Id.
    É a fonte FIÁVEL para a fadiga real: inclui os jogos do torneio em
    curso (que o histórico Sackmann/tennis-data só regista com atraso).
    Cache 1 dia. None se falhar (a fadiga cai então no fallback do histórico).
    """
    cache_key = f"{tour}:{player_id}"
    cached = _RECENT_MATCHES_CACHE.get(cache_key)
    if cached is not None:
        age_hours = (datetime.now(timezone.utc) - cached["fetched_at"]).total_seconds() / 3600
        if age_hours < RECENT_MATCHES_CACHE_MAX_AGE_HOURS:
            return cached["data"]

    persistent = _read_player_cache_entry(
        tour,
        player_id,
        "recent_matches",
        RECENT_MATCHES_CACHE_MAX_AGE_HOURS,
    )
    if persistent is not None:
        _RECENT_MATCHES_CACHE[cache_key] = {
            "fetched_at": datetime.now(timezone.utc),
            "data": persistent,
        }
        return persistent

    if not RAPIDAPI_KEY:
        return None

    url = f"{RAPIDAPI_BASE}/{tour}/player/past-matches/{player_id}"
    try:
        resp = _rapidapi_get(url)
        resp.raise_for_status()
        data = resp.json().get("data")
        if not isinstance(data, list):
            data = None
        _RECENT_MATCHES_CACHE[cache_key] = {"fetched_at": datetime.now(timezone.utc), "data": data}
        _write_player_cache_entry(tour, player_id, "recent_matches", data)
        return data
    except requests.RequestException as exc:
        print(f"[aviso] falha a obter jogos recentes ({tour}, id {player_id}): {exc}")
        return None


def compute_fatigue_from_recent(recent_matches: list, player_id: int,
                                 match_date: datetime, current_tournament_id=None) -> Optional[dict]:
    """
    Fadiga REAL a partir dos jogos recentes da API (past-matches). Corrige
    o bug de o histórico ignorar os jogos do torneio em curso (dava "25
    dias" a quem está nas meias-finais). Calcula:
      - days_since_last_match (real)
      - matches_last_3d / _7d / _14d
      - matches_this_tournament (carga acumulada esta semana — o sinal que
        importa nas fases finais)
      - sets_last_7d (contados do campo result)
    """
    if not recent_matches:
        return None

    played = []  # (data, é_do_torneio_atual, n_sets)
    for m in recent_matches:
        if not isinstance(m, dict):
            continue
        # confirmar que o jogo envolve este jogador
        if player_id not in (m.get("player1Id"), m.get("player2Id")):
            continue
        raw_date = m.get("date")
        if not raw_date:
            continue
        try:
            d = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        # só jogos ANTES do jogo que estamos a analisar (não jogos futuros)
        if d >= match_date:
            continue
        # contar sets a partir do result ("6-4 3-6 6-3" = 3 sets)
        result = m.get("result") or ""
        n_sets = len([s for s in result.split() if "-" in s]) if result else 0
        is_current = (current_tournament_id is not None
                      and m.get("tournamentId") == current_tournament_id)
        played.append((d, is_current, n_sets))

    if not played:
        return None

    played.sort(key=lambda x: x[0], reverse=True)
    last_date = played[0][0]
    days_since = (match_date - last_date).days

    def _count_within(days):
        cutoff = match_date - timedelta(days=days)
        return sum(1 for d, _, _ in played if d >= cutoff)

    sets_7d = sum(n for d, _, n in played if d >= match_date - timedelta(days=7))
    matches_tourn = sum(1 for _, is_cur, _ in played if is_cur)

    return {
        "days_since_last_match": days_since,
        "matches_last_3d": _count_within(3),
        "matches_last_7d": _count_within(7),
        "matches_last_14d": _count_within(14),
        "matches_this_tournament": matches_tourn,
        "sets_last_7d": sets_7d,
        "fatigue_source": "api_recent",  # marca que veio da fonte fiável
    }


def compute_h2h_from_api(h2h_matches: list, player_a_id: int, player_b_id: int,
                          current_surface: Optional[str] = None) -> Optional[dict]:
    """
    H2H calculado a partir da lista de confrontos da RapidAPI (fetch_h2h_matches),
    para não depender do histórico Sackmann (partido para WTA). Mesmo formato
    que compute_h2h: {overall:{a_wins,b_wins,total_matches}, on_surface, surface}.
    """
    if not h2h_matches:
        return None
    a_wins = b_wins = 0
    a_surf = b_surf = 0
    for m in h2h_matches:
        if not isinstance(m, dict):
            continue
        winner = m.get("match_winner") or m.get("winnerId") or m.get("winner")
        if winner is None:
            continue
        # normalizar o piso do confronto
        surf = (m.get("court") or m.get("surface") or "")
        surf = str(surf).lower()
        same_surface = current_surface and current_surface.lower() in surf
        if winner == player_a_id:
            a_wins += 1
            if same_surface: a_surf += 1
        elif winner == player_b_id:
            b_wins += 1
            if same_surface: b_surf += 1
    total = a_wins + b_wins
    if total == 0:
        return None
    overall = {"a_wins": a_wins, "b_wins": b_wins, "total_matches": total}
    on_surface = None
    if current_surface and (a_surf + b_surf) > 0:
        on_surface = {"a_wins": a_surf, "b_wins": b_surf, "total_matches": a_surf + b_surf}
    return {"overall": overall, "on_surface": on_surface, "surface": current_surface}


def compute_form_from_recent(recent_matches: list, player_id: int,
                              match_date: datetime, n_matches: int = 10,
                              current_surface: Optional[str] = None) -> dict:
    """
    Forma recente + época atual + piso, a partir dos jogos recentes da API
    (past-matches). Substitui compute_recent_form/current_season/surface_stats
    para o WTA (Sackmann partido). Devolve dict com 'form', 'season', 'surface'.
    """
    out = {"form": None, "season": None, "surface": None}
    if not recent_matches:
        return out

    jogos = []  # (data, ganhou_bool, piso)
    for m in recent_matches:
        if not isinstance(m, dict):
            continue
        if player_id not in (m.get("player1Id"), m.get("player2Id")):
            continue
        raw = m.get("date")
        if not raw:
            continue
        try:
            d = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        if d >= match_date:
            continue
        winner = m.get("match_winner")
        ganhou = (winner == player_id) if winner is not None else None
        if ganhou is None:
            continue
        surf = str(m.get("court") or m.get("surface") or "").lower()
        jogos.append((d, ganhou, surf))

    if not jogos:
        return out
    jogos.sort(key=lambda x: x[0], reverse=True)

    # forma: últimos n jogos
    ult = jogos[:n_matches]
    w = sum(1 for _, g, _ in ult if g)
    out["form"] = {"wins": w, "losses": len(ult) - w, "matches": len(ult)}

    # época atual: jogos do ano do match_date
    ano = match_date.year
    da_epoca = [(g) for d, g, _ in jogos if d.year == ano]
    if da_epoca:
        we = sum(1 for g in da_epoca if g)
        out["season"] = {"wins": we, "losses": len(da_epoca) - we, "matches": len(da_epoca)}

    # piso: jogos no piso atual (todos os recentes disponíveis)
    if current_surface:
        cs = current_surface.lower()
        no_piso = [(g) for _, g, s in jogos if cs in s]
        if no_piso:
            wp = sum(1 for g in no_piso if g)
            out["surface"] = {"wins": wp, "losses": len(no_piso) - wp, "matches": len(no_piso)}
    return out


def fetch_player_perf_breakdown(tour: str, player_id: int) -> Optional[dict]:
    """
    Desempenho do jogador SEPARADO POR NÍVEL DE RANKING do adversário
    (top1/5/10/20/50/100), por ano e por piso — endpoint perf-breakdown.
    É o que permite distinguir "ganha muito contra fracos" de "ganha
    contra os melhores". Devolve um resumo AGREGADO (soma de todos os anos)
    do desempenho por patamar de ranking, ou None. Cache 7 dias.
    """
    cache_key = f"{tour}:{player_id}"
    cached = _PERF_BREAKDOWN_CACHE.get(cache_key)
    if cached is not None:
        age_hours = (datetime.now(timezone.utc) - cached["fetched_at"]).total_seconds() / 3600
        if age_hours < PERF_BREAKDOWN_CACHE_MAX_AGE_HOURS:
            return cached["data"]

    persistent = _read_player_cache_entry(
        tour,
        player_id,
        "perf_breakdown",
        PERF_BREAKDOWN_CACHE_MAX_AGE_HOURS,
    )
    if persistent is not None:
        _PERF_BREAKDOWN_CACHE[cache_key] = {
            "fetched_at": datetime.now(timezone.utc),
            "data": persistent,
        }
        return persistent

    if not RAPIDAPI_KEY:
        return None

    url = f"{RAPIDAPI_BASE}/{tour}/player/perf-breakdown/{player_id}"
    try:
        resp = _rapidapi_get(url)
        resp.raise_for_status()
        raw = resp.json().get("data", {})

        # Agregar 'rank' (vs top1/5/10/20/50/100) somando todos os anos.
        # Formato por ano: {ano: {"rank": {"top10": {"aw":X,"al":Y}, ...}}}
        levels = ("top1", "top5", "top10", "top20", "top50", "top100")
        agg = {lv: {"wins": 0, "losses": 0} for lv in levels}
        for year_data in (raw.values() if isinstance(raw, dict) else []):
            rank_block = (year_data or {}).get("rank", {})
            for lv in levels:
                cell = rank_block.get(lv) or {}
                agg[lv]["wins"] += cell.get("aw", 0) or 0
                agg[lv]["losses"] += cell.get("al", 0) or 0

        # Só devolve patamares com jogos, com a percentagem calculada
        summary = {}
        for lv in levels:
            w, l = agg[lv]["wins"], agg[lv]["losses"]
            total = w + l
            if total > 0:
                summary[lv] = {"wins": w, "losses": l, "matches": total,
                               "win_pct": round(100 * w / total, 1)}

        # Agregar desempenho por PISO (chave "court" por ano). Mapeamento dos
        # índices confirmado contra o vs-all-stats (01/08/2026):
        # 1=Hard(outdoor), 2=Clay, 3=Hard indoor, 4=Carpet, 5=Grass.
        court_map = {"1": "hard", "2": "clay", "3": "hard_indoor",
                     "4": "carpet", "5": "grass"}
        surf_agg = {v: {"wins": 0, "losses": 0} for v in court_map.values()}
        for year_data in (raw.values() if isinstance(raw, dict) else []):
            court_block = (year_data or {}).get("court", {})
            if not isinstance(court_block, dict):
                continue
            for idx, name in court_map.items():
                cell = court_block.get(idx)
                if isinstance(cell, dict):
                    surf_agg[name]["wins"] += cell.get("aw", 0) or 0
                    surf_agg[name]["losses"] += cell.get("al", 0) or 0

        by_surface = {}
        for name, rec in surf_agg.items():
            w, l = rec["wins"], rec["losses"]
            total = w + l
            if total > 0:
                by_surface[name] = {"wins": w, "losses": l, "matches": total,
                                    "win_pct": round(100 * w / total, 1)}

        # Desempenho por NÍVEL DE TORNEIO (chave "level" por ano). Nomes
        # diretos na API (confirmado no JSON real). Só guardamos os níveis
        # relevantes para os torneios que seguimos (250/500/1000/GS); os
        # menores (challengers/futures/cups) e o "total" são ignorados.
        level_map = {"grandSlam": "grand_slam", "masters": "masters",
                     "mainTour": "main_tour"}
        lvl_agg = {v: {"wins": 0, "losses": 0} for v in level_map.values()}
        for year_data in (raw.values() if isinstance(raw, dict) else []):
            level_block = (year_data or {}).get("level", {})
            if not isinstance(level_block, dict):
                continue
            for api_key, name in level_map.items():
                cell = level_block.get(api_key)
                if isinstance(cell, dict):
                    lvl_agg[name]["wins"] += cell.get("aw", 0) or 0
                    lvl_agg[name]["losses"] += cell.get("al", 0) or 0

        by_level = {}
        for name, rec in lvl_agg.items():
            w, l = rec["wins"], rec["losses"]
            total = w + l
            if total > 0:
                by_level[name] = {"wins": w, "losses": l, "matches": total,
                                  "win_pct": round(100 * w / total, 1)}

        data = {}
        if summary:
            data["vs_rank_level"] = summary
        if by_surface:
            data["by_surface"] = by_surface
        if by_level:
            data["by_level"] = by_level
        data = data or None
        _PERF_BREAKDOWN_CACHE[cache_key] = {"fetched_at": datetime.now(timezone.utc), "data": data}
        _write_player_cache_entry(tour, player_id, "perf_breakdown", data)
        return data
    except requests.RequestException as exc:
        print(f"[aviso] falha a obter perf-breakdown ({tour}, id {player_id}): {exc}")
        return None


def get_player_id_from_ranking(tour: str, player_name: str) -> Optional[int]:
    """
    Resolve o ID matchstat de um jogador a partir do ranking oficial (que
    já traz o player_id de cada um). Necessário para chamar endpoints que
    funcionam por ID (career stats, h2h). None se não encontrar.
    """
    official = fetch_official_ranking(tour)
    if not official:
        return None
    entry = official.get(_normalize_name(player_name))
    return entry.get("player_id") if entry else None


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

    # B5 da auditoria (28/07/2026): se o jogo mais recente não tiver
    # ranking registado, recuamos até ao último jogo COM ranking válido
    # (até 10 jogos para trás), em vez de devolver None imediatamente.
    for _, row in played.iloc[::-1].head(10).iterrows():
        is_winner = row.get("winner_name") == player
        rank_col = "winner_rank" if is_winner else "loser_rank"
        points_col = "winner_rank_points" if is_winner else "loser_rank_points"

        rank_value = row.get(rank_col)
        if pd.isna(rank_value):
            continue

        points_value = row.get(points_col)
        return {
            "rank": int(rank_value),
            "points": int(points_value) if not pd.isna(points_value) else None,
            "as_of": str(row.get("tourney_date")),
        }
    return None


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


# --------------------------------------------------------------------- #
# CÓDIGO NÃO USADO ATUALMENTE (28/07/2026): esta função e
# fetch_all_upcoming_fixtures() eram a arquitetura antiga — feed global
# "todos os jogos ATP do dia" via getDateFixtures. Substituída por
# fetch_tournament_fixtures()/fetch_tracked_tournament_fixtures() (mais
# abaixo), que pede diretamente por tournamentId e evita o ruído global.
# Mantida por se um dia for útil como mecanismo de DESCOBERTA de novos
# torneios (a nova arquitetura exige adicionar tournamentId manualmente
# a TRACKED_TOURNAMENT_IDS — ver README). Não é chamada por main.py.
# --------------------------------------------------------------------- #
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
            resp = _rapidapi_get(url, params=params)
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


def fetch_tournament_fixtures(tournament_id: int, tour: str) -> list[dict]:
    """
    Busca TODOS os jogos de um torneio específico diretamente pelo
    tournamentId (endpoint getTournamentFixtures) — muito mais eficiente
    do que o feed global por dia, que traz ruído de torneios do mundo
    inteiro. Filtra automaticamente jogos de pares (nomes com "/") e
    jogos ainda sem data marcada (date: null).

    Usa a mesma cache de fixtures (por chave "torneio:{id}"), com o
    mesmo tempo de vida configurado (FIXTURES_CACHE_MAX_AGE_HOURS).
    """
    global _fixtures_cache_dirty
    cache_key = f"torneio:{tournament_id}"

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

    url = f"{RAPIDAPI_BASE}/{tour}/fixtures/tournament/{tournament_id}"
    all_data: list[dict] = []
    page = 1
    try:
        while True:
            params = {
                "pageSize": TOURNAMENT_FIXTURES_PAGE_SIZE,
                "pageNo": page,
                "filter": "PlayerGroup:both;",
            }
            resp = _rapidapi_get(url, params=params)
            resp.raise_for_status()
            payload = resp.json()
            page_data = payload.get("data", [])

            # Filtrar pares (nomes com "/") e jogos ainda sem data marcada —
            # não fazem parte da análise (só singles) nem são "elegíveis"
            # sem data para verificar a janela de antecedência.
            for match in page_data:
                p1_name = (match.get("player1") or {}).get("name", "")
                p2_name = (match.get("player2") or {}).get("name", "")
                if "/" in p1_name or "/" in p2_name:
                    continue
                if not match.get("date"):
                    continue
                match["_tour"] = tour
                all_data.append(match)

            if not payload.get("hasNextPage"):
                break
            page += 1
            if page > MAX_FIXTURE_PAGES:
                print(f"[aviso] fixtures {cache_key}: atingido o limite de {MAX_FIXTURE_PAGES} páginas.")
                break

        _fixtures_cache[cache_key] = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "data": all_data,
        }
        _fixtures_cache_dirty = True
        print(f"[info] fixtures {cache_key}: {len(all_data)} jogo(s) de singles com data marcada.")
        return all_data
    except requests.RequestException as exc:
        print(f"[aviso] falha a obter fixtures do torneio {tournament_id}: {exc}")
        return []


def fetch_tracked_tournament_fixtures() -> list[dict]:
    """Junta fixtures de todos os torneios em TRACKED_TOURNAMENT_IDS."""
    all_matches = []
    for tournament_id, tour in TRACKED_TOURNAMENT_IDS.items():
        all_matches.extend(fetch_tournament_fixtures(tournament_id, tour))
    return all_matches


def fetch_all_upcoming_fixtures(lookahead_days: int) -> list[dict]:
    """Junta fixtures dos tours configurados (TOURS_TO_FOLLOW) para os próximos `lookahead_days` dias (incl. hoje)."""
    all_matches = []
    today = datetime.now(timezone.utc)
    for offset in range(lookahead_days):
        day = today + timedelta(days=offset)
        for tour in TOURS_TO_FOLLOW:
            day_matches = fetch_date_fixtures(day, tour)
            print(f"[diagnóstico] pedido para {day.strftime('%Y-%m-%d')} ({tour}) devolveu {len(day_matches)} jogo(s).")
            all_matches.extend(day_matches)
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
        resp = _rapidapi_get(url)
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
