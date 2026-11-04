"""Isolated visual prototype; not inserted into current reports."""
from __future__ import annotations

import html
from typing import Any, Mapping


def render_contextual_shadow_panel(shadow: Mapping[str, Any]) -> str:
    probability = 100.0 * float(shadow["probability_model_a"])
    interval = shadow["probability_interval_90_model_a"]
    odd = shadow["fair_odd_model_a"]
    rows = []
    for family in shadow.get("families", []):
        value = family.get("probability_model_a")
        pct = "N/D" if value is None else f"{100.0 * float(value):.1f}%"
        rows.append(
            '<div class="ctx-family">'
            f'<span>{html.escape(str(family.get("label") or family.get("key")))}</span>'
            f'<strong>{pct}</strong>'
            f'<small>{html.escape(str(family.get("data_state") or "N/D"))}</small>'
            '</div>'
        )
    return (
        '<section class="contextual-shadow" data-production-effect="false">'
        '<header><b>NOVO MODELO CONTEXTUAL</b><em>SHADOW · não altera decisões</em></header>'
        f'<div class="ctx-main"><strong>{probability:.1f}%</strong>'
        f'<span>intervalo 90%: {100*float(interval[0]):.1f}%–{100*float(interval[1]):.1f}%</span>'
        f'<span>fair odd: {float(odd["central"]):.2f} '
        f'({float(odd["lower"]):.2f}–{float(odd["upper"]):.2f})</span></div>'
        '<div class="ctx-families">' + "".join(rows) + '</div>'
        '<footer>Sem mercado, edge, PAPER ou GREEN.</footer></section>'
    )
