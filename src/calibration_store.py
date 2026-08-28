"""Snapshots pre-match imutaveis para calibracao futura, sem fuga temporal."""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = 1
DEFAULT_PATH = Path("data/calibration_snapshots.json")
MAX_ENTRIES = None  # o histórico operacional não é truncado silenciosamente

_LOCK = threading.Lock()
_METRIC_KEYS = (
    "market_adjusted_form_a", "market_adjusted_form_b",
    "opposition_quality_a", "opposition_quality_b",
    "pressure_profile_a", "pressure_profile_b",
    "surface_momentum_a", "surface_momentum_b",
    "recent_form_a", "recent_form_b",
    "serve_return_stats_a", "serve_return_stats_b",
    "deciding_set_stats_a", "deciding_set_stats_b",
    "set1_comeback_stats_a", "set1_comeback_stats_b",
    "ranking_a", "ranking_b", "features", "divergencia",
    "report_assessment", "prelive_decision",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _snapshot_key(payload: Mapping[str, Any]) -> str:
    match_id = payload.get("match_id")
    if match_id is not None:
        return f"{str(payload.get('tour') or '').lower()}:{match_id}"
    material = "|".join(str(payload.get(key) or "") for key in (
        "tour", "player_a_id", "player_b_id", "commence_time_utc",
    ))
    return "fallback:" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def build_snapshot(payload: Mapping[str, Any], result: Mapping[str, Any] | None = None,
                   analyzed_at_utc: str | None = None) -> dict[str, Any]:
    """Cria uma fotografia compacta apenas com informacao conhecida pre-jogo."""
    analyzed_at = analyzed_at_utc or _utc_now()
    key = _snapshot_key(payload)
    report_id = hashlib.sha256(f"{key}|{analyzed_at}".encode("utf-8")).hexdigest()[:20]
    snapshot = {
        "key": key,
        "report_id": report_id,
        "match_id": payload.get("match_id"),
        "tour": payload.get("tour"),
        "tournament_id": payload.get("tournament_id"),
        "tournament": payload.get("tournament"),
        "surface": payload.get("surface"),
        "commence_time_utc": payload.get("commence_time_utc"),
        "analyzed_at_utc": analyzed_at,
        "player_a": {"id": payload.get("player_a_id"), "name": payload.get("player_a")},
        "player_b": {"id": payload.get("player_b_id"), "name": payload.get("player_b")},
        "market_odds_decimal": payload.get("market_odds_decimal"),
        # Congelado antes do encontro, juntamente com a configuracao/hash que
        # o produziu. Uma repeticao nunca substitui esta primeira estimativa.
        "pricing": payload.get("pricing"),
        "metrics": {key: payload.get(key) for key in _METRIC_KEYS if payload.get(key) is not None},
        "analysis": {
            key: result.get(key) for key in ("flag", "signal_strength") if result and result.get(key) is not None
        },
        "outcome": None,
    }
    return snapshot


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"schema_version": SCHEMA_VERSION, "snapshots": []}
    if value.get("schema_version") != SCHEMA_VERSION or not isinstance(value.get("snapshots"), list):
        return {"schema_version": SCHEMA_VERSION, "snapshots": []}
    return value


