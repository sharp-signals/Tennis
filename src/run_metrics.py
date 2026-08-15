"""Telemetria operacional leve, sem dependências externas."""

from __future__ import annotations

import json
import math
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

_LOCK = threading.Lock()
_FILE_LOCK = threading.Lock()
_COUNTERS: dict[str, int] = {}
_CONTEXT: dict = {}
_STARTED_AT: float | None = None
MAX_HISTORY_ENTRIES = 180


def _env_number(name: str, default: float) -> float:
    """Lê configuração numérica sem deixar um typo quebrar a telemetria."""
    try:
        value = float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) and value >= 0 else default


def _as_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _as_float(value: object) -> float:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) and number >= 0 else 0.0


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
        "input": _env_number("LLM_PRICE_INPUT_PER_MTOK", 3.0),
        "output": _env_number("LLM_PRICE_OUTPUT_PER_MTOK", 15.0),
        "cache_read": _env_number("LLM_PRICE_CACHE_READ_PER_MTOK", 0.3),
        "cache_write": _env_number("LLM_PRICE_CACHE_WRITE_PER_MTOK", 3.75),
    }
    total = (
        _as_int(values.get("llm_input_tokens")) * prices["input"]
        + _as_int(values.get("llm_output_tokens")) * prices["output"]
        + _as_int(values.get("llm_cache_read_tokens")) * prices["cache_read"]
        + _as_int(values.get("llm_cache_creation_tokens")) * prices["cache_write"]
    ) / 1_000_000
    return round(total, 6)


def health_alerts(entry: dict) -> list[str]:
    """Alertas simples, configuráveis e explicáveis para uma execução."""
    alerts = []
    calls = _as_int(entry.get("rapidapi_calls"))
    llm_calls = _as_int(entry.get("llm_calls"))
    fallbacks = _as_int(entry.get("llm_fallbacks"))
    if entry.get("status") == "failed":
        alerts.append(f"execução falhou na fase {entry.get('phase', 'desconhecida')}")
    if calls >= _env_number("ALERT_RAPIDAPI_CALLS", 600):
        alerts.append(f"consumo RapidAPI elevado: {calls} chamadas")
    if llm_calls and fallbacks / llm_calls >= _env_number("ALERT_LLM_FALLBACK_RATE", 0.2):
        alerts.append(f"fallback LLM elevado: {fallbacks}/{llm_calls}")
    if _as_int(entry.get("reports_failed")):
        alerts.append(f"relatórios falhados: {entry['reports_failed']}")
    analysis_failed = _as_int(entry.get("analysis_failed"))
    eligible = _as_int(entry.get("eligible"))
    if analysis_failed:
        ratio = analysis_failed / eligible if eligible else 1.0
        alerts.append(
            "análises falhadas: "
            f"{analysis_failed}/{eligible or '?'} ({ratio:.0%})"
        )
    if _as_int(entry.get("llm_cache_invalid")):
        alerts.append(f"cache LLM inválida: {entry['llm_cache_invalid']} entrada(s)")
    if _as_int(entry.get("llm_cache_write_failures")):
        alerts.append(f"falhas ao gravar cache LLM: {entry['llm_cache_write_failures']}")
    estimated_cost = _as_float(entry.get("llm_estimated_cost_usd"))
    if estimated_cost >= _env_number("ALERT_LLM_COST_USD", 1.0):
        alerts.append(f"custo LLM estimado elevado: ${estimated_cost:.4f}")
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
    target = Path(path)
    with _FILE_LOCK:
        try:
            with target.open("r", encoding="utf-8") as handle:
                history = json.load(handle)
            if not isinstance(history, list):
                history = []
            else:
                history = [item for item in history if isinstance(item, dict)]
        except (OSError, UnicodeError, TypeError, json.JSONDecodeError):
            history = []
        history = (history + [entry])[-MAX_HISTORY_ENTRIES:]
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                json.dump(history, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, target)
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink()
                except FileNotFoundError:
                    pass
    return entry
