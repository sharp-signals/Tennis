"""Telemetria operacional leve, sem dependências externas."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone

_LOCK = threading.Lock()
_COUNTERS: dict[str, int] = {}
MAX_HISTORY_ENTRIES = 180


def reset() -> None:
    with _LOCK:
        _COUNTERS.clear()


def increment(name: str, amount: int = 1) -> None:
    if not name or amount < 0:
        raise ValueError("Métrica inválida.")
    with _LOCK:
        _COUNTERS[name] = _COUNTERS.get(name, 0) + int(amount)


def snapshot() -> dict[str, int]:
    with _LOCK:
        return dict(sorted(_COUNTERS.items()))


def append_run(
    *,
    path: str = "data/run_metrics_log.json",
    context: dict | None = None,
) -> dict:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **dict(context or {}),
        **snapshot(),
    }
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
