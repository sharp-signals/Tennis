"""
Gerador de relatório HTML — design escuro sóbrio, executivo, com gráficos
SVG (barras de confronto A-vs-B e medidores de percentagem).

Substitui a publicação em Telegra.ph (que não permite fundo escuro nem
gráficos). Gera uma página HTML autónoma por jogo, para publicar no
GitHub Pages. Sem dependências externas: os gráficos são SVG desenhado
à mão, o CSS está embebido, nada de bibliotecas.

Filosofia de design (ver frontend-design skill):
- Fundo carvão (#14161a), não preto — mais suave para leitura longa.
- Acento azul-aço para dados/favorito, verde-menta para sinais positivos.
- Selos de peso das discrepâncias reaproveitam 🔴/🟡/⚪.
- Assinatura: "placar" no topo, dois jogadores frente a frente com a odd
  de mercado ao centro, como um painel de estádio.
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import Optional


# --- paleta (tokens de cor) ---------------------------------------------
COLORS = {
    "bg": "#14161a",
    "surface": "#1c1f26",
    "surface_alt": "#23272f",
    "text": "#e6e9ef",
    "text_dim": "#9aa3b2",
    "steel": "#5b9bd5",      # azul-aço: dados, favorito
    "mint": "#4ecdc4",       # verde-menta: sinais positivos
    "amber": "#e0a34a",      # 🟡
    "red": "#e06c5b",        # 🔴
    "line": "#2c313b",
}


def _esc(text) -> str:
    return html.escape(str(text if text is not None else ""))


def _bar_comparison(label: str, a_name: str, a_val: float, b_name: str,
                    b_val: float, unit: str = "%", max_val: float = 100) -> str:
    """Barra de confronto A-vs-B (duas barras que crescem do centro)."""
    a_pct = min(100, 100 * a_val / max_val) if max_val else 0
    b_pct = min(100, 100 * b_val / max_val) if max_val else 0
    a_wins = a_val >= b_val
    a_color = COLORS["steel"] if a_wins else COLORS["text_dim"]
    b_color = COLORS["steel"] if not a_wins else COLORS["text_dim"]
    return f"""
    <div class="cmp">
      <div class="cmp-label">{_esc(label)}</div>
      <div class="cmp-row">
        <div class="cmp-val left">{_esc(a_val)}{unit}</div>
        <div class="cmp-track">
          <div class="cmp-fill left" style="width:{a_pct/2:.1f}%;background:{a_color}"></div>
          <div class="cmp-fill right" style="width:{b_pct/2:.1f}%;background:{b_color}"></div>
        </div>
        <div class="cmp-val right">{_esc(b_val)}{unit}</div>
      </div>
    </div>"""


def _gauge(label: str, value: float, sample: Optional[int] = None,
           max_val: float = 100) -> str:
    """Medidor semicircular para uma percentagem isolada."""
    pct = min(100, 100 * value / max_val) if max_val else 0
    # arco semicircular: 180 graus, raio 50
    import math
    angle = math.pi * (1 - pct / 100)
    x = 60 + 50 * math.cos(angle)
    y = 60 - 50 * math.sin(angle)
    large = 0
    color = COLORS["mint"] if pct >= 60 else (COLORS["amber"] if pct >= 40 else COLORS["red"])
    sample_txt = f'<tspan class="gauge-sample"> · {sample} jogos</tspan>' if sample else ""
    return f"""
    <div class="gauge">
      <svg viewBox="0 0 120 75" width="120" height="75">
        <path d="M 10 60 A 50 50 0 0 1 110 60" fill="none" stroke="{COLORS['line']}" stroke-width="8"/>
        <path d="M 10 60 A 50 50 0 {large} 1 {x:.1f} {y:.1f}" fill="none" stroke="{color}" stroke-width="8" stroke-linecap="round"/>
        <text x="60" y="52" text-anchor="middle" class="gauge-val">{value:.0f}%</text>
      </svg>
      <div class="gauge-label">{_esc(label)}{sample_txt}</div>
    </div>"""


def _markdown_inline(text: str) -> str:
    """Converte **negrito** e `código` para HTML, escapando o resto."""
    # escapar primeiro
    text = _esc(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    return text


def _weight_badge(line: str) -> tuple[str, str]:
    """Deteta o selo de peso (🔴/🟡/⚪) no início de uma linha e devolve
    (classe_css, texto_sem_emoji)."""
    stripped = line.lstrip()
    if stripped.startswith("🔴"):
        return "w-red", stripped[1:].strip()
    if stripped.startswith("🟡"):
        return "w-amber", stripped[1:].strip()
    if stripped.startswith("⚪"):
        return "w-white", stripped[1:].strip()
    return "", stripped


def _render_markdown_body(markdown_text: str) -> str:
    """Converte o markdown do relatório do Claude em HTML estruturado."""
    out: list[str] = []
    in_list = False

    def close_list():
        nonlocal in_list
        if in_list:
            out.append("</div>")
            in_list = False

    for raw in markdown_text.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            close_list()
            continue

        # cabeçalhos
        if line.startswith("### ") or line.startswith("#### "):
            close_list()
            title = line.split(" ", 1)[1]
            out.append(f'<h3 class="sec">{_markdown_inline(title)}</h3>')
        elif line.startswith("## "):
            close_list()
            title = line.split(" ", 1)[1]
            out.append(f'<h2 class="sec-main">{_markdown_inline(title)}</h2>')
        elif line.startswith("# "):
            continue  # o título principal já está no placar
        elif line.strip() in ("---", "***", "___"):
            close_list()
            out.append('<hr/>')
        elif line.lstrip().startswith(("- ", "* ")):
            if not in_list:
                out.append('<div class="items">')
                in_list = True
            item = line.lstrip()[2:]
            badge_class, clean = _weight_badge(item)
            if badge_class:
                out.append(f'<div class="item {badge_class}">{_markdown_inline(clean)}</div>')
            else:
                out.append(f'<div class="item">{_markdown_inline(item)}</div>')
        else:
            close_list()
            out.append(f'<p>{_markdown_inline(line)}</p>')

    close_list()
    return "\n".join(out)


def _build_charts(payload: dict) -> str:
    """Constrói os gráficos SVG a partir dos dados do payload, quando
    disponíveis. Escolhe barras (comparação A-vs-B) ou medidores conforme
    a estatística. Devolve HTML (pode ser vazio se não houver dados)."""
    a = _esc(payload.get("player_a", "A"))
    b = _esc(payload.get("player_b", "B"))
    charts: list[str] = []

    # Serviço/resposta — barras de confronto
    sa = payload.get("serve_return_stats_a") or {}
    sb = payload.get("serve_return_stats_b") or {}
    if sa and sb:
        rows = []
        pairs = [
            ("1º serviço ganho", "avg_first_serve_won_pct"),
            ("Break points salvos", "avg_break_points_saved_pct"),
            ("Aces", "avg_ace_pct"),
        ]
        for label, key in pairs:
            if sa.get(key) is not None and sb.get(key) is not None:
                rows.append(_bar_comparison(label, a, round(sa[key]*100, 1), b, round(sb[key]*100, 1)))
        if rows:
            charts.append(f'<div class="chart-block"><div class="chart-title">Serviço / Resposta</div>{"".join(rows)}</div>')

    # Forma recente — medidores lado a lado
    fa = payload.get("recent_form_a") or {}
    fb = payload.get("recent_form_b") or {}
    if fa.get("matches") and fb.get("matches"):
        g1 = _gauge(f"{a} (forma)", 100*fa["wins"]/fa["matches"], fa["matches"])
        g2 = _gauge(f"{b} (forma)", 100*fb["wins"]/fb["matches"], fb["matches"])
        charts.append(f'<div class="chart-block"><div class="chart-title">Forma recente</div><div class="gauges">{g1}{g2}</div></div>')

    if not charts:
        return ""
    return f'<section class="charts">{"".join(charts)}</section>'


def build_report_html(payload: dict, result: dict) -> str:
    """Gera a página HTML completa e autónoma para um jogo."""
    a = _esc(payload.get("player_a", "?"))
    b = _esc(payload.get("player_b", "?"))
    tournament = _esc(payload.get("tournament", ""))
    tier = _esc(payload.get("tier", ""))
    surface = _esc(payload.get("surface", ""))
    flag = _esc(result.get("flag", ""))
    date_str = datetime.now(timezone.utc).strftime("%d/%m/%Y")

    # Grau de confiança global (0-100) com cor por faixa
    conf = result.get("confidence_score")
    conf_reason = _esc(result.get("confidence_reason", ""))
    conf_html = ""
    if conf is not None:
        try:
            conf = int(conf)
            conf_color = COLORS["mint"] if conf >= 67 else (COLORS["amber"] if conf >= 34 else COLORS["red"])
            conf_label = "alta" if conf >= 67 else ("média" if conf >= 34 else "baixa")
            conf_html = f"""
    <div class="confidence">
      <div class="conf-head">
        <span class="conf-title">Confiança da leitura</span>
        <span class="conf-num" style="color:{conf_color}">{conf}/100 · {conf_label}</span>
      </div>
      <div class="conf-track"><div class="conf-fill" style="width:{conf}%;background:{conf_color}"></div></div>
      {f'<div class="conf-reason">{conf_reason}</div>' if conf_reason else ''}
    </div>"""
        except (ValueError, TypeError):
            pass

    odds = payload.get("market_odds_decimal") or {}
    odd_a = odds.get("player_a") if isinstance(odds, dict) else None
    odd_b = odds.get("player_b") if isinstance(odds, dict) else None
    odd_a_txt = f"{odd_a}" if odd_a else "—"
    odd_b_txt = f"{odd_b}" if odd_b else "—"

    charts = _build_charts(payload)
    body = _render_markdown_body(result.get("full_report_markdown", ""))

    return f"""<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{a} vs {b}</title>
