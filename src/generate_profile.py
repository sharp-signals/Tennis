"""
Gera fichas de jogador e guarda-as em knowledge/players/.

Uso (localmente ou via workflow manual):
    python -m src.generate_profile "Jannik Sinner" atp
    python -m src.generate_profile "Aryna Sabalenka" wta

Sem argumentos, gera para uma pequena lista de exemplo (útil para teste).
As fichas são markdown, uma por jogador, e podem ir para o repositório
(commit) para crescerem ao longo do tempo — a "base de conhecimento" na
sua forma mais simples e honesta: factos organizados, com amostra à
vista, sem modelo por cima.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
import unicodedata

from . import fetch_data
from .player_profile import build_player_profile_markdown

OUTPUT_DIR = "knowledge/players"

EXEMPLOS = [
    ("Jannik Sinner", "atp"),
    ("Carlos Alcaraz", "atp"),
]


def _slug(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def generate_one(player: str, tour: str) -> str | None:
    history = fetch_data.get_history(tour)

    # Tenta enriquecer com stats de carreira ricas (matchstat) — precisa
    # do ID do jogador, que vem do ranking oficial. Se não encontrar o ID
    # (jogador fora do ranking) ou a API falhar, a ficha gera na mesma só
    # com os dados do histórico.
    career_stats = None
    player_id = fetch_data.get_player_id_from_ranking(tour, player)
    if player_id:
        career_stats = fetch_data.fetch_player_career_stats(tour, player_id)

    md = build_player_profile_markdown(history, player, tour, career_stats=career_stats)
    if md is None:
        print(f"[aviso] '{player}' não encontrado no histórico {tour.upper()} — ficha não gerada.")
        return None

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, f"{_slug(player)}.md")
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=OUTPUT_DIR,
            prefix=".profile-", suffix=".tmp", delete=False,
        ) as temp_file:
            temp_file.write(md)
            temp_path = temp_file.name
        os.replace(temp_path, path)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
    career_note = " (com stats de carreira matchstat)" if career_stats else " (só histórico)"
    print(f"[info] Ficha gerada: {path}{career_note}")
    return path


def main() -> None:
    if len(sys.argv) >= 3:
        generate_one(sys.argv[1], sys.argv[2].lower())
    elif len(sys.argv) == 2:
        # só o nome — assume atp
        generate_one(sys.argv[1], "atp")
    else:
        print("[info] Sem argumentos — a gerar fichas de exemplo.")
        for player, tour in EXEMPLOS:
            generate_one(player, tour)


if __name__ == "__main__":
    main()