def _write(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def upsert_snapshots(snapshots: Iterable[Mapping[str, Any]], path: Path = DEFAULT_PATH,
                     max_entries: int | None = MAX_ENTRIES) -> int:
    """Insere snapshots; uma repeticao nunca reescreve a fotografia original."""
    with _LOCK:
        document = _read(path)
        existing = {item.get("key"): item for item in document["snapshots"] if item.get("key")}
        added = 0
        for snapshot in snapshots:
            key = snapshot.get("key")
            if key and key not in existing:
                existing[key] = dict(snapshot)
                added += 1
        ordered = sorted(existing.values(), key=lambda item: item.get("analyzed_at_utc") or "")
        document["snapshots"] = ordered[-max_entries:] if max_entries else ordered
        document["updated_at_utc"] = _utc_now()
        _write(path, document)
        return added


def settle_from_matches(matches: Iterable[Mapping[str, Any]], path: Path = DEFAULT_PATH) -> int:
    """Preenche resultados usando jogos terminados; nao altera dados pre-match."""
    completed = {}
    completed_by_players: dict[frozenset[str], list[Mapping[str, Any]]] = {}
    for match in matches:
        match_id = match.get("id")
        winner_id = match.get("match_winner")
        if winner_id is None:
            continue
        if str(match.get("result_type") or "").lower() not in {"completed", "finished"}:
            continue
        if match_id is not None:
            completed[str(match_id)] = match
        p1 = match.get("player1Id") or (match.get("player1") or {}).get("id")
        p2 = match.get("player2Id") or (match.get("player2") or {}).get("id")
        if p1 is not None and p2 is not None:
            completed_by_players.setdefault(frozenset((str(p1), str(p2))), []).append(match)

    def parse_time(value):
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None

    def fallback_match(snapshot):
        a_id = (snapshot.get("player_a") or {}).get("id")
        b_id = (snapshot.get("player_b") or {}).get("id")
        if a_id is None or b_id is None:
            return None
        candidates = completed_by_players.get(frozenset((str(a_id), str(b_id))), [])
        scheduled = parse_time(snapshot.get("commence_time_utc"))
        if scheduled is None:
            return None
        dated = []
        for candidate in candidates:
            played = parse_time(candidate.get("date"))
            if played is not None:
                delta = abs((played - scheduled).total_seconds())
                if delta <= 48 * 3600:
                    dated.append((delta, candidate))
        return min(dated, key=lambda item: item[0])[1] if dated else None

    with _LOCK:
        document = _read(path)
        settled = 0
        for snapshot in document["snapshots"]:
            if snapshot.get("outcome") is not None:
                continue
            match = completed.get(str(snapshot.get("match_id"))) or fallback_match(snapshot)
            if not match:
                continue
            winner_id = match.get("match_winner")
            a_id = (snapshot.get("player_a") or {}).get("id")
            b_id = (snapshot.get("player_b") or {}).get("id")
            if str(winner_id) == str(a_id):
                side = "a"
            elif str(winner_id) == str(b_id):
                side = "b"
            else:
                continue
            snapshot["outcome"] = {
                "winner_side": side,
                "winner_id": winner_id,
                "result": match.get("result"),
                "settled_at_utc": _utc_now(),
            }
            settled += 1
        if settled:
            document["updated_at_utc"] = _utc_now()
            _write(path, document)
        return settled


def compute_system_accuracy(path: Path = DEFAULT_PATH) -> dict[str, Any] | None:
    """
    NOVO (22/08/2026, a pedido): histórico de acerto do PRÓPRIO sistema, a
    partir dos snapshots já resolvidos. Não é opinião — é o registo real do
    que aconteceu. Devolve, quando há amostra mínima:
      - alinhamento_forte: em jogos onde mercado e indicadores concordavam
        fortemente (nível 0 mas índice muito concentrado), quantas vezes o
        favorecido confirmou.
      - divergencia: em jogos onde os indicadores apontavam contra o
        mercado (nível >= 2), quantas vezes o lado dos INDICADORES ganhou.
    Cada um só é devolvido com um mínimo de 10 casos resolvidos (abaixo
    disso a taxa é ruído). None se não houver dados de todo.
    """
    document = _read(path)
    snaps = [s for s in document.get("snapshots", []) if s.get("outcome")]
    if not snaps:
        return None

    MIN_CASOS = 10

    alinhamento_ok = alinhamento_total = 0
    diverg_ok = diverg_total = 0

    for s in snaps:
        div = (s.get("metrics") or {}).get("divergencia") or {}
        outcome = s.get("outcome") or {}
        winner_side = outcome.get("winner_side")  # 'a' ou 'b'
        if winner_side not in ("a", "b"):
            continue

        nivel = (div.get("classificacao") or {}).get("nivel", 0) or 0
        mercado_favorece = div.get("mercado_favorece")
        indice_favorece = div.get("indice_favorece")
        nome_a = div.get("player_a") or s.get("player_a")
        nome_b = div.get("player_b") or s.get("player_b")
        vencedor_nome = nome_a if winner_side == "a" else nome_b

        if nivel >= 2 and indice_favorece and indice_favorece != mercado_favorece:
            # Divergência real: os indicadores apontaram contra o mercado.
            diverg_total += 1
            if vencedor_nome == indice_favorece:
                diverg_ok += 1
        elif nivel == 0 and mercado_favorece:
            # Alinhado: mercado e indicadores concordam. Conta se o
            # favorecido confirmou.
            alinhamento_total += 1
            if vencedor_nome == mercado_favorece:
                alinhamento_ok += 1

    resultado: dict[str, Any] = {}
    if alinhamento_total >= MIN_CASOS:
        lo, hi = _wilson_interval(alinhamento_ok, alinhamento_total)
        resultado["alinhamento_forte"] = {
            "acertos": alinhamento_ok, "total": alinhamento_total,
            "taxa_pct": round(100 * alinhamento_ok / alinhamento_total, 1),
            "intervalo_pct": [round(lo * 100, 1), round(hi * 100, 1)],
        }
    if diverg_total >= MIN_CASOS:
        lo, hi = _wilson_interval(diverg_ok, diverg_total)
        resultado["divergencia"] = {
            "acertos": diverg_ok, "total": diverg_total,
            "taxa_pct": round(100 * diverg_ok / diverg_total, 1),
            "intervalo_pct": [round(lo * 100, 1), round(hi * 100, 1)],
        }
    return resultado or None


def _wilson_interval(wins: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 1.0
    observed = wins / total
    denominator = 1 + z * z / total
    centre = (observed + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(observed * (1 - observed) / total + z * z / (4 * total * total)) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)


def estimate_indicative_odds(divergence: Mapping[str, Any] | None,
                             path: Path = DEFAULT_PATH, min_samples: int = 30,
                             bucket_width: int = 10) -> dict[str, Any] | None:
    """Estima uma faixa de odds, preferindo resultados já liquidados.

    A calibração usa o lado com maior índice em cada encontro, uma observação
    por jogo, e um intervalo de Wilson de 95%. Antes da amostra mínima, a faixa
    continua visível e é marcada como provisória. Sem qualquer observação,
    usa-se uma heurística deliberadamente larga e explicitamente não calibrada;
    o índice é suavizado para metade da distância a 50, em vez de ser tratado
    diretamente como probabilidade.
    """
    if not isinstance(divergence, Mapping):
        return None
    try:
        index_a = float(divergence["indice_evidencia_a"])
        index_b = float(divergence["indice_evidencia_b"])
    except (KeyError, TypeError, ValueError):
        return None
    target_favourite = max(index_a, index_b)
    if target_favourite <= 50:
        return None
    bucket_low = int(target_favourite // bucket_width) * bucket_width
    bucket_high = min(100, bucket_low + bucket_width - 1)
    if target_favourite == 100:
        bucket_low, bucket_high = 90, 100

    observations: list[bool] = []
    for snapshot in _read(path)["snapshots"]:
        outcome = snapshot.get("outcome") or {}
        metrics = snapshot.get("metrics") or {}
        historical = metrics.get("divergencia") or {}
        try:
            hist_a = float(historical["indice_evidencia_a"])
            hist_b = float(historical["indice_evidencia_b"])
        except (KeyError, TypeError, ValueError):
            continue
        hist_favourite = max(hist_a, hist_b)
        if not bucket_low <= hist_favourite <= bucket_high or hist_a == hist_b:
            continue
        winner_side = outcome.get("winner_side")
        if winner_side not in {"a", "b"}:
            continue
        favourite_side = "a" if hist_a > hist_b else "b"
        observations.append(winner_side == favourite_side)

    total = len(observations)
    result: dict[str, Any] = {
        "available": True,
        "calibrated": total >= min_samples,
        "provisional": total < min_samples,
        "sample_size": total,
        "minimum_sample": min_samples,
        "evidence_bucket": [bucket_low, bucket_high],
        "confidence_level_pct": 95,
    }
    # Heurística (usada sozinha sem observações, ou misturada com dados
    # reais quando a amostra ainda é pequena — ver blend abaixo).
    strength = (target_favourite - 50.0) / 50.0  # 0 (neutro) .. 1 (índice 100)
    strength_sq = strength ** 2  # aperta só perceptivelmente perto do extremo (100)
    heur_centre = 0.5 + strength_sq * 0.35
    heur_margin = 0.20 - strength_sq * 0.10
    heur_low = max(0.05, heur_centre - heur_margin)
    heur_high = min(0.95, heur_centre + heur_margin)

    if total:
        low, high = _wilson_interval(sum(observations), total)
        # CORREÇÃO (18/08/2026, log real): com amostra pequena (ex: n=6),
        # o intervalo de Wilson isolado pode ficar absurdamente largo
        # (visto na prática: 1.77–33.28) — matematicamente correto, mas
        # inútil. Mistura-se com a heurística, ponderado pela amostra:
        # quase só heurística com poucos jogos, cada vez mais dados reais
        # conforme a amostra cresce até à amostra mínima.
        peso_historico = min(1.0, total / min_samples)
        low = peso_historico * low + (1 - peso_historico) * heur_low
        high = peso_historico * high + (1 - peso_historico) * heur_high
        if peso_historico < 1.0:
            result["method"] = "calibração histórica combinada com heurística (amostra ainda pequena)"
        else:
            result["method"] = "calibração histórica; intervalo de Wilson"
        result["basis"] = "historical"
    else:
        # O índice de evidência não é uma probabilidade. Para permitir a
        # evolução visual do relatório desde já, aproximamos com uma curva
        # que ainda é deliberadamente larga em sinais fracos, mas encolhe
        # com a força da convicção — em vez de uma margem fixa de ±20 p.p.
        # que mantinha a faixa quase tão larga em índice 100 como em
        # índice 55 (18/08/2026, a pedido: "o Zverev tem quase tudo a
        # favor e o intervalo máximo é só até 2.00"). Esta faixa continua
        # a ser um andaime de produto, não uma odd justa, e desaparece
        # automaticamente assim que existirem resultados liquidados neste
        # balde (ver ramo `if total:` acima).
        low, high = heur_low, heur_high
        result["method"] = "heurística experimental; margem encolhe com a força da convicção"
        result["basis"] = "heuristic"

    side_ranges = {}
    for side, index in (("a", index_a), ("b", index_b)):
        prob_low, prob_high = (low, high) if index > 50 else (1 - high, 1 - low)
        # Evita odds infinitas em amostras iniciais com 0%/100% observado.
        prob_low = max(0.01, min(0.99, prob_low))
        prob_high = max(prob_low, min(0.99, prob_high))
        side_ranges[side] = {
            "probability_low_pct": round(prob_low * 100, 1),
            "probability_high_pct": round(prob_high * 100, 1),
            "odds_low": round(1 / prob_high, 2),
            "odds_high": round(1 / prob_low, 2),
        }
    result["players"] = side_ranges
    return result