<style>
:root {{
  --bg:{COLORS['bg']}; --surface:{COLORS['surface']}; --surface-alt:{COLORS['surface_alt']};
  --text:{COLORS['text']}; --dim:{COLORS['text_dim']}; --steel:{COLORS['steel']};
  --mint:{COLORS['mint']}; --amber:{COLORS['amber']}; --red:{COLORS['red']}; --line:{COLORS['line']};
}}
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{
  background:var(--bg); color:var(--text);
  font-family:'Segoe UI',system-ui,-apple-system,sans-serif;
  line-height:1.6; padding:0 0 60px;
  -webkit-font-smoothing:antialiased;
}}
.wrap {{ max-width:760px; margin:0 auto; padding:0 20px; }}

/* Placar (assinatura) */
.scoreboard {{
  background:linear-gradient(180deg,var(--surface-alt),var(--surface));
  border-bottom:2px solid var(--steel);
  padding:28px 20px 22px;
}}
.sb-inner {{ max-width:760px; margin:0 auto; }}
.sb-meta {{ color:var(--dim); font-size:13px; letter-spacing:.08em; text-transform:uppercase; margin-bottom:14px; }}
.sb-players {{ display:flex; align-items:center; justify-content:space-between; gap:16px; }}
.sb-name {{ font-size:clamp(20px,5vw,30px); font-weight:800; letter-spacing:-.02em; flex:1; }}
.sb-name.right {{ text-align:right; }}
.sb-odds {{ text-align:center; padding:0 8px; }}
.sb-odd {{ font-size:22px; font-weight:700; color:var(--steel); }}
.sb-vs {{ font-size:12px; color:var(--dim); letter-spacing:.1em; margin:2px 0; }}
.sb-flag {{ display:inline-block; margin-top:14px; font-size:14px; padding:4px 12px; border-radius:20px; background:var(--surface); border:1px solid var(--line); }}

