"""
Fichas de jogador — versão leve (29/07/2026).

Gera uma ficha markdown por jogador a partir do histórico que já
carregamos (TennisMyLife/Sackmann), juntando num só sítio o que o resto
do bot já calcula disperso: forma, piso, serviço, recuperação após 1º
set, set decisivo, canhotos/destros, regresso de pausa, fase do torneio.

Princípio central (honestidade estatística): CADA número vem com a sua
amostra ao lado, e um rótulo de fiabilidade baseado só no tamanho da
amostra. Não há modelo, não há pesos, não há previsão — é uma vista
organizada dos factos, para o utilizador (ex-tenista) cruzar com o que
sabe. É deliberadamente simples: não é o sistema quantitativo completo
(SQLite/bayesiano), é a fundação honesta sobre a qual isso poderia
assentar no futuro, se alguma vez fizer sentido.

Sem promessas de vantagem: o backtest (ver backtest.py) mostrou que
estes sinais não batem o mercado. A ficha organiza informação para
leitura humana, não afirma que prevê resultados.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from . import fetch_data


def _reliability_label(sample_size: int) -> str:
    """Rótulo de fiabilidade baseado SÓ no tamanho da amostra — a coisa
    mais honesta que podemos dizer sem um modelo estatístico a sério."""
    if sample_size < 10:
        return "⚠️ amostra muito pequena"
    if sample_size < 30:
        return "amostra pequena"
    if sample_size < 100:
        return "amostra razoável"
    return "amostra sólida"


def _pct(wins: int, total: int) -> str:
    if total == 0:
        return "n/d"
    return f"{100 * wins / total:.1f}%"


def _format_career_stats_section(career: dict) -> list[str]:
    """Formata a secção de stats de carreira (matchstat / getH2HVsAllOppStats)."""
    lines = ["## Stats de carreira (fonte: matchstat)", ""]
    stats = career.get("playerStats") or career.get("player1Stats") or career
    if not isinstance(stats, dict):
        return []

    def g(key):
        return stats.get(key)

    played = g("statMatchesPlayed") or g("matchesPlayed")
    if played:
        lines.append(f"- Jogos de carreira na base: **{played}**")
    if g("avgTime"):
        lines.append(f"- Duração média de jogo: **{g('avgTime')}**")
    if g("firstServePercentage") is not None:
        lines.append(f"- 1º serviço dentro: **{g('firstServePercentage')}%** · "
                     f"ganho no 1º: **{g('winningOnFirstServePercentage')}%** · "
                     f"ganho no 2º: **{g('winningOnSecondServePercentage')}%**")
    if g("returnPtsWinPercentage") is not None:
        lines.append(f"- Pontos de resposta ganhos: **{g('returnPtsWinPercentage')}%** · "
                     f"break points convertidos: **{g('breakpointsWonPercentage')}%**")
    if g("firstSetWinMatchWinPercentage") is not None:
        lines.append(f"- Quando ganha o 1º set, fecha o jogo: **{g('firstSetWinMatchWinPercentage')}%** "
                     f"(quando perde o 1º, recupera: **{g('firstSetLoseMatchWinPercentage')}%**)")
    if g("decidingSetWinPercentage") is not None:
        lines.append(f"- Set decisivo: **{g('decidingSetWinPercentage')}%** · "
                     f"tiebreaks: **{g('totalTBWinPercentage')}%**")
    lines.append("")
    lines.append("*Nota: stats de carreira acumulada — para um jogador em fim de "
                 "carreira podem descrever o auge, não o presente. Cruza com a forma "
                 "recente e o registo da época atual.*")
    lines.append("")
    return lines


def build_player_profile_markdown(history: pd.DataFrame, player: str, tour: str,
                                  career_stats: dict | None = None) -> Optional[str]:
    """
    Devolve a ficha do jogador em markdown, ou None se o jogador não for
    encontrado no histórico. Reutiliza as funções compute_* existentes —
    não recalcula nada de forma diferente do resto do bot. Se `career_stats`
    for fornecido (do getH2HVsAllOppStats via matchstat), acrescenta uma
    secção rica de carreira.
    """
    resolved = fetch_data.resolve_player_name(history, player)
    if resolved is None:
        return None
    player = resolved

    lines: list[str] = []
    lines.append(f"# {player}")
    lines.append("")
    lines.append(
        f"*Ficha gerada em {datetime.now(timezone.utc).strftime('%Y-%m-%d')} "
        f"({tour.upper()}). Cada número traz a amostra ao lado — a amostra "
        f"é o que distingue um sinal real de ruído. Isto é informação para "
        f"leitura, não uma previsão.*"
    )
    lines.append("")

    if career_stats:
        lines.extend(_format_career_stats_section(career_stats))

    # --- Ranking ---
    ranking = fetch_data.get_player_ranking(history, player)
    if ranking:
        pts = f", {ranking['points']} pts" if ranking.get("points") else ""
        as_of = str(ranking.get("as_of") or "?")[:10]
        lines.append(f"**Ranking:** #{ranking['rank']}{pts} (à data de {as_of})")
        lines.append("")

    # --- Forma recente (várias janelas, para mostrar estabilidade) ---
    lines.append("## Forma recente")
    for n in (5, 10, 20):
        form = fetch_data.compute_recent_form(history, player, n)
        if form and form["matches"] > 0:
            note = " — janela curta, instável" if n == 5 else ""
            lines.append(f"- Últimos {form['matches']}: **{form['wins']}-{form['losses']}** "
                         f"({_pct(form['wins'], form['matches'])}){note}")
    lines.append("")

    # --- Piso ---
    surface = fetch_data.compute_surface_stats(history, player)
    if surface:
        lines.append("## Por piso (carreira)")
        for surf in ("Hard", "Clay", "Grass"):
            s = surface.get(surf)
            if s and s["matches"] > 0:
                lines.append(f"- {surf}: **{_pct(s['wins'], s['matches'])}** "
                             f"({s['wins']}-{s['losses']}, {s['matches']} jogos — {_reliability_label(s['matches'])})")
        lines.append("")

    # --- Serviço/resposta ---
    serve = fetch_data.compute_serve_return_stats(history, player, 20)
    if serve and serve.get("matches_used", 0) > 0:
        lines.append(f"## Serviço/resposta (últimos {serve['matches_used']} jogos)")
        lines.append(f"- Ace%: {serve['avg_ace_pct'] * 100:.1f}% · Dupla falta%: {serve['avg_double_fault_pct'] * 100:.1f}%")
        lines.append(f"- 1º serviço dentro: {serve['avg_first_serve_in_pct'] * 100:.1f}% · "
                     f"ganho no 1º serviço: {serve['avg_first_serve_won_pct'] * 100:.1f}%")
        lines.append(f"- Break points salvos: {serve['avg_break_points_saved_pct'] * 100:.1f}%")
        lines.append("")

    # --- Situações específicas (a parte que o Hugo queria destacar) ---
    lines.append("## Situações específicas")
    lines.append("")

    set1 = fetch_data.compute_set1_comeback_stats(history, player)
    if set1:
        lines.append("**Depois de perder o 1º set:**")
        for fmt, label in (("bo3", "Melhor de 3"), ("bo5", "Melhor de 5")):
            s = set1.get(fmt)
            if s:
                lines.append(f"- {label}: recuperou **{s['comeback_rate_pct']}%** "
                             f"({s['matches_lost_set1_won_overall']}/{s['matches_lost_set1']} jogos — "
                             f"{_reliability_label(s['matches_lost_set1'])})")
        lines.append("")

    deciding = fetch_data.compute_deciding_set_stats(history, player)
    if deciding:
        lines.append("**Em set decisivo:**")
        for fmt, label in (("bo3", "Melhor de 3"), ("bo5", "Melhor de 5")):
            s = deciding.get(fmt)
            if s:
                lines.append(f"- {label}: **{s['win_rate_pct']}%** "
                             f"({s['wins']}/{s['matches_went_the_distance']} jogos — "
                             f"{_reliability_label(s['matches_went_the_distance'])})")
        lines.append("")

    layoff = fetch_data.compute_return_from_layoff_stats(history, player)
    if layoff:
        lines.append(f"**Regresso após pausa longa (60+ dias):** "
                     f"**{layoff['win_rate_pct']}%** "
                     f"({layoff['wins_after_layoff']}/{layoff['matches_after_layoff']} jogos — "
                     f"{_reliability_label(layoff['matches_after_layoff'])})")
        lines.append("")

    handedness = fetch_data.compute_handedness_matchup_stats(history, player)
    if handedness:
        lines.append("**Contra canhotos vs destros:**")
        for key, label in (("vs_left_handed", "Contra canhotos"), ("vs_right_handed", "Contra destros")):
            s = handedness.get(key)
            if s:
                lines.append(f"- {label}: **{_pct(s['wins'], s['matches'])}** "
                             f"({s['wins']}-{s['losses']}, {s['matches']} jogos — {_reliability_label(s['matches'])})")
        lines.append("")

    round_stage = fetch_data.compute_round_stage_stats(history, player)
    if round_stage:
        lines.append("**Por fase do torneio:**")
        for key, label in (("early_rounds", "Rondas iniciais"), ("late_rounds", "Rondas finais")):
            s = round_stage.get(key)
            if s:
                lines.append(f"- {label}: **{_pct(s['wins'], s['matches'])}** "
                             f"({s['wins']}-{s['losses']}, {s['matches']} jogos — {_reliability_label(s['matches'])})")
        lines.append("")

    lines.append("---")
    lines.append(
        "*Como ler: uma diferença só é interessante se a amostra for "
        "suficiente. Ex.: 75% de recuperação em 4 jogos não diz nada; "
        "40% em 78 jogos já é um padrão. Cruza sempre com o que sabes do "
        "jogador — lesões, mudanças recentes, contexto — que os números "
        "não capturam.*"
    )

    return "\n".join(lines)
