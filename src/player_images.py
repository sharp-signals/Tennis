"""Registos curados de fotografias locais e respetivos créditos."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = PROJECT_ROOT / "data" / "player_images.json"
OVERRIDES_PATH = PROJECT_ROOT / "data" / "player_image_overrides.json"
_REQUIRED_OVERRIDE_FIELDS = {
    "tour", "player_id", "name", "source_url", "author", "license",
    "license_url", "path", "modifications",
}


def _normalise_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return " ".join("".join(ch for ch in text if not unicodedata.combining(ch)).casefold().split())


def _load_players(path: Path) -> dict[str, dict]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    players = document.get("players") if isinstance(document, dict) else None
    return players if isinstance(players, dict) else {}


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, dict]:
    return _load_players(path)


def _is_web_url(value: Any) -> bool:
    try:
        parsed = urlparse(str(value))
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_reusable_license(value: Any) -> bool:
    """Aceita apenas licenças abertas que permitem redistribuição e adaptação."""
    licence = " ".join(str(value or "").upper().replace("_", " ").split())
    if not licence or any(token in licence for token in ("-NC", " NC", "-ND", " ND", "ALL RIGHTS")):
        return False
    return bool(
        re.fullmatch(r"CC0(?:\s+1\.0)?", licence)
        or re.fullmatch(r"CC BY(?:-SA)?(?:\s+[1-4]\.0)?", licence)
        or licence in {"PUBLIC DOMAIN", "PUBLIC DOMAIN MARK", "PDM"}
    )


def _local_asset_path(report_path: Any, project_root: Path) -> Path | None:
    if not isinstance(report_path, str) or not report_path.strip():
        return None
    try:
        asset = (project_root / "docs" / "relatorios" / report_path).resolve()
        allowed = (project_root / "docs" / "assets" / "players").resolve()
        asset.relative_to(allowed)
    except (OSError, ValueError):
        return None
    return asset


def validate_manual_override(
    key: str,
    entry: Any,
    *,
    project_root: Path = PROJECT_ROOT,
) -> tuple[dict | None, str | None]:
    """Valida fail-closed a identidade, proveniência, licença e asset local."""
    if not isinstance(entry, dict):
        return None, "INVALID_ENTRY"
    missing = sorted(field for field in _REQUIRED_OVERRIDE_FIELDS if not entry.get(field))
    if missing:
        return None, "MISSING_" + "_".join(field.upper() for field in missing)

    tour = str(entry["tour"]).casefold()
    player_id = str(entry["player_id"])
    if tour not in {"atp", "wta"} or key != f"{tour}:{player_id}":
        return None, "IDENTITY_MISMATCH"
    if not _normalise_name(entry["name"]):
        return None, "MISSING_NAME"
    if not _is_web_url(entry["source_url"]):
        return None, "INVALID_SOURCE_URL"
    if not _is_web_url(entry["license_url"]):
        return None, "INVALID_LICENSE_URL"
    if not _is_reusable_license(entry["license"]):
        return None, "LICENSE_NOT_REUSABLE"

    asset = _local_asset_path(entry["path"], project_root)
    if asset is None or not asset.is_file():
        return None, "LOCAL_ASSET_UNAVAILABLE"

    validated = dict(entry)
    validated["tour"] = tour
    validated["manual_override"] = True
    validated["provenance"] = "MANUAL_LICENSED_OVERRIDE"
    return validated, None


def load_manual_overrides(
    path: Path = OVERRIDES_PATH,
    *,
    project_root: Path = PROJECT_ROOT,
) -> dict[str, dict]:
    """Carrega apenas overrides cuja reutilização é comprovável localmente."""
    valid = {}
    for key, entry in _load_players(path).items():
        checked, _reason = validate_manual_override(key, entry, project_root=project_root)
        if checked:
            valid[key] = checked
    return valid


def find_manual_override(
    tour: str,
    player_id: Any,
    player_name: str,
    overrides: dict[str, dict] | None = None,
    *,
    project_root: Path = PROJECT_ROOT,
) -> dict | None:
    entries = overrides if overrides is not None else _load_players(OVERRIDES_PATH)
    valid = {}
    for key, entry in entries.items():
        checked, _reason = validate_manual_override(key, entry, project_root=project_root)
        if checked:
            valid[key] = checked

    tour_key = str(tour or "").casefold()
    key = f"{tour_key}:{player_id}"
    entry = valid.get(key) if player_id is not None else None
    if entry:
        return dict(entry)

    wanted = _normalise_name(player_name)
    matches = [
        entry for entry in valid.values()
        if entry.get("tour") == tour_key and _normalise_name(entry.get("name")) == wanted
    ]
    return dict(matches[0]) if len(matches) == 1 else None


def find_player_image(
    tour: str,
    player_id: Any,
    player_name: str,
    registry: dict[str, dict] | None = None,
    *,
    overrides: dict[str, dict] | None = None,
    project_root: Path = PROJECT_ROOT,
) -> dict | None:
    """Resolve override licenciado, depois Commons; o HTML trata as iniciais."""
    manual = find_manual_override(
        tour, player_id, player_name, overrides, project_root=project_root,
    )
    if manual:
        return manual

    entries = registry if registry is not None else load_registry()
    key = f"{str(tour or '').casefold()}:{player_id}"
    entry = entries.get(key) if player_id is not None else None
    if entry:
        return dict(entry)
    wanted = _normalise_name(player_name)
    matches = [entry for entry in entries.values()
               if _normalise_name(entry.get("name")) == wanted]
    return dict(matches[0]) if len(matches) == 1 else None
