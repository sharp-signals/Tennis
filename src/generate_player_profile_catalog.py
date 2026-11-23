"""Gera em lote as fichas v2 e um catálogo HTML pesquisável.

O processo reutiliza uma única leitura do histórico por tour. Não consulta
ranking individual pela API e não altera qualquer componente de pricing.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path

import pandas as pd

from . import fetch_data
from .generate_profile_v2 import OUTPUT_ROOT, _slug, _write_json_atomic, rebuild_index
from .player_profile_v2 import build_player_profile_v2_record


DOCS_ROOT = Path("docs/jogadores")
FAMILY_LABELS = {
    "recent_form": "Forma recente e contexto competitivo",
    "structural_strength": "Força estrutural",
    "surface_conditions": "Superfície e condições",
    "serve_return": "Serviço e resposta",
    "historical_market_context": "Histórico por faixa de odd",
}


def _history_dates(history: pd.DataFrame) -> pd.Series:
    source = history.get("tourney_date", history.get("date", pd.Series(index=history.index, dtype=object)))
    raw = source.astype("string").str.strip()
    compact = pd.to_datetime(raw, format="%Y%m%d", errors="coerce", utc=True)
    return compact.fillna(pd.to_datetime(raw, errors="coerce", utc=True))


def select_active_players(
    history: pd.DataFrame,
    *,
    cutoff: datetime,
    active_days: int = 730,
) -> list[str]:
    """Seleciona identidades com jogos válidos dentro da janela definida."""
    if history.empty or active_days < 1:
        return []
    dates = _history_dates(history)
    lower = pd.Timestamp(cutoff) - pd.Timedelta(days=active_days)
    eligible = history[dates.notna() & (dates < pd.Timestamp(cutoff)) & (dates >= lower)]
    counts: Counter[str] = Counter()
    representatives: dict[str, str] = {}
    for column in ("winner_name", "loser_name"):
        for raw in eligible.get(column, pd.Series(dtype=object)).dropna():
            name = str(raw).strip()
            if name:
                identity = min(_identity_keys(name), key=lambda value: (len(value), value))
                counts[identity] += 1
                current = representatives.get(identity)
                if current is None or len(name) < len(current):
                    representatives[identity] = name
    ordered = sorted(counts, key=lambda key: (-counts[key], representatives[key].casefold()))
    return [representatives[key] for key in ordered]


def _identity_keys(player: str) -> set[str]:
    normalized = fetch_data._normalize_name(player)
    keys = {normalized}
    for canonical, variants in fetch_data._HISTORICAL_EXACT_NAME_ALIASES.items():
        family = {
            fetch_data._normalize_name(canonical),
            *(fetch_data._normalize_name(value) for value in variants),
        }
        if normalized in family:
            keys.update(family)
    return keys


def _player_row_index(history: pd.DataFrame) -> dict[str, set[object]]:
    index: dict[str, set[object]] = {}
    for column in ("winner_name", "loser_name"):
        if column not in history.columns:
            continue
        for row_index, raw in history[column].dropna().items():
            key = fetch_data._normalize_name(str(raw))
            if key:
                index.setdefault(key, set()).add(row_index)
    return index


def _rows_for_player(
    history: pd.DataFrame, row_index: dict[str, set[object]], player: str,
) -> pd.DataFrame:
    identity_keys = _identity_keys(player)
    selected: set[object] = set()
    for key in identity_keys:
        selected.update(row_index.get(key, set()))
    if not selected:
        result = history.iloc[0:0].copy()
    else:
        result = history.loc[history.index.isin(selected)].copy()
    result.attrs["history_cache_key"] = (
        "player_profile_subset",
        history.attrs.get("history_cache_key"),
        tuple(sorted(identity_keys)),
    )
    return result


def generate_catalog(
    *,
    tours: tuple[str, ...] = ("atp", "wta"),
    output_root: Path = OUTPUT_ROOT,
    docs_root: Path = DOCS_ROOT,
    active_days: int = 730,
    max_players: int | None = None,
    generated_at_utc: str | None = None,
) -> dict:
    generated_at = generated_at_utc or datetime.now(timezone.utc).isoformat()
    cutoff = pd.to_datetime(generated_at, utc=True).to_pydatetime()
    counts: dict[str, int] = {}
    skipped: dict[str, int] = {}
    generated_paths: set[Path] = set()

    for tour in tours:
        normalized = str(tour).strip().lower()
        if normalized not in {"atp", "wta"}:
            raise ValueError("tour deve ser atp ou wta")
        history = fetch_data.get_history(normalized)
        odds_history = fetch_data.get_historical_odds_history(
            normalized, refresh_current=False,
        )
        history_index = _player_row_index(history)
        odds_index = _player_row_index(odds_history)
        players = select_active_players(history, cutoff=cutoff, active_days=active_days)
        if max_players is not None and max_players > 0:
            players = players[:max_players]
        counts[normalized] = 0
        skipped[normalized] = 0
        for player in players:
            player_history = _rows_for_player(history, history_index, player)
            player_odds_history = _rows_for_player(odds_history, odds_index, player)
            profile = build_player_profile_v2_record(
                player_history,
                player,
                normalized,
                odds_history=player_odds_history,
                generated_at_utc=generated_at,
            )
            if profile is None:
                skipped[normalized] += 1
                continue
            path = output_root / normalized / f"{_slug(profile['player']['name'])}.json"
            _write_json_atomic(path, profile)
            generated_paths.add(path)
        counts[normalized] = sum(
            path.parent.name == normalized for path in generated_paths
        )

    index_path = rebuild_index(output_root, generated_paths)
    index_payload = json.loads(index_path.read_text(encoding="utf-8"))
    render_catalog(index_payload, output_root=output_root, docs_root=docs_root)
    summary = {
        "generated_at_utc": generated_at,
        "active_days": active_days,
        "generated": counts,
        "skipped": skipped,
        "players_in_index": len(index_payload.get("players") or []),
    }
    _write_json_atomic(output_root / "generation-summary.json", summary)
    return summary


def _format_value(metric: dict) -> str:
    value = metric.get("value")
    unit = metric.get("unit")
    if value is None:
        return "Sem dados"
    if unit in {"win_rate", "rate", "rate_within_ranked_results"}:
        return f"{100 * float(value):.1f}%"
    if unit == "rank":
        return f"#{float(value):.0f}"
    if unit in {"points", "matches"}:
        return f"{float(value):.0f}"
    if isinstance(value, list):
        return f"{len(value)} períodos"
    return escape(str(value))


def _metric_card(metric: dict) -> str:
    sample = metric.get("sample_assessment") or {}
    context = metric.get("context") or {}
    record = ""
    if "wins" in context and "losses" in context:
        record = f'<div class="record">{context["wins"]}V–{context["losses"]}D</div>'
    bar = ""
    if metric.get("unit") in {"win_rate", "rate", "rate_within_ranked_results"} and metric.get("value") is not None:
        width = max(0.0, min(100.0, 100 * float(metric["value"])))
        bar = f'<div class="bar"><i style="width:{width:.1f}%"></i></div>'
    return (
        '<article class="metric">'
        f'<div class="metric-label">{escape(str(metric.get("label") or ""))}</div>'
        f'<div class="metric-value">{_format_value(metric)}</div>'
        f'{bar}{record}<div class="sample">n={metric.get("sample_size") or 0} · '
        f'{escape(str(sample.get("label") or "Sem classificação"))}</div>'
        '</article>'
    )


def _ranking_chart(metric: dict) -> str:
    values = [row for row in (metric.get("value") or []) if row.get("typical_rank")]
    if not values:
        return ""
    ranks = [float(row["typical_rank"]) for row in values]
    highest = max(ranks)
    lowest = min(ranks)
    span = max(1.0, highest - lowest)
    width = 680.0
    points = []
    labels = []
    rank_labels = []
    for index, row in enumerate(values):
        x = 20.0 if len(values) == 1 else 20.0 + index * (width - 40.0) / (len(values) - 1)
        y = 20.0 + (float(row["typical_rank"]) - lowest) * 120.0 / span
        points.append(f"{x:.1f},{y:.1f}")
        labels.append(f'<text x="{x:.1f}" y="170" text-anchor="middle">{row["year"]}</text>')
        rank = float(row["typical_rank"])
        rank_text = f"#{rank:.0f}" if rank.is_integer() else f"#{rank:.1f}"
        rank_labels.append(
            f'<text class="rank-value" x="{x:.1f}" y="{max(12.0, y - 10.0):.1f}" '
            f'text-anchor="middle">{rank_text}</text>'
        )
    circles = "".join(
        f'<circle cx="{point.split(",")[0]}" cy="{point.split(",")[1]}" r="5"/>'
        for point in points
    )
    return (
        '<div class="chart"><h3>Evolução do ranking típico</h3>'
        f'<svg viewBox="0 0 680 185" role="img" aria-label="Evolução anual do ranking"><polyline points="{" ".join(points)}"/>'
        f'{circles}'
        f'{"".join(rank_labels)}{"".join(labels)}</svg>'
        '<div class="chart-note">O número junto de cada ponto é o ranking típico dessa época.</div></div>'
    )


def _season_table(metric: dict) -> str:
    rows = []
    for point in metric.get("value") or []:
        cells = []
        for key in ("overall", "hard_outdoor", "indoor", "clay", "grass"):
            record = point.get(key) or {}
            rate = record.get("win_rate")
            text = "—" if rate is None else f'{100 * float(rate):.1f}% ({record.get("matches", 0)})'
            cells.append(f"<td>{text}</td>")
        rows.append(f'<tr><th>{point.get("year")}</th>{"".join(cells)}</tr>')
    if not rows:
        return ""
    return (
        '<div class="table-wrap"><table><thead><tr><th>Época</th><th>Geral</th>'
        '<th>Hard outdoor</th><th>Indoor</th><th>Clay</th><th>Grass</th></tr></thead><tbody>'
        f'{"".join(rows)}</tbody></table></div>'
    )


def render_profile(profile: dict) -> str:
    player = profile.get("player") or {}
    sample = profile.get("overall_sample") or {}
    grouped: dict[str, list[dict]] = {}
    season_table = ""
    ranking_chart = ""
    for metric in profile.get("metrics") or []:
        if metric.get("metric_id") == "season_surface_evolution":
            season_table = _season_table(metric)
        if metric.get("metric_id") == "ranking_by_year":
            ranking_chart = _ranking_chart(metric)
        grouped.setdefault(str(metric.get("family") or "other"), []).append(metric)
    sections = []
    for family, metrics in grouped.items():
        cards = "".join(_metric_card(metric) for metric in metrics if not isinstance(metric.get("value"), list))
        extra = season_table if family == "surface_conditions" else ""
        if family == "structural_strength":
            extra += ranking_chart
        sections.append(
            f'<section><h2>{escape(FAMILY_LABELS.get(family, family))}</h2>'
            f'<div class="metrics">{cards}</div>{extra}</section>'
        )
    alert = ""
    if any(item.get("severity") == "CRITICAL" for item in profile.get("alerts") or []):
        alert = '<div class="alert">Amostra inferior a 20 jogos: leitura apenas indicativa.</div>'
    return f"""<!doctype html>
