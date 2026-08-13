"""Telemetria operacional leve, sem dependências externas."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone

_LOCK = threading.Lock()
_COUNTERS: dict[str, int] = {}
_CONTEXT: dict = {}
_STARTED_AT: float | None = None
MAX_HISTORY_ENTRIES = 180


def reset() -> None:
    global _STARTED_AT
    with _LOCK:
        _COUNTERS.clear()
        _CONTEXT.clear()
        _STARTED_AT = time.monotonic()


def update_context(**values) -> None:
    """Atualiza o estado que será persistido mesmo se a execução falhar."""
    with _LOCK:
        _CONTEXT.update({key: value for key, value in values.items() if value is not None})


def increment(name: str, amount: int = 1) -> None:
    if not name or amount < 0:
        raise ValueError("Métrica inválida.")
    with _LOCK:
        _COUNTERS[name] = _COUNTERS.get(name, 0) + int(amount)


def snapshot() -> dict[str, int]:
    with _LOCK:
        return dict(sorted(_COUNTERS.items()))


def estimate_llm_cost_usd(metrics: dict | None = None) -> float:
    """Estimativa configurável; a faturação do fornecedor continua autoritativa."""
    values = metrics or snapshot()
    prices = {
        "input": float(os.environ.get("LLM_PRICE_INPUT_PER_MTOK", "3")),
        "output": float(os.environ.get("LLM_PRICE_OUTPUT_PER_MTOK", "15")),
        "cache_read": float(os.environ.get("LLM_PRICE_CACHE_READ_PER_MTOK", "0.3")),
        "cache_write": float(os.environ.get("LLM_PRICE_CACHE_WRITE_PER_MTOK", "3.75")),
    }
    total = (
        int(values.get("llm_input_tokens", 0)) * prices["input"]
        + int(values.get("llm_output_tokens", 0)) * prices["output"]
        + int(values.get("llm_cache_read_tokens", 0)) * prices["cache_read"]
        + int(values.get("llm_cache_creation_tokens", 0)) * prices["cache_write"]
    ) / 1_000_000
    return round(total, 6)


def health_alerts(entry: dict) -> list[str]:
    """Alertas simples, configuráveis e explicáveis para uma execução."""
    alerts = []
    calls = int(entry.get("rapidapi_calls") or 0)
    llm_calls = int(entry.get("llm_calls") or 0)
    fallbacks = int(entry.get("llm_fallbacks") or 0)
    if entry.get("status") == "failed":
        alerts.append(f"execução falhou na fase {entry.get('phase', 'desconhecida')}")
    if calls >= int(os.environ.get("ALERT_RAPIDAPI_CALLS", "600")):
        alerts.append(f"consumo RapidAPI elevado: {calls} chamadas")
    if llm_calls and fallbacks / llm_calls >= float(os.environ.get("ALERT_LLM_FALLBACK_RATE", "0.2")):
        alerts.append(f"fallback LLM elevado: {fallbacks}/{llm_calls}")
    if int(entry.get("reports_failed") or 0):
        alerts.append(f"relatórios falhados: {entry['reports_failed']}")
    if float(entry.get("llm_estimated_cost_usd") or 0) >= float(os.environ.get("ALERT_LLM_COST_USD", "1")):
        alerts.append(f"custo LLM estimado elevado: ${entry['llm_estimated_cost_usd']:.4f}")
    return alerts


def append_run(
    *,
    path: str = "data/run_metrics_log.json",
    context: dict | None = None,
) -> dict:
    with _LOCK:
        persistent_context = dict(_CONTEXT)
        started_at = _STARTED_AT
    counters = snapshot()
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **persistent_context,
        **dict(context or {}),
        **counters,
    }
    if started_at is not None:
        entry.setdefault("duration_seconds", round(time.monotonic() - started_at, 3))
    entry.setdefault("llm_estimated_cost_usd", estimate_llm_cost_usd(counters))
    try:
        with open(path, "r", encoding="utf-8") as handle:
            history = json.load(handle)
        if not isinstance(history, list):
            history = []
    except (OSError, TypeError, json.JSONDecodeError):
        history = []
    history = (history + [entry])[-MAX_HISTORY_ENTRIES:]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    temp = f"{path}.tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(history, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
    return entry