/* Confiança da leitura */
.confidence {{ margin-top:16px; max-width:420px; }}
.conf-head {{ display:flex; justify-content:space-between; align-items:baseline; margin-bottom:6px; }}
.conf-title {{ font-size:12px; text-transform:uppercase; letter-spacing:.08em; color:var(--dim); }}
.conf-num {{ font-size:15px; font-weight:700; }}
.conf-track {{ height:8px; background:var(--surface-alt); border-radius:5px; overflow:hidden; }}
.conf-fill {{ height:100%; border-radius:5px; }}
.conf-reason {{ font-size:13px; color:var(--dim); margin-top:6px; font-style:italic; }}

/* Gráficos */
.charts {{ margin:26px 0; }}
.chart-block {{ background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:18px; margin-bottom:16px; }}
.chart-title {{ font-size:13px; text-transform:uppercase; letter-spacing:.08em; color:var(--dim); margin-bottom:14px; }}
.cmp {{ margin:10px 0; }}
.cmp-label {{ font-size:13px; color:var(--dim); margin-bottom:4px; text-align:center; }}
.cmp-row {{ display:flex; align-items:center; gap:8px; }}
.cmp-val {{ font-size:14px; font-weight:700; width:56px; }}
.cmp-val.left {{ text-align:right; }}
.cmp-track {{ flex:1; height:10px; background:var(--surface-alt); border-radius:6px; display:flex; overflow:hidden; }}
.cmp-fill {{ height:100%; }}
.cmp-fill.left {{ margin-left:auto; border-radius:6px 0 0 6px; }}
.cmp-fill.right {{ border-radius:0 6px 6px 0; }}
.gauges {{ display:flex; justify-content:space-around; flex-wrap:wrap; gap:12px; }}
.gauge {{ text-align:center; }}
.gauge-val {{ fill:var(--text); font-size:20px; font-weight:800; }}
.gauge-label {{ font-size:12px; color:var(--dim); margin-top:2px; }}

