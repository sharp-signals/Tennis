"""Constrói um acervo local de fotografias licenciadas para ATP/WTA."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import unicodedata
from pathlib import Path
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import fetch_data, player_images  # noqa: E402


WIKIDATA_API = "https://www.wikidata.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
ASSET_DIR = ROOT / "docs" / "assets" / "players"
REVIEW_PATH = ROOT / "data" / "player_images_review.json"
USER_AGENT = "SharpSignalsTennis/1.0 (https://github.com/sharp-signals/Tennis)"
ALLOWED_LICENSES = ("CC BY", "CC0", "PUBLIC DOMAIN", "PDM")


def _normalise(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return " ".join("".join(ch for ch in text if not unicodedata.combining(ch)).casefold().split())


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _normalise(value)).strip("-") or "player"


def _plain(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", str(value or ""))).strip()


def _get(session: requests.Session, url: str, *, params=None, attempts: int = 3) -> requests.Response:
    for attempt in range(attempts):
        try:
            response = session.get(url, params=params, timeout=25)
            response.raise_for_status()
            return response
        except requests.RequestException:
            if attempt + 1 == attempts:
                raise
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError("pedido externo sem resposta")


def _find_wikidata_item(session: requests.Session, name: str) -> tuple[str | None, str]:
    response = _get(session, WIKIDATA_API, params={
        "action": "wbsearchentities", "search": name, "language": "en",
        "uselang": "en", "type": "item", "limit": 8, "format": "json",
    }).json()
    exact = []
    wanted = _normalise(name)
    for item in response.get("search", []):
        names = [item.get("label"), *(item.get("aliases") or [])]
        if wanted not in {_normalise(candidate) for candidate in names if candidate}:
            continue
        description = str(item.get("description") or "").casefold()
        if "tennis" in description:
            exact.append(item.get("id"))
    exact = [item for item in exact if item]
    if len(exact) != 1:
        return None, "sem correspondência inequívoca de tenista no Wikidata"
    return exact[0], ""


def _wikidata_image(session: requests.Session, item_id: str) -> str | None:
    entity = _get(session, WIKIDATA_API, params={
        "action": "wbgetentities", "ids": item_id, "props": "claims", "format": "json",
    }).json().get("entities", {}).get(item_id, {})
    claims = entity.get("claims", {}).get("P18", [])
    try:
        return claims[0]["mainsnak"]["datavalue"]["value"]
    except (IndexError, KeyError, TypeError):
        return None


def _commons_metadata(session: requests.Session, filename: str) -> tuple[dict | None, str]:
    payload = _get(session, COMMONS_API, params={
        "action": "query", "titles": f"File:{filename}", "prop": "imageinfo",
        "iiprop": "url|extmetadata", "iiurlwidth": 320, "format": "json",
    }).json()
    pages = payload.get("query", {}).get("pages", {})
    page = next(iter(pages.values()), {})
    info = (page.get("imageinfo") or [None])[0]
    if not info:
        return None, "ficheiro Commons sem metadados"
    metadata = info.get("extmetadata") or {}
    licence = _plain((metadata.get("LicenseShortName") or {}).get("value"))
    if not any(token in licence.upper() for token in ALLOWED_LICENSES):
        return None, f"licença não aceite automaticamente: {licence or 'desconhecida'}"
    source_url = (metadata.get("DescriptionUrl") or {}).get("value") or (
        "https://commons.wikimedia.org/wiki/File:" + quote(filename.replace(" ", "_"))
    )
    return {
        "download_url": info.get("thumburl") or info.get("url"),
        "author": _plain((metadata.get("Artist") or {}).get("value")) or "Wikimedia Commons contributor",
        "license": licence,
        "license_url": (metadata.get("LicenseUrl") or {}).get("value") or source_url,
        "source_url": source_url,
    }, ""


def _extension(content_type: str, url: str) -> str:
    if "png" in content_type.casefold():
        return ".png"
    if "webp" in content_type.casefold():
        return ".webp"
    return ".jpg"


def _write_registry(registry: dict[str, dict]) -> None:
    document = {"schema_version": 1, "players": dict(sorted(registry.items()))}
    player_images.REGISTRY_PATH.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )


def _record_review(item: dict) -> None:
    try:
        document = json.loads(REVIEW_PATH.read_text(encoding="utf-8"))
        review = document.get("players", []) if isinstance(document, dict) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        review = []
    key = (str(item.get("tour")), str(item.get("player_id")))
    review = [entry for entry in review
              if (str(entry.get("tour")), str(entry.get("player_id"))) != key]
    review.append(item)
    REVIEW_PATH.write_text(
        json.dumps({"players": review}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )


def ensure_player_image(tour: str, player_id, name: str, *, rank=None,
                        registry: dict[str, dict] | None = None,
                        session: requests.Session | None = None) -> dict | None:
    """Procura e guarda uma fotografia licenciada quando ainda não existe."""
    entries = registry if registry is not None else player_images.load_registry()
    existing = player_images.find_player_image(tour, player_id, name, entries)
    if existing:
        return existing
    if player_id is None or not name:
        return None

    client = session or requests.Session()
    client.headers.update({"User-Agent": USER_AGENT})
    key = f"{str(tour).casefold()}:{player_id}"
    try:
        wikidata_id, reason = _find_wikidata_item(client, name)
        filename = _wikidata_image(client, wikidata_id) if wikidata_id else None
        if not filename:
            raise ValueError(reason or "jogador sem fotografia P18 no Wikidata")
        metadata, reason = _commons_metadata(client, filename)
        if not metadata or not metadata.get("download_url"):
            raise ValueError(reason or "fotografia sem URL de download")
        response = _get(client, metadata.pop("download_url"))
        extension = _extension(response.headers.get("Content-Type", ""), response.url)
        asset_name = f"{str(tour).casefold()}-{player_id}-{_slug(name)}{extension}"
        ASSET_DIR.mkdir(parents=True, exist_ok=True)
        (ASSET_DIR / asset_name).write_bytes(response.content)
        entries[key] = {
            "name": name, "rank_at_import": rank,
            "path": f"../assets/players/{asset_name}",
            "wikidata_id": wikidata_id, "commons_file": filename,
            "modified": True, **metadata,
        }
        _write_registry(entries)
        return dict(entries[key])
    except (requests.RequestException, ValueError, OSError) as exc:
        _record_review({"tour": str(tour).casefold(), "player_id": player_id,
                        "name": name, "rank": rank, "reason": str(exc)})
        print(f"[aviso:foto] {name}: {exc}")
        return None


def sync(limit: int = 200, tours=("atp", "wta"), delay: float = 0.08) -> dict:
    registry = player_images.load_registry()
    review = []
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    summary = {"requested": 0, "existing": 0, "added": 0, "review": 0}

    for tour in tours:
        ranking = fetch_data.fetch_official_ranking(tour) or {}
        entries = sorted(ranking.values(), key=lambda item: item.get("rank") or 99999)[:limit]
        summary["requested"] += len(entries)
        for item in entries:
            player_id, name = item.get("player_id"), item.get("name")
            key = f"{tour}:{player_id}"
            if not player_id or not name:
                continue
            if key in registry:
                summary["existing"] += 1
                continue
            try:
                wikidata_id, reason = _find_wikidata_item(session, name)
                filename = _wikidata_image(session, wikidata_id) if wikidata_id else None
                if not filename:
                    reason = reason or "jogador sem fotografia P18 no Wikidata"
                    raise ValueError(reason)
                metadata, reason = _commons_metadata(session, filename)
                if not metadata or not metadata.get("download_url"):
                    raise ValueError(reason or "fotografia sem URL de download")
                response = _get(session, metadata.pop("download_url"))
                extension = _extension(response.headers.get("Content-Type", ""), response.url)
                asset_name = f"{tour}-{player_id}-{_slug(name)}{extension}"
                (ASSET_DIR / asset_name).write_bytes(response.content)
                registry[key] = {
                    "name": name, "rank_at_import": item.get("rank"),
                    "path": f"../assets/players/{asset_name}",
                    "wikidata_id": wikidata_id, "commons_file": filename,
                    "modified": True, **metadata,
                }
                summary["added"] += 1
            except (requests.RequestException, ValueError, OSError) as exc:
                review.append({"tour": tour, "player_id": player_id, "name": name,
                               "rank": item.get("rank"), "reason": str(exc)})
                summary["review"] += 1
            time.sleep(delay)

    _write_registry(registry)
    REVIEW_PATH.write_text(
        json.dumps({"players": review}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--tour", choices=("all", "atp", "wta"), default="all")
    parser.add_argument("--delay", type=float, default=0.08)
    args = parser.parse_args()
    tours = ("atp", "wta") if args.tour == "all" else (args.tour,)
    try:
        summary = sync(args.limit, tours, args.delay)
    except BaseException:
        fetch_data.persist_rapidapi_usage(status="player_images_failed", matches=0)
        raise
    fetch_data.persist_rapidapi_usage(status="player_images_synced", matches=0)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
