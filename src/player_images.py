"""Registo curado de fotografias locais e respetivos créditos."""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any


REGISTRY_PATH = Path(__file__).resolve().parent.parent / "data" / "player_images.json"


def _normalise_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return " ".join("".join(ch for ch in text if not unicodedata.combining(ch)).casefold().split())


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, dict]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    players = document.get("players") if isinstance(document, dict) else None
    return players if isinstance(players, dict) else {}


def find_player_image(tour: str, player_id: Any, player_name: str,
                      registry: dict[str, dict] | None = None) -> dict | None:
    """Resolve primeiro pelo ID estável e usa o nome apenas como fallback."""
    entries = registry if registry is not None else load_registry()
    key = f"{str(tour or '').casefold()}:{player_id}"
    entry = entries.get(key) if player_id is not None else None
    if entry:
        return dict(entry)
    wanted = _normalise_name(player_name)
    matches = [entry for entry in entries.values()
               if _normalise_name(entry.get("name")) == wanted]
    return dict(matches[0]) if len(matches) == 1 else None
