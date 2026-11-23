"""Gera a ficha JSON v2 de um jogador e reconstrói o índice pesquisável."""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import Iterable

from . import fetch_data
from .player_profile_contract import build_search_index_entry
from .player_profile_v2 import build_player_profile_v2_record


OUTPUT_ROOT = Path("data/player_profiles/v2")


def _slug(name: str) -> str:
    value = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.stem}-", suffix=".tmp", delete=False,
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            temp_path = Path(handle.name)
        os.replace(temp_path, path)
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()


def rebuild_index(
    output_root: Path = OUTPUT_ROOT,
    profile_paths: Iterable[Path] | None = None,
) -> Path:
    entries = []
    paths = profile_paths if profile_paths is not None else output_root.glob("*/*.json")
    for path in sorted(set(paths)):
        if path.name == "index.json":
            continue
        profile = json.loads(path.read_text(encoding="utf-8"))
        entry = build_search_index_entry(profile)
        entry["profile_path"] = path.relative_to(output_root).as_posix()
        entries.append(entry)
    entries.sort(key=lambda row: (str(row.get("tour") or ""), str(row.get("name") or "").casefold()))
    index_path = output_root / "index.json"
    _write_json_atomic(index_path, {"schema_version": 2, "players": entries})
    return index_path


def generate_one(player: str, tour: str, output_root: Path = OUTPUT_ROOT) -> Path | None:
    normalized_tour = tour.strip().lower()
    history = fetch_data.get_history(normalized_tour)
    odds_history = fetch_data.get_historical_odds_history(
        normalized_tour, refresh_current=False,
    )
    player_id = fetch_data.get_player_id_from_ranking(normalized_tour, player)
    profile = build_player_profile_v2_record(
        history, player, normalized_tour, player_id=player_id,
        odds_history=odds_history,
    )
    if profile is None:
        return None
    path = output_root / normalized_tour / f"{_slug(profile['player']['name'])}.json"
    _write_json_atomic(path, profile)
    rebuild_index(output_root)
    return path


def main() -> int:
    if len(sys.argv) != 3:
        print("Uso: python -m src.generate_profile_v2 \"Nome do jogador\" atp|wta")
        return 2
    path = generate_one(sys.argv[1], sys.argv[2])
    if path is None:
        print(f"[aviso] jogador não encontrado: {sys.argv[1]}")
        return 1
    print(f"[info] ficha v2 gerada: {path}")
    print(f"[info] índice atualizado: {OUTPUT_ROOT / 'index.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