/* Corpo */
.wrap {{ padding-top:26px; }}
h2.sec-main {{ font-size:20px; margin:26px 0 12px; color:var(--text); }}
h3.sec {{ font-size:16px; margin:22px 0 10px; color:var(--steel); border-left:3px solid var(--steel); padding-left:10px; }}
p {{ margin:10px 0; color:var(--text); }}
.items {{ margin:10px 0; }}
.item {{ background:var(--surface); border:1px solid var(--line); border-radius:8px; padding:10px 12px; margin:6px 0; font-size:15px; }}
.item.w-red {{ border-left:4px solid var(--red); }}
.item.w-amber {{ border-left:4px solid var(--amber); }}
.item.w-white {{ border-left:4px solid var(--dim); opacity:.85; }}
code {{ background:var(--surface-alt); padding:1px 6px; border-radius:4px; font-size:13px; color:var(--mint); }}
hr {{ border:none; border-top:1px solid var(--line); margin:20px 0; }}
strong {{ color:#fff; font-weight:700; }}
.footer {{ text-align:center; color:var(--dim); font-size:12px; margin-top:30px; }}
</style>
</head>
<body>
<header class="scoreboard">
  <div class="sb-inner">
    <div class="sb-meta">{tournament} · {tier} · {surface} · {date_str}</div>
    <div class="sb-players">
      <div class="sb-name">{a}</div>
      <div class="sb-odds">
        <div class="sb-odd">{odd_a_txt}</div>
        <div class="sb-vs">VS</div>
        <div class="sb-odd">{odd_b_txt}</div>
      </div>
      <div class="sb-name right">{b}</div>
    </div>
    <div class="sb-flag">{flag} sinal</div>
    {conf_html}
  </div>
</header>
<div class="wrap">
  {charts}
  {body}
  <div class="footer">Tennis Pre-Live Bot · análise informativa, não é recomendação de aposta</div>
</div>
</body>
</html>"""
