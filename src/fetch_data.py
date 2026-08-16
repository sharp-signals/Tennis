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
from urllib.parse import urlparse
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
import requests

from .cache_store import JsonCacheStore
from .config import (
    ALLOWED_TOURNAMENT_TIERS,
    FIXTURES_CACHE_MAX_AGE_HOURS,
    FIXTURES_CACHE_PATH,
    HISTORY_YEARS_TO_LOAD,
    MAX_FIXTURE_PAGES,
    RAPIDAPI_BASE,
    RAPIDAPI_HOST,
    RAPIDAPI_MAX_CALLS_PER_DAY,
    RAPIDAPI_MAX_CALLS_PER_RUN,
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
_RAPIDAPI_ENDPOINT_CALLS: dict[str, int] = {}
_RAPIDAPI_RECORDED_TODAY = {"n": 0}
_RAPIDAPI_BUDGET_EXCEEDED = {"value": False}
RAPIDAPI_MIN_INTERVAL = 0.35
_RAPIDAPI_LAST_CALL = {"t": 0.0}
_RAPIDAPI_LOCK = threading.Lock()
RAPIDAPI_USAGE_PATH = os.environ.get("RAPIDAPI_USAGE_PATH", "data/rapidapi_usage_log.json")
RAPIDAPI_INFLIGHT_PATH = os.environ.get("RAPIDAPI_INFLIGHT_PATH", "data/rapidapi_usage_inflight.json")
RAPIDAPI_CHECKPOINT_EVERY = 10


class RapidAPIBudgetExceeded(RuntimeError):
    """A execução atingiu o orçamento configurado antes do pedido seguinte."""


def _load_recorded_today_calls() -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        with open(RAPIDAPI_USAGE_PATH, "r", encoding="utf-8") as handle:
            history = json.load(handle)
        recorded = sum(
            int(item.get("calls") or 0)
            for item in history
            if str(item.get("timestamp", "")).startswith(today)
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        recorded = 0
    try:
        with open(RAPIDAPI_INFLIGHT_PATH, "r", encoding="utf-8") as handle:
            inflight = json.load(handle)
        if str(inflight.get("timestamp", "")).startswith(today):
            recorded += int(inflight.get("calls") or 0)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        pass
    return recorded


def _write_rapidapi_checkpoint() -> None:
    path = RAPIDAPI_INFLIGHT_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    temp = f"{path}.tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump({"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "calls": _RAPIDAPI_CALL_COUNT["n"]}, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def persist_rapidapi_usage(*, status: str, matches: int = 0) -> dict:
    """Fecha o checkpoint numa entrada histórica, incluindo runs falhadas."""
    entry = {"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "calls": get_rapidapi_call_count(), "matches": int(matches), "status": status}
    try:
        with open(RAPIDAPI_USAGE_PATH, "r", encoding="utf-8") as handle:
            history = json.load(handle)
        if not isinstance(history, list):
            history = []
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        history = []
    os.makedirs(os.path.dirname(RAPIDAPI_USAGE_PATH) or ".", exist_ok=True)
    temp = f"{RAPIDAPI_USAGE_PATH}.tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump((history + [entry])[-365:], handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, RAPIDAPI_USAGE_PATH)
    try:
        os.remove(RAPIDAPI_INFLIGHT_PATH)
    except FileNotFoundError:
        pass
    return entry


def clear_rapidapi_checkpoint() -> None:
    try:
        os.remove(RAPIDAPI_INFLIGHT_PATH)
    except FileNotFoundError:
        pass


def _reserve_rapidapi_call() -> None:
    """Reserva atomicamente uma chamada real, incluindo tentativas após 429."""
    projected_run = _RAPIDAPI_CALL_COUNT["n"] + 1
    projected_day = _RAPIDAPI_RECORDED_TODAY["n"] + projected_run
    if (
        projected_run > RAPIDAPI_MAX_CALLS_PER_RUN
        or projected_day > RAPIDAPI_MAX_CALLS_PER_DAY
    ):
        _RAPIDAPI_BUDGET_EXCEEDED["value"] = True
        raise RapidAPIBudgetExceeded(
            "Orçamento RapidAPI atingido "
            f"(execução={_RAPIDAPI_CALL_COUNT['n']}/{RAPIDAPI_MAX_CALLS_PER_RUN}, "
            f"dia={projected_day - 1}/{RAPIDAPI_MAX_CALLS_PER_DAY})."
        )
    _RAPIDAPI_CALL_COUNT["n"] = projected_run
    if projected_run == 1 or projected_run % RAPIDAPI_CHECKPOINT_EVERY == 0:
        _write_rapidapi_checkpoint()


def _rapidapi_get(url, **kwargs):
    """Wrapper único com orçamento, contador real, anti-429 e retry."""
    import time
    for tentativa in range(3):
        with _RAPIDAPI_LOCK:
            _reserve_rapidapi_call()
            endpoint = urlparse(str(url)).path
            _RAPIDAPI_ENDPOINT_CALLS[endpoint] = _RAPIDAPI_ENDPOINT_CALLS.get(endpoint, 0) + 1
            elapsed = time.monotonic() - _RAPIDAPI_LAST_CALL["t"]
            if elapsed < RAPIDAPI_MIN_INTERVAL:
                time.sleep(RAPIDAPI_MIN_INTERVAL - elapsed)
            _RAPIDAPI_LAST_CALL["t"] = time.monotonic()
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


def get_rapidapi_endpoint_counts() -> dict[str, int]:
    return dict(sorted(_RAPIDAPI_ENDPOINT_CALLS.items()))


def reset_rapidapi_call_count() -> None:
    _RAPIDAPI_CALL_COUNT["n"] = 0
    _RAPIDAPI_ENDPOINT_CALLS.clear()
    _RAPIDAPI_RECORDED_TODAY["n"] = _load_recorded_today_calls()
    _RAPIDAPI_BUDGET_EXCEEDED["value"] = False
    _write_rapidapi_checkpoint()


def rapidapi_budget_exceeded() -> bool:
    return _RAPIDAPI_BUDGET_EXCEEDED["value"]


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
# URL do "All Upcoming Matches" — devolve {"total","matches"} com odds
# embutidas (player.odd). Path confirmado pelo curl real da RapidAPI:
#   /tennis/v2/ms-api/upcoming/matches?tournament=...&limit=...&page=...
# (NÃO é /extend/api/events/upcoming — esse devolve 'results' sem as odds.)
RAPIDAPI_ALL_UPCOMING_URL = f"{RAPIDAPI_BASE}/ms-api/upcoming/matches"
# Teto de páginas ao carregar o all-upcoming (100 jogos/página). 20 = 2000
# jogos, cobre qualquer dia com folga. Evita loop infinito se a API não
# sinalizar bem a última página.
_ALL_UPCOMING_MAX_PAGES = 20

# Índice de eventos da camada Extend da RapidAPI.
# As fixtures normais usam o ID principal do jogo (match ID), enquanto os
# endpoints de odds usam o eventId da camada Extend. O índice faz a ponte
# entre os dois sem ter de chamar /event/get individualmente para cada jogo.
_RAPIDAPI_EVENT_INDEX: dict[str, dict] = {}
_RAPIDAPI_EVENT_INDEX_READY: set[str] = set()
_RAPIDAPI_ODDS_CACHE: dict[str, Optional[dict]] = {}
_RAPIDAPI_EMBEDDED_ODDS: dict[str, dict] = {}  # odds vindas da lista upcoming
_ALL_UPCOMING_EVENTS_CACHE: Optional[list[dict]] = None  # cache desta execução


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
    Carrega os eventos upcoming para obter as ODDS EMBUTIDAS (player.odd) e
    também o TORNEIO de cada jogo (tournament.id/name/rankId) — usado pela
    descoberta automática de torneios (discover_tracked_tournaments).
    Usa PRIMEIRO o "All Upcoming Matches" — devolve {"total", "matches"} com
    as odds embutidas em cada jogo (confirmado: traz ATP e WTA, incluindo os
    jogos que o by-tour não indexava). Só cai no by-tour se o All falhar.
    O parâmetro `tour` mantém-se por compatibilidade, mas o All traz tudo.

    Cacheado nesta execução (_ALL_UPCOMING_EVENTS_CACHE): tanto a descoberta
    de torneios como a indexação de odds precisam deste mesmo feed — sem
    cache, duplicaria ~6 pedidos paginados por execução.
    """
    global _ALL_UPCOMING_EVENTS_CACHE
    if _ALL_UPCOMING_EVENTS_CACHE is not None:
        return _ALL_UPCOMING_EVENTS_CACHE

    if not RAPIDAPI_KEY:
        return []

    events: list[dict] = []

    # --- FONTE PRINCIPAL: Upcoming Matches por tour (tem matches + odds embutidas) ---
    # Confirmado por teste real: o endpoint SEM tour no path só devolve ATP.
    # O tour é um SEGMENTO DE PATH, não um query param:
    #   /tennis/v2/ms-api/upcoming/matches/atp
    #   /tennis/v2/ms-api/upcoming/matches/wta
    # Por isso é preciso uma chamada (paginada) por cada tour.
    # NOTA: o campo "total" da resposta é o tamanho da PÁGINA (=limit), não o
    # total de jogos — por isso NÃO serve como condição de paragem.
    LIMIT = 100
    for t in ("atp", "wta"):
        page = 1
        tour_events: list[dict] = []
        while page <= _ALL_UPCOMING_MAX_PAGES:
            url = f"{RAPIDAPI_ALL_UPCOMING_URL}/{t}"
            try:
                resp = _rapidapi_get(url, params={"page": page, "limit": LIMIT})
                resp.raise_for_status()
                payload = resp.json() or {}
                page_results = payload.get("matches") or []
                if page == 1:
                    _chaves = list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__
                    print(f"[diag] all-upcoming/{t}: HTTP {resp.status_code}, "
                          f"chaves={_chaves}, total={payload.get('total')}, "
                          f"matches_pag1={len(page_results)}, url={url}")
                novos = [e for e in page_results if isinstance(e, dict)]
                tour_events.extend(novos)
                # parar quando a página vier vazia ou incompleta (última página)
                if len(page_results) < LIMIT or not novos:
                    break
                page += 1
            except requests.RequestException as exc:
                print(f"[aviso] falha a obter all-upcoming/{t} (pág {page}) para odds: {exc}")
                break
        print(f"[diag] all-upcoming/{t}: {len(tour_events)} jogos carregados em {page} página(s).")
        events.extend(tour_events)

    if events:
        _ALL_UPCOMING_EVENTS_CACHE = events
        return events

    # --- FALLBACK: by-tour (estrutura antiga, caso o All falhe) ---
    print(f"[diag] all-upcoming vazio — a tentar by-tour {tour}.")
    page = 1
    while True:
        url = f"{RAPIDAPI_EXTEND_BASE}/events/upcoming/{tour}"
        try:
            resp = _rapidapi_get(url, params={"page": page, "limit": 100})
            resp.raise_for_status()
            payload = resp.json() or {}
            page_results = payload.get("matches") or payload.get("results") or []
            if page == 1:
                _chaves = list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__
                print(f"[diag] upcoming/{tour}: HTTP {resp.status_code}, "
                      f"chaves={_chaves}, matches={len(page_results)}, url={url}")
            events.extend(e for e in page_results if isinstance(e, dict))
            total = payload.get("total")
            if not page_results or (isinstance(total, int) and len(events) >= total):
                break
            page += 1
            if page > MAX_FIXTURE_PAGES:
                break
        except requests.RequestException as exc:
            print(f"[aviso] falha a obter eventos upcoming {tour}: {exc}")
            break
    return events


def prepare_rapidapi_odds_index(matches: list[dict]) -> None:
    """
    Prepara, uma vez por execução, as odds de cada jogo a partir da lista de
    upcoming events da RapidAPI. As odds vêm EMBUTIDAS em cada evento
    (player1.odd / player2.odd), por isso lemo-las diretamente daqui — sem
    precisar de cruzar eventId nem de uma segunda chamada ao recent-odds
    (que era o que falhava para alguns jogos). Indexadas por par de apelidos.
    """
    global _RAPIDAPI_EVENT_INDEX_READY

    # O all-upcoming traz TODOS os tours de uma vez — por isso carregamos UMA
    # só vez (não por tour), evitando descarregar centenas de jogos em
    # duplicado. Indexamos tudo na chave global "*:{key}" e também por tour.
    if "__ALL__" not in _RAPIDAPI_EVENT_INDEX_READY:
        events = _fetch_extend_upcoming_events("all")
        def _odd(pl, kkey, ev):
            o = pl.get("odd")
            if o is None:
                o = (ev.get("odds") or {}).get(kkey)
            try:
                o = float(o)
                return o if o > 1 else None
            except (TypeError, ValueError):
                return None
        n_indexados = 0
        for event in events:
            p1 = event.get("player1") or {}
            p2 = event.get("player2") or {}
            n1, n2 = p1.get("name", ""), p2.get("name", "")
            if not n1 or not n2:
                continue
            oa = _odd(p1, "k1", event)
            ob = _odd(p2, "k2", event)
            if oa is None or ob is None:
                continue
            key = _odds_names_key(n1, n2)
            if key:
                registo = {"n1": n1, "n2": n2, "o1": oa, "o2": ob}
                _RAPIDAPI_EMBEDDED_ODDS[f"*:{key}"] = registo
                n_indexados += 1
        _RAPIDAPI_EVENT_INDEX_READY.add("__ALL__")
        # diagnóstico: quantos dos NOSSOS jogos casaram
        casados = 0
        for m in matches:
            pa = (m.get("player1") or {}).get("name", "")
            pb = (m.get("player2") or {}).get("name", "")
            k = _odds_names_key(pa, pb)
            if k and f"*:{k}" in _RAPIDAPI_EMBEDDED_ODDS:
                casados += 1
        print(f"[info] RapidAPI odds embutidas: {n_indexados} eventos indexados; "
              f"{casados}/{len(matches)} dos nossos jogos casaram.")
        # se algum não casou, mostrar quais (para diagnóstico de nomes)
        for m in matches:
            pa = (m.get("player1") or {}).get("name", "")
            pb = (m.get("player2") or {}).get("name", "")
            k = _odds_names_key(pa, pb)
            if k and f"*:{k}" not in _RAPIDAPI_EMBEDDED_ODDS:
                print(f"[diag] sem odds: {pa} vs {pb} (chave {k})")
    return

    # (código antigo por tour — já não usado, mantido comentado abaixo)
    tours = {m.get("_tour") for m in matches if m.get("_tour")}
    for tour in tours:
        if tour in _RAPIDAPI_EVENT_INDEX_READY:
            continue

        events = _fetch_extend_upcoming_events(tour)
        matched = 0
        for event in events:
            p1 = event.get("player1") or {}
            p2 = event.get("player2") or {}
            n1, n2 = p1.get("name", ""), p2.get("name", "")
            if not n1 or not n2:
                continue
            # odds embutidas: preferir player.odd; fallback ao bloco odds.k1/k2
            def _odd(pl, kkey, ev):
                o = pl.get("odd")
                if o is None:
                    o = (ev.get("odds") or {}).get(kkey)
                try:
                    o = float(o)
                    return o if o > 1 else None
                except (TypeError, ValueError):
                    return None
            oa = _odd(p1, "k1", event)
            ob = _odd(p2, "k2", event)
            if oa is None or ob is None:
                continue
            # indexar por par de apelidos (tolerante à ordem). Guardamos com
            # prefixo de tour E numa chave global (sem tour), para o match
            # funcionar mesmo que o tour do fallback all-upcoming não bata.
            key = _odds_names_key(n1, n2)
            if key:
                registo = {"n1": n1, "n2": n2, "o1": oa, "o2": ob}
                _RAPIDAPI_EMBEDDED_ODDS[f"{tour}:{key}"] = registo
                _RAPIDAPI_EMBEDDED_ODDS.setdefault(f"*:{key}", registo)
                matched += 1

        _RAPIDAPI_EVENT_INDEX_READY.add(tour)
        n_tour = sum(1 for m in matches if m.get("_tour") == tour)
        print(f"[info] RapidAPI odds embutidas {tour}: {len(_RAPIDAPI_EMBEDDED_ODDS)} eventos indexados ({n_tour} jogos a cobrir).")


def _odds_names_key(n1: str, n2: str):
    """Chave estável por par de apelidos, independente da ordem."""
    def _sn(nome):
        toks = [t for t in str(nome).lower().replace(".", " ").split() if t.isalpha()]
        return toks[-1] if toks else str(nome).lower().strip()
    a, b = _sn(n1), _sn(n2)
    if not a or not b:
        return None
    return "|".join(sorted([a, b]))


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
    Obtém a Moneyline de um jogo pela RapidAPI. Estratégia robusta:
    1) ODDS EMBUTIDAS na lista upcoming (player.odd) — indexadas por apelidos.
       É a fonte principal: não depende de cruzar eventId (que falhava para
       alguns jogos) nem de uma segunda chamada.
    2) Fallback: endpoint recent-odds/get/{eventId}, se o eventId existir.
    Devolve {nome_jogador: odd} com os nomes do nosso jogo.
    """
    player_a = (match.get("player1") or {}).get("name", "")
    player_b = (match.get("player2") or {}).get("name", "")
    tour = match.get("_tour")

    # --- 1) odds embutidas (fonte principal) ---
    key = _odds_names_key(player_a, player_b)
    if key:
        # tenta a chave com tour; se falhar, a chave global (sem tour)
        emb = None
        if tour:
            emb = _RAPIDAPI_EMBEDDED_ODDS.get(f"{tour}:{key}")
        if not emb:
            emb = _RAPIDAPI_EMBEDDED_ODDS.get(f"*:{key}")
        if emb:
            # mapear as odds aos nomes do NOSSO jogo (a ordem pode diferir)
            def _sn(n):
                toks = [t for t in str(n).lower().replace(".", " ").split() if t.isalpha()]
                return toks[-1] if toks else str(n).lower().strip()
            if _sn(player_a) == _sn(emb["n1"]):
                odds = {player_a: emb["o1"], player_b: emb["o2"]}
            else:
                odds = {player_a: emb["o2"], player_b: emb["o1"]}
            print(f"[odds] {player_a} vs {player_b} | RapidAPI embutidas | {odds}")
            return odds

    # --- 2) fallback: recent-odds por eventId ---
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
        # (correção: repositório tennis_wta do Sackmann continua a devolver
        # 404 para todos os anos, confirmado por logs reais — ver histórico
        # do projeto. Deixámos de o tentar para o WTA: ia direto ao
        # tennis-data.co.uk, que é fiável e já funciona bem como fonte.
        # Poupa ~20 pedidos falhados por jogo WTA.)
        df = None
        source = "sackmann (desativado para wta)"

    if df is None or df.empty:
        if tour == "atp":
            df = _load_sackmann(tour, year)
            source = "sackmann"
        # para wta não tentamos o Sackmann de todo (ver nota acima) —
        # passamos direto ao tennis-data.co.uk abaixo.
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
_NAME_INDEX_CACHE: dict[tuple, dict[str, str]] = {}


def _normalize_name(name: str) -> str:
    if not name:
        return ""
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_name = "".join(c for c in nfkd if not unicodedata.combining(c))
    return ascii_name.lower().strip()


def _build_name_index(history: pd.DataFrame) -> dict[str, str]:
    """Índice nome_normalizado -> nome tal como aparece no histórico.
    Cacheado por CONTEÚDO (nº de linhas + colunas), não por id(history).

    CORREÇÃO CRÍTICA (15/08/2026, log real): a versão anterior usava
    id(history) como chave — o endereço de memória do objeto. Como o
    histórico é recarregado várias vezes ao longo de uma execução (uma
    nova instância de DataFrame a cada chamada a get_history), o Python
    pode REUTILIZAR o mesmo endereço de memória depois do DataFrame
    anterior ser libertado (garbage collection) — fazendo esta cache
    devolver por engano o índice de nomes DE OUTRO TOUR (ex: WTA a usar
    a cache construída para o ATP, onde nenhum nome WTA existe).
    Confirmado no log: resolve_player_name falhava para TODAS as
    jogadoras WTA, incluindo top-10 óbvias (Swiatek, Sabalenka, Gauff),
    o que só faz sentido com a cache "cruzada" entre tours. As colunas
    diferem sempre entre ATP (TennisMyLife) e WTA (tennis-data.co.uk),
    por isso usá-las na chave elimina a colisão."""
    key = (len(history), tuple(history.columns))
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

    CORREÇÃO (15/08/2026, log real): confirmado que resolve_player_name
    falhava para 100% das jogadoras WTA (incluindo top-10 óbvias tipo
    Swiatek/Sabalenka), mesmo sem acentos — descartando erro de
    acentuação. Suspeita forte (não 100% confirmada por falta de acesso
    direto aos dados brutos): a tennis-data.co.uk regista os nomes no
    formato "Apelido Inicial." (ex: "Swiatek I."), não "Nome Apelido"
    como as outras fontes — um formato estruturalmente diferente que
    nenhum limiar de correspondência aproximada resolve. Acrescentado um
    fallback específico para este formato, tentado só se os métodos
    normais falharem — não pode piorar nada, só ajudar se a suspeita
    estiver certa. Fica também um diagnóstico em main.py a mostrar
    amostras reais, para confirmar de vez se isto bastou.
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

    # Fallback: formato "Apelido Inicial." (ex: tennis-data.co.uk)
    # CORREÇÃO (16/08/2026, log real): antes assumia "apelido = última
    # palavra", o que falhava sistematicamente em apelidos compostos de
    # 2+ palavras (ex: "Jessica Bouzas Maneiro" — via só "Maneiro",
    # nunca batia com "Bouzas Maneiro J." no histórico). Agora usa
    # "apelido = tudo depois do primeiro nome", que lida com os dois casos.
    partes = normalized_input.split()
    if len(partes) >= 2:
        primeiro_nome = partes[0]
        apelido = " ".join(partes[1:])
        candidato = f"{apelido} {primeiro_nome[0]}"
        if candidato in index:
            return index[candidato]
        close2 = difflib.get_close_matches(candidato, index.keys(), n=1, cutoff=0.85)
        if close2:
            return index[close2[0]]

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


def compute_indoor_outdoor_stats(history: pd.DataFrame, player: str) -> Optional[dict]:
    """
    NOVO (14/08/2026, a pedido): performance indoor vs outdoor — alguns
    jogadores têm diferenças reais de rendimento consoante jogam coberto
    ou ao ar livre, mesmo dentro do MESMO tipo de piso (ex: hard indoor
    vs hard outdoor). Devolve {"indoor": {"matches","wins"} ou None,
    "outdoor": {...} ou None}.

    ATENÇÃO (não confirmado com dados reais ainda): a coluna que marca
    indoor/outdoor tem formato DIFERENTE consoante a fonte:
    - TennisMyLife (ATP): coluna "indoor", esperada 0/1 ou True/False.
    - tennis-data.co.uk (WTA): coluna "Court", esperada texto
      "Indoor"/"Outdoor" (esquema documentado publicamente desta fonte,
      mas nunca verificado ao vivo neste projeto — ver print de
      diagnóstico abaixo na primeira vez que houver dados).
    Esta função tenta as duas formas; se nenhuma bater certo, devolve
    None em vez de arriscar um valor errado.
    """
    if history.empty:
        return None
    resolved = resolve_player_name(history, player)
    if resolved is None:
        return None
    player = resolved

    played = history[(history["winner_name"] == player) | (history["loser_name"] == player)].copy()
    if played.empty:
        return None

    def _is_indoor(row) -> Optional[bool]:
        # CORREÇÃO CRÍTICA (15/08/2026, log real): a coluna 'indoor' da
        # TennisMyLife guarda LETRAS ("I"/"O"), não 0/1 como eu tinha
        # assumido sem confirmar. O int("O") rebentava com
        # "invalid literal for int() with base 10: 'O'" — e como isto
        # corre dentro do cálculo de fatores, DERRUBAVA A ANÁLISE DO JOGO
        # INTEIRO (confirmado: 32/32 jogos ATP falharam nesta execução).
        # Agora trata letras, texto e números, e nunca deixa uma surpresa
        # nos dados derrubar o jogo — no pior caso devolve None
        # ("sem dados"), nunca uma exceção.
        try:
            if "indoor" in played.columns:
                v = row.get("indoor")
                if pd.isna(v):
                    return None
                if isinstance(v, bool):
                    return v
                if isinstance(v, str):
                    s = v.strip().upper()
                    if s in ("I", "INDOOR", "1", "TRUE"):
                        return True
                    if s in ("O", "OUTDOOR", "0", "FALSE"):
                        return False
                    return None
                return bool(int(v))
            if "Court" in played.columns:
                v = row.get("Court")
                if not isinstance(v, str):
                    return None
                v = v.strip().lower()
                if v == "indoor":
                    return True
                if v == "outdoor":
                    return False
                return None
        except (ValueError, TypeError):
            return None
        return None
        return None

    played["_indoor"] = played.apply(_is_indoor, axis=1)
    if played["_indoor"].isna().all():
        # nenhuma das duas colunas deu um valor utilizável — diagnóstico
        # para confirmar isto com dados reais, sem adivinhar mais.
        cols_relevantes = [c for c in ("indoor", "Court") if c in played.columns]
        print(f"[diag:indoor] {player}: colunas presentes {cols_relevantes}, "
              f"mas nenhum valor interpretável — ver amostra: "
              f"{played[cols_relevantes].head(3).to_dict('records') if cols_relevantes else 'nenhuma coluna'}")
        return None

    result: dict = {}
    for chave, valor in (("indoor", True), ("outdoor", False)):
        subset = played[played["_indoor"] == valor]
        if subset.empty:
            result[chave] = None
            continue
        wins = int((subset["winner_name"] == player).sum())
        result[chave] = {"matches": len(subset), "wins": wins, "losses": len(subset) - wins}

    if result.get("indoor") is None and result.get("outdoor") is None:
        return None
    return result


def compute_recent_form(history: pd.DataFrame, player: str, n_matches: int,
                        window_days: Optional[int] = None) -> Optional[dict]:
    """Forma recente do jogador (qualquer piso). None se não há dados.

    CORREÇÃO (14/08/2026, a pedido): antes usava sempre os últimos
    n_matches jogos (contagem), o que podia significar 3 semanas para um
    jogador muito ativo ou 2-3 meses para um pouco ativo — não capta bem
    "como está a jogar ULTIMAMENTE". Com `window_days` definido, usa
    antes uma JANELA DE TEMPO (ex: últimos 45 dias); se houver poucos
    jogos nessa janela (jogador pouco ativo), cai para os últimos
    n_matches como rede de segurança, para nunca ficar sem dados.
    """
    if history.empty or "winner_name" not in history.columns:
        return None

    resolved = resolve_player_name(history, player)
    if resolved is None:
        return None
    player = resolved

    played = history[(history["winner_name"] == player) | (history["loser_name"] == player)].copy()
    if played.empty:
        return None

    if "tourney_date" in played.columns:
        played = played.sort_values("tourney_date")

    if window_days is not None and "tourney_date" in played.columns:
        played["_date"] = pd.to_datetime(played["tourney_date"], format="%Y%m%d", errors="coerce")
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=window_days)
        janela = played[played["_date"] >= cutoff]
        if len(janela) >= max(3, n_matches // 3):  # amostra mínima na janela
            played = janela
        else:
            played = played.tail(n_matches)  # fallback: pouca atividade recente
    else:
        played = played.tail(n_matches)

    wins = int((played["winner_name"] == player).sum())
    return {"matches": len(played), "wins": wins, "losses": len(played) - wins}


def compute_recent_quality_wins(history: pd.DataFrame, player: str,
                                window_days: int = 90) -> Optional[dict]:
    """
    NOVO (14/08/2026, a pedido): pontuação de QUALIDADE das vitórias
    recentes — capta um jogador "em explosão" (bate cabeças de série
    mesmo com registo win/loss modesto) que a forma recente por si só
    não mostra. Ex: Navone vs Collignon — indicadores gerais estavam
    todos para o Collignon, mas o Navone vinha de bater vários top-20.

    Para cada vitória do jogador nos últimos `window_days` dias, soma
    pontos consoante o ranking do adversário BATIDO nessa altura:
    top-10 = 3 pontos, top-20 = 2, top-50 = 1, resto = 0 (graduado, não
    um limiar único — bater um #3 vale mais que bater um #45).

    Gratuito — usa o histórico local que já temos (winner_rank/loser_rank),
    sem chamadas à API. Não depende do orçamento "rich" (que é limitado
    e às vezes indisponível).
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
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=window_days)
    janela = played[played["_date"] >= cutoff]
    if janela.empty:
        return {"score": 0, "top10_wins": 0, "top20_wins": 0, "top50_wins": 0, "matches": 0}

    vitorias = janela[janela["winner_name"] == player]
    if "loser_rank" not in vitorias.columns or vitorias.empty:
        return {"score": 0, "top10_wins": 0, "top20_wins": 0, "top50_wins": 0, "matches": len(janela)}

    def _pontos(rank):
        if pd.isna(rank):
            return 0
        rank = int(rank)
        if rank <= 10:
            return 3
        if rank <= 20:
            return 2
        if rank <= 50:
            return 1
        return 0

    ranks_batidos = vitorias["loser_rank"].dropna()
    score = int(sum(_pontos(r) for r in ranks_batidos))
    top10 = int((ranks_batidos <= 10).sum())
    top20 = int((ranks_batidos <= 20).sum())
    top50 = int((ranks_batidos <= 50).sum())
    return {"score": score, "top10_wins": top10, "top20_wins": top20,
            "top50_wins": top50, "matches": len(janela)}


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
    result["sets_last_7d"] = sets_played_7d  # alias (nome usado pelo motor)
    # Sets do ÚLTIMO jogo especificamente (para o motor detetar "jogo
    # longo recente" — auditoria 11/08/2026, mesmo campo em falta que na
    # versão api_recent).
    last_match_sets = None
    if not past_matches.empty and "score" in past_matches.columns:
        _last_idx = past_matches["tourney_date"].idxmax()
        last_match_sets = _count_sets(past_matches.loc[_last_idx, "score"])
    result["last_match_sets"] = last_match_sets
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


def _first_set_winner_from_cols(w1, l1) -> Optional[bool]:
    """Equivalente a _first_set_winner_is_match_winner, mas para o formato
    de colunas separadas por set (tennis-data.co.uk/WTA: W1/L1), em vez do
    score combinado (Sackmann/TennisMyLife/ATP). NOTA: W1/L1 é sempre do
    lado do vencedor do JOGO (mesma convenção do score combinado)."""
    if pd.isna(w1) or pd.isna(l1):
        return None
    try:
        w1, l1 = int(w1), int(l1)
    except (ValueError, TypeError):
        return None
    if w1 == l1:
        return None
    return w1 > l1


def compute_set1_comeback_stats(history: pd.DataFrame, player: str) -> Optional[dict]:
    """
    Entre os jogos em que o jogador PERDEU o 1º set, em quantos ainda
    assim ganhou o jogo? Separado por melhor-de-3 (Masters/500) e
    melhor-de-5 (Slams), porque a taxa de recuperação é estruturalmente
    diferente nos dois formatos. None se não houver dados suficientes.

    CORREÇÃO (14/08/2026, a pedido): antes exigia a coluna 'score'
    (só existe no formato ATP/TennisMyLife) — para WTA (tennis-data.co.uk,
    sem 'score', só W1/L1/W2/L2/W3/L3) devolvia sempre None. Passa a
    suportar as duas formas.
    """
    if history.empty or "best_of" not in history.columns:
        return None
    usa_score = "score" in history.columns
    usa_w1l1 = {"W1", "L1"}.issubset(history.columns)
    if not usa_score and not usa_w1l1:
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
            if usa_score:
                set1_winner_is_match_winner = _first_set_winner_is_match_winner(row.get("score"))
            else:
                set1_winner_is_match_winner = _first_set_winner_from_cols(row.get("W1"), row.get("L1"))
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


# Limite de jogos históricos processados por jogadora na reconstrução via
# perfis (WTA) — evita picos de custo na primeira execução (cache vazio),
# quando cada adversária nova custa 1 pedido à RapidAPI. Com o tempo, a
# cache permanente (a mão nunca muda) faz o custo tender para zero.
MAX_JOGOS_RECONSTRUCAO_MAO = 80


def _hand_cache_path(tour: str, player_name: str):
    """Caminho da cache de mão por NOME normalizado — partilhado entre
    _get_cached_hand_by_name (consulta durante a análise) e
    warm_up_hand_cache (pré-aquecimento pelo ranking) para garantir que os
    DOIS escrevem/leem exatamente a mesma chave. Extraído para função
    própria de propósito — este projeto já teve vários bugs de chaves
    trocadas entre quem escreve e quem lê dados; partilhar a lógica evita
    reintroduzir o mesmo problema aqui.

    CORREÇÃO CRÍTICA (16/08/2026, log real): a cache de "não encontrada"
    nunca expira (a mão não muda) — mas isso significa que qualquer nome
    marcado como "não encontrado" ANTES de melhorarmos a lógica de
    correspondência (formato "Apelido I." -> ranking oficial) ficava
    PRESO nesse estado para sempre, mesmo depois da lógica melhorar.
    Confirmado no log: 0/80 adversárias resolvidas para TODAS as
    jogadoras WTA, incluindo casos óbvios (Swiatek, Sabalenka) que a
    lógica nova resolveria sem problema — só não chegavam lá porque a
    cache antiga "envenenada" respondia primeiro. O prefixo da cache
    mudou de "hand_by_name" para "hand_by_name_v2": invalida
    automaticamente todas as entradas antigas (ficam simplesmente por
    usar, sem precisar de as apagar à mão), e esta execução recomeça do
    zero com a lógica corrigida."""
    key = (_normalize_name(player_name) or "desconhecido").replace(" ", "_")
    tour_key = str(tour).strip().lower()
    return _PLAYER_CACHE_STORE.entity_path("hand_by_name_v2", tour_key, f"{key}.json")


def _read_cached_hand(tour: str, player_name: str) -> Optional[str]:
    """None = nunca foi tentado; "" = já tentado, sem perfil encontrado;
    "L"/"R" = mão conhecida. Ver _hand_cache_path."""
    try:
        return _PLAYER_CACHE_STORE.get_entry(
            _hand_cache_path(tour, player_name), "hand", max_age_hours=24 * 365 * 5)
    except (OSError, TypeError, ValueError):
        return None


def _write_cached_hand(tour: str, player_name: str, hand: Optional[str]) -> None:
    try:
        _PLAYER_CACHE_STORE.set_entry(
            _hand_cache_path(tour, player_name), "hand", hand or "",
            metadata={"tour": str(tour).strip().lower(), "name": player_name})
    except (OSError, TypeError, ValueError):
        pass


def fetch_player_profile_by_id(tour: str, player_id: int) -> Optional[dict]:
    """Endpoint /tennis/v2/{tour}/player/profile/{id} — perfil por ID
    (confirmado real, 13/08/2026: devolve corretamente jogador do tour
    pedido, com a mão em data.information.plays, mesmo formato que
    fetch_player_profile/compute_hand_from_profile já sabem ler). Ao
    contrário de fetch_player_profile (por nome), não precisa de
    resolver grafia — usado no pré-aquecimento a partir do ranking
    oficial, que já dá o ID diretamente."""
    tour_key = str(tour).strip().lower()
    cache_key = f"{tour_key}:{player_id}"
    cached = _PROFILE_CACHE.get(cache_key)
    if cached is not None:
        age = (datetime.now(timezone.utc) - cached["fetched_at"]).total_seconds() / 3600
        if age < 24 * 30:
            return cached["data"]
    if not RAPIDAPI_KEY:
        return None
    url = f"{RAPIDAPI_BASE}/{tour_key}/player/profile/{int(player_id)}"
    try:
        resp = _rapidapi_get(url)
        resp.raise_for_status()
        data = resp.json()
        _PROFILE_CACHE[cache_key] = {"fetched_at": datetime.now(timezone.utc), "data": data}
        return data
    except requests.RequestException as exc:
        print(f"[aviso] falha a obter profile por ID ({tour_key}, {player_id}): {exc}")
        return None


def warm_up_hand_cache(tour: str = "wta", top_n: int = 200) -> dict:
    """
    Pré-aquecimento da cache de mão (permanente) a partir do RANKING
    OFICIAL — em vez de esperar que cada adversária apareça organicamente
    num jogo (e só aí gastar o pedido), resolve de uma vez a mão das
    top_n jogadoras do ranking. Depois disto, a esmagadora maioria dos
    jogos WTA já tem a mão das duas jogadoras em cache ANTES do primeiro
    jogo ser analisado.

    Usa o ID do ranking oficial diretamente (fetch_player_profile_by_id)
    — não precisa de resolver nomes por grafia. Só WTA precisa disto (ATP
    já tem a mão embutida no histórico local, sem custo de API nenhum —
    ver compute_handedness_matchup_stats).

    Pensado para correr à parte do fluxo normal do bot (manual ou
    agendado, ex: semanal) — não faz parte de main.py. Respeita o
    circuit breaker (rapidapi_budget_exceeded) e para mais cedo se o
    orçamento acabar, devolvendo o que já conseguiu.
    """
    tour_key = str(tour).strip().lower()
    resumo = {"total_ranking": 0, "ja_em_cache": 0, "resolvidas_agora": 0,
              "sem_perfil": 0, "parou_por_orcamento": False}
    ranking = fetch_official_ranking(tour_key)
    if not ranking:
        print(f"[aviso] pré-aquecimento {tour_key}: ranking oficial indisponível.")
        return resumo

    # ordena por posição, do #1 para baixo, até top_n
    entradas = sorted(
        ((info.get("rank") or 9999, key, info.get("player_id"))
         for key, info in ranking.items() if info.get("player_id")),
        key=lambda t: t[0],
    )[:top_n]
    resumo["total_ranking"] = len(entradas)

    for _rank, normalized_key, player_id in entradas:
        if rapidapi_budget_exceeded():
            resumo["parou_por_orcamento"] = True
            print(f"[aviso] pré-aquecimento {tour_key}: orçamento RapidAPI esgotado, "
                  f"parado em {resumo['resolvidas_agora']} jogadoras novas.")
            break
        # já em cache? (reaproveita _hand_cache_path — a MESMA função usada
        # por _get_cached_hand_by_name — para garantir que as duas leem e
        # escrevem exatamente a mesma chave. BUG APANHADO EM TESTE
        # 13/08/2026: a primeira versão construía o caminho aqui à parte,
        # sem aplicar `.replace(" ", "_")` como _hand_cache_path faz —
        # a cache escrita aqui nunca era encontrada por quem a consultava
        # depois. Corrigido para usar sempre a função partilhada.
        path = _hand_cache_path(tour_key, normalized_key)
        try:
            existente = _PLAYER_CACHE_STORE.get_entry(path, "hand", max_age_hours=24 * 365 * 5)
        except (OSError, TypeError, ValueError):
            existente = None
        if existente is not None:
            resumo["ja_em_cache"] += 1
            continue
        profile = fetch_player_profile_by_id(tour_key, player_id)
        hand = compute_hand_from_profile(profile) if profile else None
        _write_cached_hand(tour_key, normalized_key, hand)
        if hand:
            resumo["resolvidas_agora"] += 1
        else:
            resumo["sem_perfil"] += 1

    print(f"[info] pré-aquecimento {tour_key}: {resumo['resolvidas_agora']} novas, "
          f"{resumo['ja_em_cache']} já em cache, {resumo['sem_perfil']} sem perfil "
          f"(de {resumo['total_ranking']} no ranking).")
    return resumo


def _match_abbreviated_name_to_ranking(name: str, ranking: dict) -> Optional[dict]:
    """
    NOVO (15/08/2026, log real): o histórico WTA (tennis-data.co.uk) grava
    os nomes em formato "Apelido Inicial." (ex: "Sabalenka A."), mas o
    ranking oficial (fetch_official_ranking) tem nomes completos
    ("Aryna Sabalenka") — sem esta ponte, qualquer adversária vinda do
    histórico nunca batia certo com o ranking, e a chamada por nome à
    RapidAPI falhava sempre (o endpoint não reconhece o formato abreviado).
    Procura por apelido + inicial do primeiro nome. Devolve a entrada do
    ranking (com "player_id") ou None.
    """
    if not ranking:
        return None
    normalized = _normalize_name(name)
    if normalized in ranking:
        return ranking[normalized]
    # CORREÇÃO (16/08/2026, log real): só tratava exatamente 2 palavras
    # ("Sabalenka A."), falhando sempre em apelidos compostos de 3+
    # palavras ("Bouzas Maneiro J."). Agora: a última palavra é sempre a
    # inicial, tudo antes é o apelido (pode ter várias palavras) — e o
    # mesmo do lado do nome completo (tudo depois da primeira palavra).
    partes_abrev = normalized.split()
    if len(partes_abrev) >= 2:
        inicial_abrev = partes_abrev[-1].rstrip(".")  # "a." -> "a" (_normalize_name não remove o ponto)
        if len(inicial_abrev) == 1:
            apelido_abrev = " ".join(partes_abrev[:-1])
            for chave_completa, info in ranking.items():
                partes_completa = chave_completa.split()
                if len(partes_completa) >= 2:
                    inicial_completo = partes_completa[0][0]
                    apelido_completo = " ".join(partes_completa[1:])
                    if apelido_completo == apelido_abrev and inicial_completo == inicial_abrev:
                        return info
    return None


def _get_cached_hand_by_name(tour: str, player_name: str) -> Optional[str]:
    """Mão do jogador (L/R) com CACHE PERMANENTE por nome — a mão nunca
    muda ao longo da carreira, ao contrário de estatísticas dinâmicas, por
    isso esta cache não expira (max_age_hours muito alto). Usa
    fetch_player_profile (já existente, funciona por NOME, não precisa de
    ID) só na primeira vez que um nome aparece; depois fica gravado para
    sempre — o custo desta função tende a zero à medida que o circuito vai
    sendo coberto (inclusive pelo pré-aquecimento, ver warm_up_hand_cache).
    Também grava "não encontrada" (string vazia) para não repetir pedidos
    a nomes sem perfil disponível.

    CORREÇÃO (15/08/2026, log real): confirmado que a reconstrução WTA
    falhava 100% das vezes — o nome do adversário vem do histórico local
    em formato abreviado ("Sabalenka A."), que a RapidAPI não reconhece
    por nome. Agora tenta primeiro traduzir esse formato para o nome
    completo via ranking oficial (que tem ID), e só cai para a busca por
    nome se isso falhar (ex: jogadora fora do ranking carregado)."""
    cached = _read_cached_hand(tour, player_name)
    if cached is not None:
        return cached or None
    if not RAPIDAPI_KEY or rapidapi_budget_exceeded():
        return None

    hand = None
    ranking = fetch_official_ranking(tour)
    match = _match_abbreviated_name_to_ranking(player_name, ranking) if ranking else None
    if match and match.get("player_id"):
        profile = fetch_player_profile_by_id(tour, match["player_id"])
        hand = compute_hand_from_profile(profile) if profile else None

    if hand is None:
        profile = fetch_player_profile(player_name)
        hand = compute_hand_from_profile(profile) if profile else None

    _write_cached_hand(tour, player_name, hand)
    return hand


def compute_handedness_matchup_stats_via_profiles(history: pd.DataFrame, player: str, tour: str) -> Optional[dict]:
    """
    Alternativa a compute_handedness_matchup_stats para quando o histórico
    NÃO tem colunas winner_hand/loser_hand — o caso do WTA: a única fonte
    (tennis-data.co.uk) nunca teve essas colunas, e o repositório
    JeffSackmann/tennis_wta desapareceu POR COMPLETO (confirmado 13/08/2026,
    404 no repositório inteiro, não só nos ficheiros por ano).

    Em vez de pedir "mão do adversário em cada jogo" a uma API limitada
    (past-matches só devolve ~10 jogos, sem paginação — confirmado na
    Playground), usa o HISTÓRICO COMPLETO multi-ano que já temos, e resolve
    a mão de cada ADVERSÁRIA por nome via fetch_player_profile — com cache
    PERMANENTE (ver _get_cached_hand_by_name), por isso o custo tende a
    zero com o tempo. Limitado a MAX_JOGOS_RECONSTRUCAO_MAO jogos mais
    recentes por precaução (picos de custo na primeira execução).
    """
    if history.empty:
        return None
    resolved = resolve_player_name(history, player)
    if resolved is None:
        return None
    played = history[(history["winner_name"] == resolved) | (history["loser_name"] == resolved)].copy()
    if played.empty:
        return None
    if "tourney_date" in played.columns:
        played = played.sort_values("tourney_date", ascending=False)
    played = played.head(MAX_JOGOS_RECONSTRUCAO_MAO)

    played["_opponent_name"] = played.apply(
        lambda row: row["loser_name"] if row["winner_name"] == resolved else row["winner_name"], axis=1
    )

    tally = {"L": {"wins": 0, "matches": 0}, "R": {"wins": 0, "matches": 0}}
    _tentados = 0
    _resolvidos = 0
    for _, row in played.iterrows():
        if rapidapi_budget_exceeded():
            break  # circuit breaker: para a reconstrução, devolve o que já tem
        _tentados += 1
        hand = _get_cached_hand_by_name(tour, row["_opponent_name"])
        if hand not in ("L", "R"):
            continue
        _resolvidos += 1
        tally[hand]["matches"] += 1
        if row["winner_name"] == resolved:
            tally[hand]["wins"] += 1

    # DIAGNÓSTICO (15/08/2026, a pedido — matchup de mão continua a falhar
    # muito no WTA mesmo depois da tradução via ranking). Mostra um nome
    # real que foi tentado e falhou, para ver exatamente o formato.
    if _tentados > 0 and _resolvidos == 0:
        _exemplo = played["_opponent_name"].iloc[0] if not played.empty else None
        print(f"[diag:mao-detalhe] {player} ({tour}): {_tentados} adversárias "
              f"tentadas, 0 resolvidas — exemplo de nome tentado: {_exemplo!r}")

    result: dict = {}
    for hand_code, label in (("L", "vs_left_handed"), ("R", "vs_right_handed")):
        m = tally[hand_code]["matches"]
        result[label] = ({"matches": m, "wins": tally[hand_code]["wins"], "losses": m - tally[hand_code]["wins"]}
                         if m > 0 else None)
    if result.get("vs_left_handed") is None and result.get("vs_right_handed") is None:
        return None
    return result


def compute_handedness_matchup_stats(history: pd.DataFrame, player: str, tour: Optional[str] = None) -> Optional[dict]:
    """
    Taxa de vitória do jogador especificamente contra adversários canhotos
    vs destros — alguns jogadores têm dificuldade estilística real contra
    canhotos, independentemente do nível geral. Usa as colunas
    'winner_hand'/'loser_hand' já presentes no histórico ('L'/'R'/'U').

    Se o histórico não tiver essas colunas (caso do WTA) e `tour` for
    passado, cai automaticamente na reconstrução via perfis
    (compute_handedness_matchup_stats_via_profiles) — ver essa função.
    """
    required_cols = {"winner_hand", "loser_hand"}
    if history.empty or not required_cols.issubset(history.columns):
        if tour:
            return compute_handedness_matchup_stats_via_profiles(history, player, tour)
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


def compute_tiebreak_stats(history: pd.DataFrame, player: str) -> Optional[dict]:
    """
    NOVO (14/08/2026, a pedido): taxa de vitória em TIE-BREAKS especificamente
    — competência à parte da resiliência em sets decisivos (essa mede o set
    inteiro; esta mede só o desempate de 7 pontos, uma habilidade mais
    estreita e distinta). Suporta as duas formas do histórico:
    - 'score' combinado (TennisMyLife/ATP, ex: '7-6(3) 4-6 6-4').
    - colunas separadas por set (tennis-data.co.uk/WTA: W1/L1/W2/L2/W3/L3).
    Um set só conta como tie-break se o resultado for 7-6 ou 6-7 (não conta
    super-tiebreaks de 3º set tipo "1-0(10)", que têm regras diferentes).
    """
    if history.empty:
        return None
    resolved = resolve_player_name(history, player)
    if resolved is None:
        return None
    player = resolved
    played = history[(history["winner_name"] == player) | (history["loser_name"] == player)]
    if played.empty:
        return None

    tb_won = tb_played = 0

    if "score" in played.columns:
        for _, row in played.iterrows():
            is_winner = row.get("winner_name") == player
            score = row.get("score")
            if not isinstance(score, str):
                continue
            for token in score.strip().split():
                base = token.split("(")[0]
                parts = base.split("-")
                if len(parts) != 2:
                    continue
                try:
                    gw, gl = int(parts[0]), int(parts[1])
                except ValueError:
                    continue
                if {gw, gl} != {6, 7}:
                    continue
                tb_played += 1
                jogo_venceu_tb = (gw == 7)
                if is_winner == jogo_venceu_tb:
                    tb_won += 1
    elif {"W1", "L1", "W2", "L2", "W3", "L3"}.issubset(played.columns):
        for _, row in played.iterrows():
            is_winner = row.get("winner_name") == player
            for wc, lc in (("W1", "L1"), ("W2", "L2"), ("W3", "L3")):
                gw, gl = row.get(wc), row.get(lc)
                if pd.isna(gw) or pd.isna(gl):
                    continue
                try:
                    gw, gl = int(gw), int(gl)
                except (ValueError, TypeError):
                    continue
                if {gw, gl} != {6, 7}:
                    continue
                tb_played += 1
                jogo_venceu_tb = (gw == 7)
                if is_winner == jogo_venceu_tb:
                    tb_won += 1
    else:
        return None

    if tb_played == 0:
        return None
    return {"matches": tb_played, "wins": tb_won, "losses": tb_played - tb_won}


def compute_seasonal_form(history: pd.DataFrame, player: str,
                          reference_date: Optional[datetime] = None) -> Optional[dict]:
    """
    NOVO (14/08/2026, a pedido): como o jogador costuma jogar NESTA ALTURA
    DO ANO, em anos anteriores — ex: um jogador pode declinar sempre no
    final da época mas ser forte no swing de piso duro americano
    (Indian Wells/Miami), mesmo sendo o mesmo tipo de piso o ano todo; a
    diferença é mesmo a altura do calendário (fadiga acumulada, condições,
    etc.). Usa uma janela de ±21 dias à volta da MESMA DATA do calendário,
    em anos ANTERIORES ao atual (nunca o ano a decorrer — isso já é
    coberto por forma_recente/qualidade_vitorias; misturar os dois
    duplicava o sinal). Alarga a janela se a amostra ficar pequena.
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
    played = played.dropna(subset=["_date"])
    if played.empty:
        return None

    ref = reference_date or datetime.now(timezone.utc).replace(tzinfo=None)
    ref_doy = ref.timetuple().tm_yday

    def _dentro_janela(data, largura_dias):
        doy = data.timetuple().tm_yday
        diff = abs(doy - ref_doy)
        diff = min(diff, 365 - diff)  # circular: dezembro está "perto" de janeiro
        return diff <= largura_dias

    subset = played.iloc[0:0]  # vazio, tipo certo
    for largura in (21, 35, 50):
        cand = played[played["_date"].apply(lambda d: _dentro_janela(d, largura))]
        cand = cand[cand["_date"].dt.year < ref.year]
        if len(cand) >= 5:
            subset = cand
            break
        subset = cand  # guarda o último (mais largo) mesmo que pequeno

    if subset.empty:
        return None
    wins = int((subset["winner_name"] == player).sum())
    return {"matches": len(subset), "wins": wins, "losses": len(subset) - wins}


def compute_ranking_evolution(history: pd.DataFrame, player: str,
                              current_points: Optional[float],
                              reference_date: Optional[datetime] = None) -> Optional[dict]:
    """
    NOVO (14/08/2026, a pedido): evolução do ranking em PONTOS (não
    posição) nos últimos 6 e 12 meses — comparar posições não é linear
    (subir de #2 para #1 é um salto de qualidade muito maior do que subir
    de #100 para #80; os pontos captam isso, a posição não). Usa
    winner_rank_points/loser_rank_points do histórico local (o ranking do
    jogador NA ALTURA de cada jogo passado) para encontrar o valor mais
    próximo de há 6 e 12 meses, e compara com os pontos ATUAIS (do
    ranking oficial ao vivo, passado como `current_points`).
    """
    if not current_points or history.empty or "tourney_date" not in history.columns:
        return None
    resolved = resolve_player_name(history, player)
    if resolved is None:
        return None
    player = resolved
    played = history[(history["winner_name"] == player) | (history["loser_name"] == player)].copy()
    if played.empty:
        return None
    played["_date"] = pd.to_datetime(played["tourney_date"], format="%Y%m%d", errors="coerce")
    played = played.dropna(subset=["_date"])
    if played.empty:
        return None

    def _points_at(row):
        return row["winner_rank_points"] if row["winner_name"] == player else row["loser_rank_points"]

    if "winner_rank_points" not in played.columns or "loser_rank_points" not in played.columns:
        return None
    played["_points"] = played.apply(_points_at, axis=1)
    played = played.dropna(subset=["_points"])
    if played.empty:
        return None

    ref = reference_date or datetime.now(timezone.utc).replace(tzinfo=None)

    def _pontos_ha(dias):
        alvo = ref - timedelta(days=dias)
        diffs = (played["_date"] - alvo).abs()
        idx = diffs.idxmin()
        # só aceita se o jogo mais próximo estiver razoavelmente perto da
        # data alvo (não mais de 45 dias) — senão arrisca comparar com um
        # valor de há muito mais tempo (jogador esteve parado nessa altura)
        if diffs.loc[idx] > timedelta(days=45):
            return None
        return float(played.loc[idx, "_points"])

    pontos_6m = _pontos_ha(182)
    pontos_12m = _pontos_ha(365)
    if pontos_6m is None and pontos_12m is None:
        return None

    result = {"current": current_points, "points_6m_ago": pontos_6m, "points_12m_ago": pontos_12m}
    if pontos_6m and pontos_6m > 0:
        result["change_6m_pct"] = round(100 * (current_points - pontos_6m) / pontos_6m, 1)
    if pontos_12m and pontos_12m > 0:
        result["change_12m_pct"] = round(100 * (current_points - pontos_12m) / pontos_12m, 1)
    return result


# ===== VELOCIDADE DO PISO (Court Pace Index) — 14/08/2026, a pedido =====
#
# Fonte: courtspeed.com (Court Pace Index, Hawk-Eye, 2012-2026). Cobertura
# CONFIRMADA limitada a Grand Slams + Masters 1000 + ATP Finals — sem WTA
# dedicado, sem ATP 250/500 (ver investigação 14/08/2026). A folha de
# cálculo subjacente ("The Racquet ATP Court Speed Database") só é
# gratuita para LEITURA na página pública do site — a exportação em massa
# é paga (subscrição). Por isso esta tabela é MANTIDA MANUALMENTE — os
# valores abaixo são os publicamente visíveis em courtspeed.com/hard a
# 14/08/2026 (piso duro; terra batida e relva têm páginas próprias,
# ainda por acrescentar aqui). Atualizar de vez em quando copiando do site.
#
# Categorias oficiais do CPI (courtspeed.com): <30 lento, 30-34
# médio-lento, 35-39 médio, 40-44 médio-rápido, >44 rápido.
COURT_PACE_INDEX: dict = {
    "indian wells": {2016: 30, 2017: 27.4, 2018: 27.9, 2019: 32.1, 2021: 32,
                      2023: 35.4, 2024: 36.9, 2025: 30.9, 2026: 39.3},
    "miami": {2013: 31.5, 2014: 29.8, 2015: 31.2, 2016: 33.1, 2017: 33.8,
              2018: 30.4, 2019: 36.5, 2023: 40.6, 2024: 35.5, 2025: 40.7, 2026: 39.2},
    "canadian open": {2016: 35.2, 2017: 36.3, 2018: 28.8, 2019: 42.8, 2021: 42.4,
                       2022: 39.5, 2023: 41.2, 2024: 37.8, 2025: 44.6, 2026: 35.4},
    "cincinnati": {2016: 35.1, 2017: 33.6, 2018: 31.6, 2019: 37.4, 2021: 43,
                    2022: 38.6, 2023: 33.2, 2024: 42.5, 2025: 43, 2026: 37.4},
    "shanghai": {2016: 44.1, 2017: 42.9, 2018: 40, 2019: 40.9, 2023: 40.1, 2024: 40.8, 2025: 32.8},
    "paris": {2012: 32.2, 2013: 31.2, 2014: 31.8, 2015: 29.9, 2016: 39.1, 2017: 37.5,
              2018: 34.6, 2019: 40.6, 2021: 37.1, 2022: 37.1, 2023: 40.4, 2024: 45.5, 2025: 35.1},
    "atp finals": {2012: 34.1, 2013: 33.9, 2014: 34, 2015: 34.6, 2016: 42.1, 2017: 42.1,
                    2018: 40.3, 2019: 41.6, 2020: 36.7, 2021: 39.9, 2022: 43.2, 2023: 43.8,
                    2024: 39.9, 2025: 40.1},
    "monte carlo": {2016: 23.7, 2017: 24.9, 2018: 22.1, 2019: 30.3, 2023: 30,
                     2024: 29.1, 2025: 29, 2026: 27.1},
    "madrid": {2016: 22.5, 2017: 20.9, 2018: 21.6, 2019: 27.9, 2023: 26.6,
               2024: 27, 2025: 26.1, 2026: 29.8},
    "rome": {2016: 24, 2017: 22, 2018: 18.9, 2023: 28.6, 2024: 29.3, 2025: 28.9, 2026: 25.4},
    "australian open": {2017: 42, 2020: 43, 2021: 50},
    "roland garros": {2017: 21},
    "wimbledon": {2017: 37},
    "us open": {2017: 35.7, 2020: 43, 2024: 42.8},
}

# Nomes alternativos -> chave canónica em COURT_PACE_INDEX (para bater
# certo com os nomes de torneio como aparecem no NOSSO histórico, que
# podem diferir dos usados no courtspeed.com).
_CPI_NOME_ALIASES = {
    "bnp paribas open": "indian wells", "indian wells masters": "indian wells",
    "miami open": "miami", "sony ericsson open": "miami",
    "national bank open": "canadian open", "rogers cup": "canadian open",
    "montreal": "canadian open", "toronto": "canadian open",
    "cincinnati open": "cincinnati", "western southern open": "cincinnati",
    "shanghai masters": "shanghai", "rolex shanghai masters": "shanghai",
    "paris masters": "paris", "rolex paris masters": "paris", "bercy": "paris",
    "nitto atp finals": "atp finals", "tour finals": "atp finals",
    "monte carlo masters": "monte carlo", "rolex monte carlo masters": "monte carlo",
    "mutua madrid open": "madrid", "madrid open": "madrid",
    "internazionali bnl d'italia": "rome", "italian open": "rome", "rome masters": "rome",
    "australian open": "australian open", "roland garros": "roland garros",
    "french open": "roland garros", "wimbledon": "wimbledon", "us open": "us open",
}


def _normalize_tournament_name(name) -> Optional[str]:
    if not isinstance(name, str) or not name.strip():
        return None
    n = _normalize_name(name)  # já existe: lowercase, sem acentos
    if n in COURT_PACE_INDEX:
        return n
    if n in _CPI_NOME_ALIASES:
        return _CPI_NOME_ALIASES[n]
    for alias, canon in _CPI_NOME_ALIASES.items():
        if alias in n or n in alias:
            return canon
    return None


def _cpi_bucket(cpi: float) -> str:
    if cpi < 30:
        return "slow"
    if cpi < 35:
        return "medium_slow"
    if cpi < 40:
        return "medium"
    if cpi < 45:
        return "medium_fast"
    return "fast"


def lookup_court_pace(tournament_name, year: Optional[int]) -> Optional[dict]:
    """Devolve {"cpi": float, "bucket": str, "ano_usado": int} para o
    torneio/ano pedido, ou o ano mais próximo disponível na tabela (até 2
    anos de diferença) se o exato não existir. None se o torneio não
    estiver na tabela (a maioria — cobertura limitada, ver nota acima)."""
    canon = _normalize_tournament_name(tournament_name)
    if canon is None:
        return None
    anos = COURT_PACE_INDEX.get(canon) or {}
    if not anos:
        return None
    if year is not None and year in anos:
        cpi = anos[year]
        return {"cpi": cpi, "bucket": _cpi_bucket(cpi), "ano_usado": year}
    if year is not None:
        proximos = sorted(anos.keys(), key=lambda y: abs(y - year))
        for y in proximos:
            if abs(y - year) <= 2:
                cpi = anos[y]
                return {"cpi": cpi, "bucket": _cpi_bucket(cpi), "ano_usado": y}
        return None
    # sem ano pedido: usa o mais recente disponível
    y = max(anos.keys())
    cpi = anos[y]
    return {"cpi": cpi, "bucket": _cpi_bucket(cpi), "ano_usado": y}


def compute_court_speed_form(history: pd.DataFrame, player: str, current_bucket: str) -> Optional[dict]:
    """
    Performance do jogador especificamente no MESMO balde de velocidade de
    piso (lento/médio-lento/médio/médio-rápido/rápido) do jogo de HOJE —
    dentro do mesmo tipo de superfície, courts diferentes podem jogar a
    velocidades bem diferentes (ex: Madrid vs Cincinnati, os dois hard).
    Cobertura limitada aos torneios em COURT_PACE_INDEX (Slams/Masters
    1000/ATP Finals) — "sem dados" na maioria dos jogos, por desenho.
    """
    if history.empty or current_bucket is None:
        return None
    nome_col = "tourney_name" if "tourney_name" in history.columns else (
        "Tournament" if "Tournament" in history.columns else None)
    if nome_col is None:
        return None
    resolved = resolve_player_name(history, player)
    if resolved is None:
        return None
    player = resolved
    played = history[(history["winner_name"] == player) | (history["loser_name"] == player)].copy()
    if played.empty:
        return None
    if "tourney_date" in played.columns:
        played["_ano"] = pd.to_datetime(played["tourney_date"], format="%Y%m%d", errors="coerce").dt.year
    else:
        played["_ano"] = None

    matches = 0
    wins = 0
    for _, row in played.iterrows():
        info = lookup_court_pace(row.get(nome_col), row.get("_ano"))
        if info is None or info["bucket"] != current_bucket:
            continue
        matches += 1
        if row.get("winner_name") == player:
            wins += 1

    if matches == 0:
        return None
    return {"matches": matches, "wins": wins, "losses": matches - wins}


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


# ===== FASE 2: recolha RapidAPI para stats antes só no Sackmann =====
_RECENT_STATS_CACHE: dict = {}
_PROFILE_CACHE: dict = {}
RECENT_STATS_CACHE_MAX_AGE_HOURS = 24 * 3


def fetch_recent_stats(tour: str, player_id: int) -> Optional[dict]:
    """Endpoint h2h/recent-stats/{tour}/{id}: serviço/resposta + sets decisivos."""
    cache_key = f"{tour}:{player_id}"
    cached = _RECENT_STATS_CACHE.get(cache_key)
    if cached is not None:
        age = (datetime.now(timezone.utc) - cached["fetched_at"]).total_seconds() / 3600
        if age < RECENT_STATS_CACHE_MAX_AGE_HOURS:
            return cached["data"]
    persistent = _read_player_cache_entry(tour, player_id, "recent_stats", RECENT_STATS_CACHE_MAX_AGE_HOURS)
    if persistent is not None:
        _RECENT_STATS_CACHE[cache_key] = {"fetched_at": datetime.now(timezone.utc), "data": persistent}
        return persistent
    if not RAPIDAPI_KEY:
        return None
    url = f"{RAPIDAPI_BASE}/h2h/recent-stats/{tour}/{player_id}"
    try:
        resp = _rapidapi_get(url)
        resp.raise_for_status()
        data = resp.json()
        _RECENT_STATS_CACHE[cache_key] = {"fetched_at": datetime.now(timezone.utc), "data": data}
        _write_player_cache_entry(tour, player_id, "recent_stats", data)
        return data
    except requests.RequestException as exc:
        print(f"[aviso] falha a obter recent-stats ({tour}, id {player_id}): {exc}")
        return None


def fetch_player_profile(player_name: str) -> Optional[dict]:
    """Endpoint ms-api/profile/{nome}: perfil do jogador (para a MÃO).
    Usa o NOME (URL-encoded), não o ID."""
    from urllib.parse import quote
    cache_key = player_name.lower().strip()
    cached = _PROFILE_CACHE.get(cache_key)
    if cached is not None:
        age = (datetime.now(timezone.utc) - cached["fetched_at"]).total_seconds() / 3600
        if age < 24 * 30:  # perfil muda raramente -> cache 30 dias
            return cached["data"]
    if not RAPIDAPI_KEY:
        return None
    url = f"{RAPIDAPI_BASE}/ms-api/profile/{quote(player_name)}"
    try:
        resp = _rapidapi_get(url)
        resp.raise_for_status()
        data = resp.json()
        _PROFILE_CACHE[cache_key] = {"fetched_at": datetime.now(timezone.utc), "data": data}
        return data
    except requests.RequestException as exc:
        print(f"[aviso] falha a obter profile ({player_name}): {exc}")
        return None


def compute_serve_return_from_recent_stats(recent_stats: dict) -> Optional[dict]:
    """Serviço/resposta do recent-stats (já em %)."""
    if not isinstance(recent_stats, dict):
        return None
    rs = recent_stats.get("recentStats") or {}
    ps = rs.get("playerStats") or {}
    if not rs:
        return None
    def _pct(nk, dk):
        num, den = ps.get(nk), ps.get(dk)
        if num is None or not den:
            return None
        return round(100 * num / den, 1)
    fw = rs.get("firstServeWinPer")
    out = {
        "avg_first_serve_won_pct": float(fw) if fw is not None else None,
        "avg_second_serve_won_pct": float(rs["secondServeWinPer"]) if rs.get("secondServeWinPer") is not None else None,
        "avg_break_points_saved_pct": float(rs["bpSavedPer"]) if rs.get("bpSavedPer") is not None else None,
        "avg_break_points_converted_pct": float(rs["bpConvertedPer"]) if rs.get("bpConvertedPer") is not None else None,
        "avg_first_serve_in_pct": _pct("firstServe", "firstServeOf"),
    }
    return out if out["avg_first_serve_won_pct"] is not None else None


def compute_deciding_set_from_recent_stats(recent_stats: dict) -> Optional[dict]:
    """Sets decisivos do recent-stats (yearStats)."""
    if not isinstance(recent_stats, dict):
        return None
    ys = recent_stats.get("yearStats") or {}
    pct = ys.get("decidingSetWinPer")
    if pct is None:
        return None
    return {
        "deciding_set_win_pct": float(pct),
        "deciding_set_count": ys.get("decidingSetWinOf"),
        "deciding_set_wins": ys.get("decidingSetWin"),
    }


def _extract_hand(plays_str) -> Optional[str]:
    if not plays_str or not isinstance(plays_str, str):
        return None
    s = plays_str.lower()
    if "left" in s:
        return "L"
    if "right" in s:
        return "R"
    return None


def compute_hand_from_profile(profile: dict) -> Optional[str]:
    """Mão do jogador do perfil ms-api."""
    if not isinstance(profile, dict):
        return None
    d = profile.get("data", profile)
    info = d.get("information") or {}
    return _extract_hand(info.get("plays") or d.get("plays"))


def resolve_handedness_matchup(handedness_stats: Optional[dict], opponent_hand: Optional[str]) -> Optional[dict]:
    """
    CORREÇÃO (11/08/2026): o motor de divergência lê
    `handedness_matchup_X.get("win_pct")`, mas compute_handedness_matchup_stats
    nunca devolveu essa chave — só devolve {'vs_left_handed', 'vs_right_handed'}
    aninhados, cada um com {'matches','wins','losses'}. Resultado: wa/wb no
    motor eram SEMPRE None, e o fator "matchup de mão" (peso 8) nunca
    contribuiu, em nenhum jogo, desde sempre.

    Esta função resolve o par (stats do jogador, mão REAL do adversário
    NESTE jogo — de `player_hands`, via perfil RapidAPI) para a taxa de
    vitória específica contra essa mão, no formato que o motor espera.
    None se faltar a mão do adversário ou não houver amostra nesse lado.
    """
    if not isinstance(handedness_stats, dict) or opponent_hand not in ("L", "R"):
        return None
    key = "vs_left_handed" if opponent_hand == "L" else "vs_right_handed"
    sub = handedness_stats.get(key)
    if not isinstance(sub, dict) or not sub.get("matches"):
        return None
    return {
        "win_pct": round(100 * sub["wins"] / sub["matches"], 1),
        "matches": sub["matches"],
        "opponent_hand": opponent_hand,
    }


def compute_scenarios_from_past_matches(past_matches: list, player_id: int) -> Optional[dict]:
    """Recuperação de 1º set a partir do score set-a-set ('result')."""
    if not past_matches:
        return None
    fsl_win = fsl_tot = fsw_win = fsw_tot = 0
    for m in past_matches:
        if not isinstance(m, dict):
            continue
        result = m.get("result")
        winner = m.get("match_winner")
        p1, p2 = m.get("player1Id"), m.get("player2Id")
        if not result or winner is None or player_id not in (p1, p2):
            continue
        sets = []
        for token in str(result).split():
            base = token.split("(")[0]
            if "-" in base:
                try:
                    a, b = base.split("-")
                    sets.append((int(a), int(b)))
                except ValueError:
                    continue
        if not sets:
            continue
        sou_p1 = (player_id == p1)
        s1a, s1b = sets[0]
        ganhou_1set = (s1a > s1b) if sou_p1 else (s1b > s1a)
        ganhou_jogo = (winner == player_id)
        if ganhou_1set:
            fsw_tot += 1
            if ganhou_jogo:
                fsw_win += 1
        else:
            fsl_tot += 1
            if ganhou_jogo:
                fsl_win += 1
    out = {}
    if fsl_tot:
        out["first_set_lose_then_win_pct"] = round(100 * fsl_win / fsl_tot)
        out["first_set_lose_count"] = fsl_tot
    if fsw_tot:
        out["first_set_win_then_win_pct"] = round(100 * fsw_win / fsw_tot)
        out["first_set_win_count"] = fsw_tot
    return out or None


def compute_layoff_from_past_matches(past_matches: list, player_id: int, match_date) -> Optional[dict]:
    """Regresso de lesão: maior gap entre jogos + dias desde o último."""
    if not past_matches:
        return None
    datas = []
    for m in past_matches:
        if not isinstance(m, dict):
            continue
        if player_id not in (m.get("player1Id"), m.get("player2Id")):
            continue
        raw = m.get("date")
        if not raw:
            continue
        try:
            datas.append(datetime.fromisoformat(raw.replace("Z", "+00:00")))
        except (ValueError, AttributeError):
            continue
    if len(datas) < 2:
        return None
    datas.sort(reverse=True)
    dias_ultimo = (match_date - datas[0]).days if match_date else None
    maior_gap = max((datas[i] - datas[i + 1]).days for i in range(len(datas) - 1))
    return {"days_since_last_match": dias_ultimo, "days_out": maior_gap}


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
        # CORREÇÃO (11/08/2026): o motor lia este campo para detetar "último
        # jogo foi longo" (escala o peso da fadiga), mas nunca existia —
        # sempre None, essa escalada nunca disparava. Já temos o nº de sets
        # de cada jogo em `played` (index 2); o mais recente é played[0].
        "last_match_sets": played[0][2] if played else None,
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
    for attempt in (1, 2, 3):
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


def discover_tracked_tournaments() -> dict[int, str]:
    """
    Descoberta automática dos torneios ATP/WTA elegíveis (substitui a
    manutenção manual de TRACKED_TOURNAMENT_IDS em config.py sempre que um
    torneio novo começa, ex: Cincinnati a seguir a Montreal/Toronto).

    Fonte: o mesmo feed "All Upcoming Matches" já usado para as odds
    embutidas (_fetch_extend_upcoming_events) — cada jogo já vem com
    tournament.id/name e o tour (atp/wta). Agrupamos por torneio e
    filtramos pelo tier via get_tournament_info() (já testada, com cache
    local — só 1 pedido por torneio NOVO, não por jogo).

    Robustez: se a descoberta falhar por qualquer razão (sem chave, feed
    vazio, ou 0 torneios elegíveis), cai para TRACKED_TOURNAMENT_IDS
    (config.py) como rede de segurança — nunca fica sem jogos por causa
    disto. Podes continuar a usar a lista manual como reforço/override se
    quiseres forçar um torneio específico.
    """
    events = _fetch_extend_upcoming_events("all")
    if not events:
        print("[aviso] descoberta automática de torneios: feed vazio — "
              "a usar TRACKED_TOURNAMENT_IDS manual (config.py).")
        return dict(TRACKED_TOURNAMENT_IDS)

    candidatos: dict[int, str] = {}
    for ev in events:
        t = ev.get("tournament") or {}
        tid = t.get("id")
        tour = ev.get("type")
        if tid is None or tour not in ("atp", "wta"):
            continue
        candidatos.setdefault(tid, tour)

    aceites: dict[int, str] = {}
    for tid, tour in candidatos.items():
        info = get_tournament_info(tid, tour)
        if info and info.get("tier") in ALLOWED_TOURNAMENT_TIERS:
            aceites[tid] = tour

    if not aceites:
        print(f"[aviso] descoberta automática: {len(candidatos)} torneio(s) candidato(s), "
              "nenhum no tier permitido — a usar TRACKED_TOURNAMENT_IDS manual (config.py).")
        return dict(TRACKED_TOURNAMENT_IDS)

    resumo = ", ".join(f"{tid}:{tour}" for tid, tour in aceites.items())
    print(f"[info] descoberta automática: {len(aceites)} torneio(s) elegível(is) — {resumo}")
    return aceites


def fetch_tracked_tournament_fixtures() -> list[dict]:
    """Junta fixtures de todos os torneios elegíveis, descobertos
    automaticamente (discover_tracked_tournaments), com fallback para a
    lista manual TRACKED_TOURNAMENT_IDS se a descoberta falhar."""
    tracked = discover_tracked_tournaments()
    all_matches = []
    for tournament_id, tour in tracked.items():
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


def main() -> None:
    """
    Entrada CLI para tarefas de manutenção que não fazem parte do fluxo
    normal do bot (main.py). Por agora só o pré-aquecimento da cache de
    mão WTA — ver warm_up_hand_cache.

    Uso:
        python -m src.fetch_data warm-up-hands [tour] [top_n]
        python -m src.fetch_data warm-up-hands wta 200   # (valores por defeito)
    """
    import sys as _sys
    args = _sys.argv[1:]
    if not args or args[0] != "warm-up-hands":
        print(__doc__ if __doc__ else "")
        print("Uso: python -m src.fetch_data warm-up-hands [tour=wta] [top_n=200]")
        return
    tour = args[1] if len(args) >= 2 else "wta"
    top_n = int(args[2]) if len(args) >= 3 else 200
    warm_up_hand_cache(tour, top_n)


if __name__ == "__main__":
    main()