<html lang="pt-PT"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(str(player.get('name') or 'Jogador'))} · Fenzobot</title>{_styles()}</head>
<body><main><a class="back" href="../index.html">← Voltar ao catálogo</a>
<header><div><span class="eyebrow">FICHA DE JOGADOR · {escape(str(player.get('tour') or '').upper())}</span>
<h1>{escape(str(player.get('name') or ''))}</h1></div>
<div class="hero-stat"><b>{sample.get('matches', 0)}</b><span>jogos na base</span></div></header>
{alert}<div class="meta">Amostra: {escape(str(sample.get('label') or sample.get('status') or ''))} · atualização {escape(str(profile.get('generated_at_utc') or ''))}</div>
{"".join(sections)}
<footer>Ficha factual. Métricas descritivas não alteram automaticamente a fair odd.</footer></main></body></html>"""


def _styles() -> str:
    return """<style>
:root{color-scheme:dark;--bg:#06131f;--panel:#0e2940;--line:#24506d;--text:#f5f8fb;--muted:#8fb4d0;--cyan:#42ddd4;--blue:#55a9ff;--warn:#ffc857}*{box-sizing:border-box}body{margin:0;background:linear-gradient(145deg,#04101a,#09233a);color:var(--text);font-family:Inter,Segoe UI,sans-serif}main{max-width:1180px;margin:auto;padding:30px 22px 60px}header{display:flex;justify-content:space-between;align-items:end;gap:24px;padding:28px;background:var(--panel);border:1px solid var(--line);border-radius:22px}h1{font-size:clamp(34px,7vw,64px);margin:6px 0}.eyebrow{color:var(--cyan);font-weight:800;letter-spacing:.12em}.hero-stat{text-align:right}.hero-stat b{display:block;font-size:38px;color:var(--blue)}.hero-stat span,.meta,.sample,.record,footer{color:var(--muted)}.back{color:var(--cyan);text-decoration:none;display:inline-block;margin-bottom:18px}.alert{margin:18px 0;padding:16px;border:1px solid #805f19;background:#30270e;color:var(--warn);border-radius:14px;font-weight:700}.meta{margin:16px 4px 28px}section{margin-top:22px;padding:24px;background:rgba(14,41,64,.9);border:1px solid var(--line);border-radius:20px}h2{margin-top:0}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px}.metric{padding:16px;background:#081d2d;border-radius:14px;border:1px solid #173d57}.metric-label{min-height:42px;color:#c9deed}.metric-value{font-size:26px;font-weight:800;color:var(--cyan);margin:8px 0}.bar{height:7px;background:#173d57;border-radius:9px;overflow:hidden}.bar i{display:block;height:100%;background:linear-gradient(90deg,var(--blue),var(--cyan))}.sample{font-size:13px;margin-top:8px}.table-wrap{overflow:auto;margin-top:18px}table{width:100%;border-collapse:collapse}th,td{padding:11px;text-align:left;border-bottom:1px solid var(--line)}.chart{margin-top:18px;padding:16px;background:#081d2d;border-radius:14px}.chart h3{margin:0 0 8px}.chart svg{width:100%;height:auto}.chart polyline{fill:none;stroke:var(--cyan);stroke-width:4}.chart circle{fill:var(--blue);stroke:white;stroke-width:2}.chart text{fill:var(--muted);font-size:13px}.chart-note{color:var(--muted);font-size:13px}footer{margin-top:28px;text-align:center}@media(max-width:600px){header{align-items:flex-start;flex-direction:column}.hero-stat{text-align:left}}
.chart .rank-value{fill:var(--cyan);font-weight:800}
</style>"""


def render_catalog(index_payload: dict, *, output_root: Path, docs_root: Path) -> Path:
    docs_root.mkdir(parents=True, exist_ok=True)
    players = []
    for entry in index_payload.get("players") or []:
        source = output_root / str(entry.get("profile_path") or "")
        if not source.exists():
            continue
        profile = json.loads(source.read_text(encoding="utf-8"))
        tour = str(entry.get("tour") or "")
        slug = _slug(str(entry.get("name") or ""))
        detail = docs_root / tour / f"{slug}.html"
        detail.parent.mkdir(parents=True, exist_ok=True)
        detail.write_text(render_profile(profile), encoding="utf-8")
        players.append({**entry, "href": f"{tour}/{slug}.html"})
    cards = "".join(
        '<a class="player-card" '
        f'href="{escape(str(row["href"]))}" data-search="{escape(str(row.get("name") or "").casefold())}" '
        f'data-tour="{escape(str(row.get("tour") or ""))}"><b>{escape(str(row.get("name") or ""))}</b>'
        f'<span>{escape(str(row.get("tour") or "").upper())} · ranking {row.get("current_rank") or "N/D"}</span>'
        f'<small>{row.get("matches") or 0} jogos · {escape(str(row.get("sample_status") or ""))}</small></a>'
        for row in players
    )
    html = f"""<!doctype html><html lang="pt-PT"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Jogadores · Fenzobot</title>{_styles()}<style>.controls{{display:flex;gap:10px;margin:22px 0;flex-wrap:wrap}}input,select{{background:#081d2d;color:white;border:1px solid var(--line);border-radius:12px;padding:13px 15px;font-size:16px}}input{{flex:1;min-width:230px}}.players{{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px}}.player-card{{display:flex;flex-direction:column;gap:7px;padding:18px;background:var(--panel);border:1px solid var(--line);border-radius:15px;color:white;text-decoration:none}}.player-card:hover{{border-color:var(--cyan);transform:translateY(-1px)}}.player-card span,.player-card small{{color:var(--muted)}}.count{{color:var(--cyan)}}</style></head>
<body><main><header><div><span class="eyebrow">BASE DE JOGADORES</span><h1>Fichas Fenzobot</h1><p>Pesquisa simples por jogador e circuito.</p></div><div class="hero-stat"><b class="count">{len(players)}</b><span>jogadores</span></div></header>
<div class="controls"><input id="search" type="search" placeholder="Pesquisar jogador…"><select id="tour"><option value="">ATP + WTA</option><option value="atp">ATP</option><option value="wta">WTA</option></select></div>
<div class="players" id="players">{cards}</div><footer>Base factual independente do mercado.</footer></main>
<script>const q=document.querySelector('#search'),t=document.querySelector('#tour'),cards=[...document.querySelectorAll('.player-card')];function filter(){{const s=q.value.trim().toLocaleLowerCase('pt'),v=t.value;let n=0;cards.forEach(c=>{{const show=(!s||c.dataset.search.includes(s))&&(!v||c.dataset.tour===v);c.hidden=!show;if(show)n++}});document.querySelector('.count').textContent=n}}q.addEventListener('input',filter);t.addEventListener('change',filter);</script></body></html>"""
    path = docs_root / "index.html"
    path.write_text(html, encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Gera catálogo pesquisável de jogadores")
    parser.add_argument("--tour", choices=("atp", "wta", "both"), default="both")
    parser.add_argument("--active-days", type=int, default=730)
    parser.add_argument("--max-players", type=int, default=0)
    args = parser.parse_args()
    tours = ("atp", "wta") if args.tour == "both" else (args.tour,)
    summary = generate_catalog(
        tours=tours,
        active_days=args.active_days,
        max_players=args.max_players or None,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
