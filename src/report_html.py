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
                    b_val: float, unit: str = "%", max_val: float = 100,
                    label_is_html: bool = False) -> str:
    """Barra de confronto A-vs-B (duas barras que crescem do centro)."""
    a_pct = min(100, 100 * a_val / max_val) if max_val else 0
    b_pct = min(100, 100 * b_val / max_val) if max_val else 0
    a_wins = a_val >= b_val
    a_color = COLORS["steel"] if a_wins else COLORS["text_dim"]
    b_color = COLORS["steel"] if not a_wins else COLORS["text_dim"]
    return f"""
    <div class="cmp">
      <div class="cmp-label">{label if label_is_html else _esc(label)}</div>
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
    """Converte **negrito** e `código` para HTML. Escapa <, >, & (segurança)
    mas NÃO apóstrofos/aspas — em conteúdo de texto são inofensivos e o
    html.escape padrão transformava-os em &#x27; à mostra."""
    text = html.escape(str(text if text is not None else ""), quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    return text


def _weight_badge(line: str) -> tuple[str, str]:
    """Deteta o selo de peso no início de uma linha e devolve (classe_css,
    texto). Auditoria P2: os pesos passam a BARRAS de intensidade (w-bar-*),
    não bolas coloridas — para o vermelho/verde terem um só significado no
    relatório (a conclusão/divergência). Aqui é só intensidade, cor neutra."""
    stripped = line.lstrip()
    if stripped.startswith("🔴"):
        return "w-bar-3", stripped[1:].strip()  # forte
    if stripped.startswith("🟡"):
        return "w-bar-2", stripped[1:].strip()  # moderado
    if stripped.startswith("⚪"):
        return "w-bar-1", stripped[1:].strip()  # fraco
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
            # Legenda dos selos, logo a seguir ao cabeçalho das discrepâncias
            if "Discrep" in title or "mercados a observar" in title:
                out.append(
                    '<div class="selos-legenda">'
                    '<span><b class="w-bar w-bar-3"></b> forte (amostra grande + divergência clara)</span>'
                    '<span><b class="w-bar w-bar-2"></b> moderado</span>'
                    '<span><b class="w-bar w-bar-1"></b> fraco / contextual</span>'
                    '<div class="selos-nota">Pontos de observação para leitura ao vivo — não são recomendações de aposta.</div>'
                    '</div>'
                )
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


def _fmt_pct(v, of=1.0):
    """Formata um valor como percentagem. of=1.0 se já é fração (0.68→68%),
    of=100 se já é percentagem inteira (68→68%)."""
    if v is None:
        return None
    try:
        return f"{float(v) * (100 if of == 1.0 else 1):.0f}%"
    except (ValueError, TypeError):
        return None


def _data_card(title, rows):
    """Monta um cartão de secção de dados. rows = lista de strings (linhas em
    HTML já escapadas). Devolve '' se não houver linhas."""
    rows = [r for r in rows if r]
    if not rows:
        return ""
    inner = "".join(f'<div class="d-row">{r}</div>' for r in rows)
    return f'<div class="d-card"><div class="d-title">{_esc(title)}</div>{inner}</div>'


def _data_card_avb(title, a_name, b_name, rows):
    """Cartão A-vs-B (sugestão Hugo): os nomes aparecem UMA vez no topo, em
    colunas, e cada linha mostra só [rótulo | valor_a | valor_b] — sem repetir
    os nomes. rows = lista de tuplos (rotulo, valor_a, valor_b) já em texto.
    Devolve '' se não houver linhas."""
    rows = [r for r in rows if r]
    if not rows:
        return ""
    header = (f'<div class="avb-head"><span class="avb-lbl"></span>'
              f'<span class="avb-a">{_esc(a_name)}</span>'
              f'<span class="avb-b">{_esc(b_name)}</span></div>')
    body = ""
    for rotulo, va, vb in rows:
        body += (f'<div class="avb-row"><span class="avb-lbl">{_esc(rotulo)}</span>'
                 f'<span class="avb-a">{_esc(va)}</span>'
                 f'<span class="avb-b">{_esc(vb)}</span></div>')
    return f'<div class="d-card"><div class="d-title">{_esc(title)}</div>{header}{body}</div>'


def _build_data_sections(payload: dict) -> str:
    """
    MEDIDA 6: monta as secções de DADOS factuais diretamente do payload, em
    Python. Usa as chaves REAIS das funções compute_* do fetch_data:
      - h2h: {"overall": {"a_wins","b_wins","total_matches"}, "on_surface": {...}}
      - recent_form/current_season: {"wins","losses","matches"}
      - surface_stats: {"wins","losses","matches","surface"}  (piso do jogo)
      - fatigue_signal: {"days_since_last_match", "fatigue_data_maybe_stale"}
      - injury_signal: {"recent_retirements": [...]}
      - ranking: {"rank","points","as_of"}   (NÃO um número)
    Cada secção só aparece se tiver dados. Devolve HTML.
    """
    a = _esc(payload.get("player_a", "A"))
    b = _esc(payload.get("player_b", "B"))
    cards = []

    def _rank_num(r):
        """ranking vem como {"rank": N, ...} ou às vezes None/int."""
        if isinstance(r, dict):
            return r.get("rank")
        return r

    # H2H
    h2h = payload.get("h2h") or {}
    if isinstance(h2h, dict) and h2h:
        rows = []
        ov = h2h.get("overall")
        if ov and isinstance(ov, dict) and ov.get("total_matches"):
            rows.append(f"<b>Geral:</b> {a} {ov.get('a_wins',0)}–{ov.get('b_wins',0)} {b}")
        surf = h2h.get("on_surface")
        if surf and isinstance(surf, dict) and surf.get("total_matches"):
            rows.append(f"<b>Neste piso:</b> {a} {surf.get('a_wins',0)}–{surf.get('b_wins',0)} {b}")
        if not rows:
            rows.append("Sem confrontos diretos registados.")
        cards.append(_data_card("Confronto direto (H2H)", rows))

    # Forma recente + época atual
    fa, fb = payload.get("recent_form_a") or {}, payload.get("recent_form_b") or {}
    sa, sb = payload.get("current_season_a") or {}, payload.get("current_season_b") or {}
    rows = []
    if fa.get("matches") and fb.get("matches"):
        rows.append(f"<b>Últimos jogos:</b> {a} {fa['wins']}-{fa['losses']} · {b} {fb['wins']}-{fb['losses']}")
    if sa.get("matches") and sb.get("matches"):
        pa = _fmt_pct(sa['wins']/sa['matches'])
        pb = _fmt_pct(sb['wins']/sb['matches'])
        rows.append(f"<b>Época atual:</b> {a} {sa['wins']}-{sa['losses']} ({pa}) · {b} {sb['wins']}-{sb['losses']} ({pb})")
    if rows:
        cards.append(_data_card("Forma recente e época atual", rows))

    # Ranking (extrair o número de dentro do dict)
    ra, rb = _rank_num(payload.get("ranking_a")), _rank_num(payload.get("ranking_b"))
    if ra or rb:
        rows = [f"<b>Ranking oficial:</b> {a} #{ra if ra else '?'} · {b} #{rb if rb else '?'}"]
        cards.append(_data_card("Ranking", rows))

    # Piso: preferir o dado RICO (by_surface do perf-breakdown, carreira
    # completa e com indoor/outdoor separado); fallback para surface_stats
    # do histórico. Mapeia o piso do jogo para a chave certa.
    surface_name = payload.get("surface", "")
    surf_lower = surface_name.lower()
    # determinar a chave de by_surface para o piso do jogo
    if "clay" in surf_lower:
        skey = "clay"
    elif "grass" in surf_lower:
        skey = "grass"
    elif "carpet" in surf_lower:
        skey = "carpet"
    elif "indoor" in surf_lower and "hard" in surf_lower:
        skey = "hard_indoor"
    elif "hard" in surf_lower:
        skey = "hard"
    else:
        skey = None

    bsa = (payload.get("rich_stats_a") or {}).get("by_surface") or {}
    bsb = (payload.get("rich_stats_b") or {}).get("by_surface") or {}
    ca = bsa.get(skey) if skey else None
    cb = bsb.get(skey) if skey else None

    if ca and cb and ca.get("matches") and cb.get("matches"):
        # dado rico (carreira completa)
        rows = [f"<b>Neste piso ({_esc(surface_name)}):</b> "
                f"{a} {ca['win_pct']}% ({ca['matches']} jogos) · "
                f"{b} {cb['win_pct']}% ({cb['matches']} jogos)"]
        cards.append(_data_card("Desempenho por piso (carreira)", rows))
    else:
        # fallback: surface_stats do histórico
        supa = payload.get("surface_stats_a") or {}
        supb = payload.get("surface_stats_b") or {}
        if supa.get("matches") and supb.get("matches"):
            pa = _fmt_pct(supa['wins']/supa['matches'])
            pb = _fmt_pct(supb['wins']/supb['matches'])
            rows = [f"<b>Neste piso ({_esc(surface_name)}):</b> {a} {pa} ({supa['matches']} jogos) · {b} {pb} ({supb['matches']} jogos)"]
            cards.append(_data_card("Desempenho por piso", rows))

    # Desempenho por NÍVEL DE TORNEIO — mostra o registo no nível deste jogo
    # (ex: num Masters, mostra o registo em Masters de cada um). Sinal útil:
    # há jogadores que rendem mais em torneios pequenos que nos grandes.
    tier = (payload.get("tier") or "").lower()
    if "grand slam" in tier or "grandslam" in tier:
        lkey, lnome = "grand_slam", "Grand Slams"
    elif "1000" in tier or "masters" in tier:
        lkey, lnome = "masters", "Masters 1000"
    elif "250" in tier or "500" in tier or "atp" in tier or "wta" in tier:
        lkey, lnome = "main_tour", "ATP/WTA Tour (250/500)"
    else:
        lkey, lnome = None, None

    if lkey:
        bla = (payload.get("rich_stats_a") or {}).get("by_level") or {}
        blb = (payload.get("rich_stats_b") or {}).get("by_level") or {}
        la, lb = bla.get(lkey), blb.get(lkey)
        if la and lb and la.get("matches") and lb.get("matches"):
            rows = [f"<b>Neste nível ({_esc(lnome)}):</b> "
                    f"{a} {la['win_pct']}% ({la['matches']} jogos) · "
                    f"{b} {lb['win_pct']}% ({lb['matches']} jogos)"]
            cards.append(_data_card("Desempenho por nível de torneio (carreira)", rows))

    # Fadiga
    fga, fgb = payload.get("fatigue_signal_a") or {}, payload.get("fatigue_signal_b") or {}
    rows = []
    for nome, fg in ((a, fga), (b, fgb)):
        if isinstance(fg, dict) and fg.get("days_since_last_match") is not None:
            parts = [f"{fg['days_since_last_match']} dias desde o último jogo"]
            # se veio da fonte fiável (API), mostrar a carga real do torneio
            if fg.get("fatigue_source") == "api_recent":
                if fg.get("matches_this_tournament"):
                    parts.append(f"{fg['matches_this_tournament']} jogo(s) neste torneio")
                if fg.get("matches_last_7d") is not None:
                    extra = f"{fg['matches_last_7d']} nos últimos 7 dias"
                    if fg.get("sets_last_7d"):
                        extra += f" ({fg['sets_last_7d']} sets)"
                    parts.append(extra)
            elif fg.get("fatigue_data_maybe_stale"):
                parts[0] += " (dado pode estar desatualizado)"
            rows.append(f"<b>{nome}:</b> " + "; ".join(parts))
    if rows:
        cards.append(_data_card("Fadiga / descanso", rows))

    # Desistências recentes
    ija, ijb = payload.get("injury_signal_a") or {}, payload.get("injury_signal_b") or {}
    rows = []
    for nome, ij in ((a, ija), (b, ijb)):
        if isinstance(ij, dict):
            rets = ij.get("recent_retirements")
            if rets:
                rows.append(f"<b>{nome}:</b> {len(rets)} desistência(s) recente(s) registada(s)")
            else:
                rows.append(f"<b>{nome}:</b> sem desistências recentes registadas")
    if rows:
        cards.append(_data_card("Desistências recentes", rows))

    # Meteorologia (só se ao ar livre e com dados)
    w = payload.get("weather")
    if w and isinstance(w, dict):
        parts = []
        if w.get("temp_max_c") is not None:
            parts.append(f"máx {w['temp_max_c']}°C")
        if w.get("wind_kmh") is not None:
            parts.append(f"vento {w['wind_kmh']} km/h")
        if w.get("precipitation_mm") is not None:
            parts.append(f"precipitação {w['precipitation_mm']} mm")
        if parts:
            cards.append(_data_card("Meteorologia (ao ar livre)", ["; ".join(parts)]))

    # Cenários de jogo (dados ricos: 1º set, set decisivo, tiebreaks) — A vs B
    sca = (payload.get("rich_stats_a") or {}).get("scenarios") or {}
    scb = (payload.get("rich_stats_b") or {}).get("scenarios") or {}
    if sca and scb:
        rows = []
        def _scen_row(label, key, count_key=None):
            va, vb = sca.get(key), scb.get(key)
            if va is None or vb is None:
                return None
            extra = ""
            if count_key and sca.get(count_key) and scb.get(count_key):
                extra = f" ({sca[count_key]}/{scb[count_key]})"
            return (f"{label}{extra}", f"{va}%", f"{vb}%")
        rows.append(_scen_row("Ganha 1º set → vence", "first_set_win_then_win_pct", "first_set_win_count"))
        rows.append(_scen_row("Perde 1º set → vence", "first_set_lose_then_win_pct", "first_set_lose_count"))
        rows.append(_scen_row("Set decisivo", "deciding_set_win_pct", "deciding_set_count"))
        rows.append(_scen_row("Tie-breaks", "tiebreak_win_pct", "tiebreak_count"))
        cards.append(_data_card_avb("Cenários de jogo (carreira)", a, b, rows))

    # Estilo de jogo (aces, erros, winners, rede, duração) — A vs B
    sta = (payload.get("rich_stats_a") or {}).get("style") or {}
    stb = (payload.get("rich_stats_b") or {}).get("style") or {}
    if sta and stb:
        rows = []
        if sta.get("net_success_pct") is not None and stb.get("net_success_pct") is not None:
            rows.append(f"<b>Sucesso na rede:</b> {a} {sta['net_success_pct']}% · {b} {stb['net_success_pct']}%")
        if sta.get("avg_time") and stb.get("avg_time"):
            rows.append(f"<b>Duração média:</b> {a} {_esc(str(sta['avg_time']))} · {b} {_esc(str(stb['avg_time']))}")
        # winners vs erros: rácio de agressividade (bruto de carreira)
        if sta.get("winners") and sta.get("unforced_errors") and stb.get("winners") and stb.get("unforced_errors"):
            ra_ = round(sta["winners"]/sta["unforced_errors"], 2)
            rb_ = round(stb["winners"]/stb["unforced_errors"], 2)
            rows.append(f"<b>Rácio winners/erros:</b> {a} {ra_} · {b} {rb_}")
        cards.append(_data_card("Estilo de jogo (carreira)", rows))

    # Domínio vs adversários (own vs opp) — quem "manda" no confronto-tipo
    doma = (payload.get("rich_stats_a") or {}).get("domination") or {}
    domb = (payload.get("rich_stats_b") or {}).get("domination") or {}
    if doma or domb:
        rows = []
        def _dom_line(nome, dom):
            if not dom:
                return None
            bits = []
            if dom.get("own_first_serve_won_pct") is not None and dom.get("opp_first_serve_won_pct") is not None:
                bits.append(f"1º serviço ganho {dom['own_first_serve_won_pct']}% vs adversários {dom['opp_first_serve_won_pct']}%")
            if dom.get("own_winners") is not None and dom.get("opp_winners") is not None:
                bits.append(f"winners {dom['own_winners']} vs {dom['opp_winners']}")
            if dom.get("own_unforced_errors") is not None and dom.get("opp_unforced_errors") is not None:
                bits.append(f"erros {dom['own_unforced_errors']} vs {dom['opp_unforced_errors']}")
            return f"<b>{nome}:</b> " + "; ".join(bits) if bits else None
        r1 = _dom_line(a, doma)
        r2 = _dom_line(b, domb)
        if r1: rows.append(r1)
        if r2: rows.append(r2)
        if rows:
            cards.append(_data_card("Domínio vs adversários (carreira)", rows))

    # (Secção "Mercado (odds)" removida — as odds já aparecem no cabeçalho,
    # com a probabilidade sem margem; repeti-las aqui era redundante.)

    cards = [c for c in cards if c]
    if not cards:
        return ""
    return f'<section class="data-sections">{"".join(cards)}</section>'


def _build_charts(payload: dict) -> str:
    """Constrói os gráficos SVG a partir dos dados do payload, quando
    disponíveis. Escolhe barras (comparação A-vs-B) ou medidores conforme
    a estatística. Devolve HTML (pode ser vazio se não houver dados)."""
    a = _esc(payload.get("player_a", "A"))
    b = _esc(payload.get("player_b", "B"))
    charts: list[str] = []

    # Serviço (e resposta, se disponível via rich_stats) — barras de confronto
    sa = payload.get("serve_return_stats_a") or {}
    sb = payload.get("serve_return_stats_b") or {}
    if sa and sb:
        rows = []
        pairs = [
            ("1º serviço ganho", "avg_first_serve_won_pct"),
            ("Break points salvos", "avg_break_points_saved_pct"),
            ("Aces", "avg_ace_pct"),
        ]
        def _pct_escala(v):
            # A RapidAPI dá já em % (ex: 66); o Sackmann dava em fração (0.66).
            # Deteta a escala: se <= 1.5 é fração -> ×100; senão já é %.
            if v is None:
                return None
            return round(v * 100, 1) if v <= 1.5 else round(v, 1)
        for label, key in pairs:
            if sa.get(key) is not None and sb.get(key) is not None:
                rows.append(_bar_comparison(label, a, _pct_escala(sa[key]), b, _pct_escala(sb[key])))

        # Resposta (Onda 2): vem em percentagem inteira já (ex: 41), não fração
        resp_a = (payload.get("rich_stats_a") or {}).get("response_stats") or {}
        resp_b = (payload.get("rich_stats_b") or {}).get("response_stats") or {}
        has_response = False
        resp_pairs = [
            ("Pontos de resposta ganhos", "return_pts_won_pct"),
            ("Break points convertidos", "break_points_converted_pct"),
        ]
        for label, key in resp_pairs:
            if resp_a.get(key) is not None and resp_b.get(key) is not None:
                rows.append(_bar_comparison(label, a, round(float(resp_a[key]), 1), b, round(float(resp_b[key]), 1)))
                has_response = True

        if rows:
            titulo = "Serviço / Resposta" if has_response else "Serviço"
            charts.append(f'<div class="chart-block"><div class="chart-title">{titulo}</div>{"".join(rows)}</div>')

    # Forma recente — medidores lado a lado
    fa = payload.get("recent_form_a") or {}
    fb = payload.get("recent_form_b") or {}
    if fa.get("matches") and fb.get("matches"):
        g1 = _gauge(f"{a} (forma)", 100*fa["wins"]/fa["matches"], fa["matches"])
        g2 = _gauge(f"{b} (forma)", 100*fb["wins"]/fb["matches"], fb["matches"])
        charts.append(f'<div class="chart-block"><div class="chart-title">Forma recente</div><div class="gauges">{g1}{g2}</div></div>')

    # Desempenho por nível de adversário (Onda 2, ponto 7) — barras de
    # confronto por patamar de ranking, quando ambos têm o dado.
    ra = (payload.get("rich_stats_a") or {}).get("vs_rank_level") or {}
    rb = (payload.get("rich_stats_b") or {}).get("vs_rank_level") or {}
    if ra and rb:
        level_labels = [("top10", "vs Top 10"), ("top50", "vs Top 50"), ("top100", "vs Top 100")]
        rows = []
        for key, label in level_labels:
            ca, cb = ra.get(key), rb.get(key)
            if ca and cb:
                # rótulo com destaque no nível, jogos discretos (sugestão Hugo)
                label_html = f'<b>{label}</b> <span class="lvl-games">({ca["matches"]}/{cb["matches"]} jogos)</span>'
                rows.append(_bar_comparison(
                    label_html,
                    a, ca["win_pct"], b, cb["win_pct"], label_is_html=True))
        if rows:
            charts.append(f'<div class="chart-block"><div class="chart-title">Desempenho</div>{"".join(rows)}</div>')

    if not charts:
        return ""
    return f'<section class="charts">{"".join(charts)}</section>'


# ===== MOTOR DE DIVERGÊNCIA PONDERADA V3 (Python puro, zero Claude) =====
# afinam-se com o backtest e os relatórios reais.
PESOS = {
    "h2h": 10,                 # ALTO — mais importante que o ranking
    "piso": 10,                # ALTO — performance na superfície
    "recuperacao_sets": 9,     # ALTO — recuperar 1 set abaixo / sets decisivos
    "matchup_maos": 8,         # ALTO — canhoto vs destro
    "forma_recente": 7,        # MÉDIO-ALTO — ritmo/confiança (inclui Challengers)
    "ranking": 5,              # MÉDIO — conta, mas dá falsos positivos
    "lesao": 5,                # MÉDIO — só ativa em regressos claros/longos
    "fadiga": 4,               # MÉDIO-BAIXO — sobe se último jogo foi longo
    "epoca_atual": 4,          # MÉDIO-BAIXO
    "servico": 4,              # MÉDIO-BAIXO
    "meteo": 1,                # BAIXO — raramente decisiva
}

# Escala de divergência (honesta — indicador de atenção, não vantagem garantida).
# Baseada na sugestão do ChatGPT, ajustada por nós. Em pontos percentuais
# da diferença entre a inclinação ponderada do modelo e o mercado.
def _classificar_divergencia(gap_pp):
    g = abs(gap_pp)
    if g < 5:
        return ("eficiente", "Mercado eficiente", 0)
    elif g < 12:
        return ("ligeira", "Divergência ligeira", 1)
    elif g < 20:
        return ("moderada", "Divergência moderada", 2)
    else:
        return ("forte", "Divergência forte", 3)


def _nome_fator(chave):
    return {
        "h2h": "confronto direto", "piso": "superfície",
        "recuperacao_sets": "resiliência em sets", "matchup_maos": "matchup de mão",
        "forma_recente": "forma recente", "ranking": "ranking",
        "lesao": "regresso após paragem", "fadiga": "fadiga",
        "epoca_atual": "época atual", "servico": "serviço", "meteo": "meteorologia",
    }.get(chave, chave)


def _calcular_divergencia(payload):
    """
    Núcleo do V3. Devolve:
    - inclinacao_modelo: % ponderada a favor de A (0-100)
    - prob_mercado: % do mercado a favor de A (sem margem)
    - gap_pp: diferença em pontos percentuais
    - classificacao: (chave, texto, nivel 0-3)
    - favorecido: quem o modelo favorece vs mercado (ou None)
    - fatores_chave: os fatores que MAIS pesaram na inclinação (para justificar)
    """
    a = payload.get("player_a", "A")
    b = payload.get("player_b", "B")
    feats = payload.get("features") or {}

    # --- 1. Recolher a "vantagem" de cada fator (quem lidera e força) ---
    # Para cada fator disponível: +peso se lidera A, -peso se lidera B,
    # escalado pela força relativa (diff) E pela CONFIANÇA DA AMOSTRA.
    contribuicoes = []  # (chave, sinal_para_A, peso_efetivo)

    def _conf_amostra(n_jogos, n_pleno=30):
        """Confiança da amostra (0.2 a 1.0). Auditoria P0 #3: um fator com
        poucos jogos (ex: 8 num piso) não deve entrar com peso quase total.
        Cresce com a amostra; satura em n_pleno jogos. Nunca zero (mínimo 0.2)
        para não anular fatores com amostra pequena mas legítima."""
        if not n_jogos or n_jogos <= 0:
            return 0.5  # amostra desconhecida -> confiança média (neutra)
        return max(0.2, min(n_jogos / n_pleno, 1.0))

    def _add(chave, lider, forca_rel=1.0, peso_override=None, conf_amostra=1.0):
        # peso efetivo = peso base × força da diferença × confiança da amostra
        base = peso_override if peso_override is not None else PESOS.get(chave, 0)
        peso = base * forca_rel * conf_amostra
        if lider == a:
            contribuicoes.append((chave, +1, peso))
        elif lider == b:
            contribuicoes.append((chave, -1, peso))

    # H2H — só conta com amostra mínima (1 jogo não é evidência fiável) e
    # com força proporcional ao domínio do confronto.
    h = feats.get("h2h")
    if isinstance(h, dict) and h.get("lider") not in (None, "igual"):
        _h_total = (h.get("a_wins", 0) + h.get("b_wins", 0)) or h.get("diff", 0)
        if _h_total >= 2:  # ignora H2H de 1 só jogo
            forca = min(_h_total / 4.0, 1.0)  # 4+ jogos = peso total
            _add("h2h", h["lider"], max(forca, 0.5))
    # Piso — com confiança de amostra (auditoria: 8 jogos não pesa como 300)
    ps = feats.get("piso")
    if isinstance(ps, dict) and ps.get("lider") not in (None, "igual"):
        forca = min((ps.get("diff") or 5) / 15.0, 1.0)
        # amostra: nº de jogos no piso (o menor dos dois jogadores, conservador)
        _n_piso = min(ps.get("amostra_a") or 0, ps.get("amostra_b") or 0) or ps.get("amostra") or 0
        _add("piso", ps["lider"], max(forca, 0.4), conf_amostra=_conf_amostra(_n_piso, 40))
    # Recuperação de sets (rich_stats scenarios)
    ra = (payload.get("rich_stats_a") or {}).get("scenarios") or {}
    rb = (payload.get("rich_stats_b") or {}).get("scenarios") or {}
    dec_a = ra.get("deciding_set_win_pct")
    dec_b = rb.get("deciding_set_win_pct")
    if dec_a is not None and dec_b is not None:
        lider = a if dec_a > dec_b else (b if dec_b > dec_a else "igual")
        if lider != "igual" and abs(dec_a - dec_b) >= 3:
            forca = min(abs(dec_a - dec_b) / 15.0, 1.0)
            _n_dec = min(ra.get("deciding_set_count") or 0, rb.get("deciding_set_count") or 0)
            _add("recuperacao_sets", lider, max(forca, 0.4), conf_amostra=_conf_amostra(_n_dec, 20))
    # Matchup de mão (handedness)
    hm = payload.get("handedness_matchup_a") or {}
    hmb = payload.get("handedness_matchup_b") or {}
    wa = hm.get("win_pct"); wb = hmb.get("win_pct")
    if wa is not None and wb is not None:
        lider = a if wa > wb else (b if wb > wa else "igual")
        if lider != "igual" and abs(wa - wb) >= 3:
            forca = min(abs(wa - wb) / 15.0, 1.0)
            _add("matchup_maos", lider, max(forca, 0.4))
    # Forma recente
    fr = feats.get("forma_recente")
    if isinstance(fr, dict) and fr.get("lider") not in (None, "igual"):
        forca = min((fr.get("diff") or 10) / 25.0, 1.0)
        _add("forma_recente", fr["lider"], max(forca, 0.4))
    # Ranking — só conta se a diferença for RELEVANTE (não #70 vs #72). A força
    # cresce com o fosso: <5 lugares ~ irrelevante; 50+ ~ peso total.
    rk = feats.get("ranking")
    if isinstance(rk, dict) and rk.get("lider") not in (None, "igual"):
        _rk_diff = rk.get("diff", 0)
        if _rk_diff >= 5:  # ignora rankings quase iguais
            forca = min(_rk_diff / 50.0, 1.0)
            _add("ranking", rk["lider"], max(forca, 0.3))
    # Época atual
    ea = feats.get("epoca_atual")
    if isinstance(ea, dict) and ea.get("lider") not in (None, "igual"):
        _add("epoca_atual", ea["lider"])
    # Serviço
    sv = feats.get("servico")
    if isinstance(sv, dict) and sv.get("lider") not in (None, "igual"):
        _add("servico", sv["lider"])
    # Fadiga (sobe se último jogo foi longo)
    fa = payload.get("fatigue_signal_a") or {}
    fb = payload.get("fatigue_signal_b") or {}
    # AUDITORIA P1: a fadiga só entra no motor se a fonte for 'api_recent'
    # (jogos reais recentes). Dados históricos de fadiga podem estar
    # desatualizados — o próprio prompt do Claude já os ignora, e o motor
    # também deve. Se qualquer dos jogadores tiver fadiga só histórica, não
    # damos peso quantitativo a este fator.
    _fadiga_fiavel = (fa.get("fatigue_source") == "api_recent"
                      and fb.get("fatigue_source") == "api_recent")
    if _fadiga_fiavel:
        def _jogo_longo(f):
            return (f.get("last_match_sets") or 0) >= 3 or (f.get("sets_last_7d") or 0) >= 8
        peso_fadiga = PESOS["fadiga"]
        if _jogo_longo(fa) or _jogo_longo(fb):
            peso_fadiga = 7  # sobe quando há jogo longo
        ja = fa.get("matches_last_7d"); jb = fb.get("matches_last_7d")
        if ja is not None and jb is not None and ja != jb:
            lider = a if ja < jb else b
            _add("fadiga", lider, peso_override=peso_fadiga)
    # Lesão (só ativa em regresso claro/longo)
    la = payload.get("layoff_return_stats_a") or {}
    lb = payload.get("layoff_return_stats_b") or {}
    def _regresso_claro(l):
        return (l.get("days_out") or 0) >= 60  # 2+ meses parado
    # quem regressa de lesão longa fica em desvantagem
    if _regresso_claro(la) and not _regresso_claro(lb):
        _add("lesao", b)  # B beneficia (A está a regressar)
    elif _regresso_claro(lb) and not _regresso_claro(la):
        _add("lesao", a)
    # Meteorologia (peso mínimo — só entra como desempate simbólico, quase nulo)
    # (não implementado como vantagem direcional; fica como contexto)

    # --- 1.5. CAP POR FAMÍLIA (auditoria P1 — evitar double counting) ---
    # ranking+época+serviço+forma medem em parte a mesma coisa ("qualidade
    # geral"). Somá-los como independentes conta a mesma variável várias vezes.
    # Agrupamos em famílias e limitamos a contribuição de cada família a um
    # teto, para que medir a qualidade de 4 formas não a inflacione 4x.
    FAMILIAS = {
        "forca_base": {"ranking", "epoca_atual", "servico", "forma_recente"},
        "matchup": {"piso", "matchup_maos", "h2h"},
        "resiliencia": {"recuperacao_sets"},
        "contexto": {"fadiga", "lesao", "meteo"},
    }
    # teto de peso efetivo por família (a família "força base", muito
    # correlacionada, é a mais limitada; matchup/resiliência são sinais mais
    # distintos e específicos do confronto, logo teto mais alto).
    CAP_FAMILIA = {"forca_base": 12, "matchup": 20, "resiliencia": 9, "contexto": 6}

    def _familia(chave):
        for fam, membros in FAMILIAS.items():
            if chave in membros:
                return fam
        return "contexto"

    # agrupar contribuições por família (mantendo o sinal), aplicar cap
    _por_familia = {}
    for chave, sinal, peso in contribuicoes:
        fam = _familia(chave)
        _por_familia.setdefault(fam, []).append((chave, sinal, peso))
    contribuicoes_capadas = []
    for fam, items in _por_familia.items():
        soma_peso = sum(abs(p) for _, _, p in items)
        cap = CAP_FAMILIA.get(fam, 10)
        if soma_peso > cap and soma_peso > 0:
            # reduzir proporcionalmente todos os fatores da família
            escala = cap / soma_peso
            items = [(c, s, p * escala) for c, s, p in items]
        contribuicoes_capadas.extend(items)
    contribuicoes = contribuicoes_capadas

    # --- 2. Calcular inclinação ponderada do modelo (índice a favor de A) ---
    peso_total = sum(abs(p) for _, _, p in contribuicoes)
    if peso_total == 0:
        return None  # sem dados suficientes
    soma_a = sum(sinal * p for _, sinal, p in contribuicoes if sinal > 0)
    soma_b = sum(-sinal * p for _, sinal, p in contribuicoes if sinal < 0)
    bruto_a = soma_a / peso_total  # 0-1 (quota de A no peso total dos sinais)

    # ÍNDICE DE EVIDÊNCIA (0-100) — NÃO é uma probabilidade de vitória. É a
    # quota do peso dos sinais que aponta para A. Apresenta-se como "índice de
    # evidência: X/100 a favor de A", nunca como "X% de hipóteses". Resolve o
    # problema metodológico (auditoria P0 #1): antes fingíamos uma probabilidade
    # (50 + (bruto-0.5)*70) e comparávamos com o mercado em pontos percentuais,
    # o que é falsa precisão — um score de peso não é uma probabilidade.
    indice_evidencia_a = round(100 * bruto_a)  # 0-100, honesto (só o índice)

    # --- 3. Direção do mercado (sem inventar probabilidade do modelo) ---
    odds = payload.get("market_odds_decimal") or {}
    oa = ob = None
    for k, v in odds.items():
        if not isinstance(v, (int, float)) or v <= 1:
            continue
        if k == "player_a" or (a and a.split()[-1].lower() in k.lower()):
            oa = v
        elif k == "player_b" or (b and b.split()[-1].lower() in k.lower()):
            ob = v
    if oa is None or ob is None:
        vals = [v for v in odds.values() if isinstance(v, (int, float)) and v > 1]
        if len(vals) == 2:
            oa, ob = vals
    prob_mercado_a = None
    if oa and ob:
        prob_mercado_a = round(100 * (1/oa) / ((1/oa) + (1/ob)))

    if prob_mercado_a is None:
        return None

    # --- 4. Comparação: DIREÇÃO + MAGNITUDE (Caso C) ---
    # Dois tipos de situação interessante:
    #  (1) DIREÇÃO: mercado num jogador, índice no outro -> "contra o mercado".
    #  (2) CONVICÇÃO: ambos no mesmo jogador, mas o índice bem mais forte que o
    #      mercado -> "favorito subvalorizado", os dados suportam-no mais que a
    #      odd. É valor do lado do favorito (o que o utilizador quer apanhar).
    # NÃO fingimos que o índice é probabilidade: a magnitude mede o
    # "desalinhamento de convicção", não "o mercado está errado em X%".
    mercado_favorece = a if prob_mercado_a >= 50 else b
    indice_favorece = a if indice_evidencia_a >= 50 else b
    forca_indice = abs(indice_evidencia_a - 50)      # 0-50
    forca_mercado = abs(prob_mercado_a - 50)          # 0-50
    # desalinhamento de magnitude (mesmo apontando ao mesmo lado)
    desalinhamento = abs(indice_evidencia_a - prob_mercado_a)  # 0-100
    tipo = "eficiente"
    if indice_favorece != mercado_favorece:
        # (1) direção oposta -> divergência clássica
        tipo = "direcao"
        conviccao = forca_indice + forca_mercado
        if conviccao < 15:
            nivel = 1
        elif conviccao < 30:
            nivel = 2
        else:
            nivel = 3
    elif desalinhamento >= 12:
        # (2) mesmo lado, mas índice bem mais forte -> convicção reforçada
        # (favorito que os dados suportam mais do que a odd reflete). Tratamento
        # SIMÉTRICO com a divergência de direção (auditoria ponto 9): sem
        # limiar de odd — mostra a todos os favoritos subvalorizados e o
        # utilizador decide o que fazer (Moneyline, handicap, etc.).
        tipo = "conviccao"
        if desalinhamento < 18:
            nivel = 1
        elif desalinhamento < 28:
            nivel = 2
        else:
            nivel = 3
    else:
        # concordam em direção e magnitude -> mercado eficiente
        nivel = 0

    # SALVAGUARDA DE CONFIANÇA (contra falsos positivos): a divergência só pode
    # ser "forte"/"moderada" se houver massa de evidência e fatores suficientes.
    massa_evidencia = peso_total
    n_fatores = len([c for c in contribuicoes if abs(c[2]) > 0])
    if massa_evidencia < 8 or n_fatores < 2:
        nivel = min(nivel, 1)
    elif massa_evidencia < 18 or n_fatores < 3:
        nivel = min(nivel, 2)
    # texto conforme o TIPO (direção vs convicção) e o nível
    if tipo == "conviccao":
        _mapa = {0: ("eficiente", "Mercado eficiente"),
                 1: ("ligeira", "Convicção ligeira"),
                 2: ("moderada", "Convicção reforçada"),
                 3: ("forte", "Convicção forte")}
    else:
        _mapa = {0: ("eficiente", "Mercado eficiente"),
                 1: ("ligeira", "Divergência ligeira"),
                 2: ("moderada", "Divergência moderada"),
                 3: ("forte", "Divergência forte")}
    chave, texto = _mapa[nivel]

    favorecido = indice_favorece if nivel >= 1 else None

    # --- 5. Fatores-chave (os que mais pesaram, para justificar) ---
    contribuicoes.sort(key=lambda x: abs(x[2]), reverse=True)
    fatores_chave = []
    for chave_f, sinal, peso in contribuicoes[:3]:
        if peso <= 0:
            continue
        quem = a if sinal > 0 else b
        fatores_chave.append((_nome_fator(chave_f), quem))

    return {
        # ÍNDICE DE EVIDÊNCIA (não probabilidade) — 0-100 a favor de cada um
        "indice_evidencia_a": indice_evidencia_a,
        "indice_evidencia_b": 100 - indice_evidencia_a,
        # direção do mercado (só para comparação direcional)
        "prob_mercado_a": prob_mercado_a,
        "prob_mercado_b": 100 - prob_mercado_a,
        "mercado_favorece": mercado_favorece,
        "indice_favorece": indice_favorece,
        # compatibilidade retro: alguns sítios ainda leem estas chaves
        "inclinacao_modelo_a": indice_evidencia_a,
        "inclinacao_modelo_b": 100 - indice_evidencia_a,
        "classificacao": {"chave": chave, "texto": texto, "nivel": nivel},
        "tipo": tipo,  # "direcao" | "conviccao" | "eficiente"
        "favorecido": favorecido,
        "fatores_chave": fatores_chave,
        "player_a": a, "player_b": b,
    }




def _compute_model_vs_market(payload):
    """Model vs Market V3 (Python): usa o motor de divergência PONDERADA.
    Se o main já calculou e pôs em payload["divergencia"], usa esse valor
    (fonte única partilhada). Senão, calcula aqui (retrocompatível — nunca
    quebra, mesmo que só este ficheiro seja atualizado)."""
    r = payload.get("divergencia") or _calcular_divergencia(payload)
    if not r:
        return {"market": None, "model": None, "divergencia": None}
    market = {"a": r["prob_mercado_a"], "b": r["prob_mercado_b"]}
    # "model" agora é o ÍNDICE DE EVIDÊNCIA (0-100), não uma probabilidade
    model = {"a": r["indice_evidencia_a"], "b": r["indice_evidencia_b"]}
    divergencia = None
    if r["classificacao"]["nivel"] >= 1 and r["favorecido"]:
        divergencia = {"favorecido": r["favorecido"]}
    return {
        "market": market, "model": model, "divergencia": divergencia,
        "classificacao": r["classificacao"], "fatores_chave": r["fatores_chave"],
        "indice_evidencia": {"a": r["indice_evidencia_a"], "b": r["indice_evidencia_b"]},
        "favorecido": r["favorecido"],
        "mercado_favorece": r.get("mercado_favorece"),
        "indice_favorece": r.get("indice_favorece"),
    }


def _compute_market_overview(payload, mvm):
    """Market Overview (Python): interesse de cada mercado padrão. Usa o ÍNDICE
    DE EVIDÊNCIA direcional (não pseudo-probabilidade nem p.p.). Interesse 0-3."""
    f = payload.get("features") or {}
    a = payload.get("player_a", "A"); b = payload.get("player_b", "B")
    market = mvm.get("market"); model = mvm.get("model"); div = mvm.get("divergencia")
    idx = mvm.get("indice_evidencia") or {}
    fav = None
    if market:
        fav = a if market["a"] >= market["b"] else b
    linhas = []
    # Moneyline Favorito — leitura direcional (sem inventar p.p.)
    i, t = 1, "Mercado alinhado com os indicadores"
    if div and fav and div["favorecido"] == fav:
        idx_fav = idx.get("a") if fav == a else idx.get("b")
        i, t = 3, f"Favorito também suportado pelos indicadores (índice {idx_fav}/100)"
    elif div and fav and div["favorecido"] != fav:
        i, t = 0, "Indicadores não confirmam o favorito do mercado"
    linhas.append(("Moneyline Favorito", i, t))
    # Moneyline Underdog
    und = b if fav == a else a
    i, t = 0, "Sem valor: indicadores concordam com o mercado"
    if div and div["favorecido"] == und:
        idx_und = idx.get("a") if und == a else idx.get("b")
        i, t = 3, f"Underdog favorecido pelos indicadores (índice {idx_und}/100)"
    linhas.append(("Moneyline Underdog", i, t))
    # Total Games — quantificado pela margem do mercado
    i, t = 1, "Sem sinal de equilíbrio"
    if market:
        margem = abs(market["a"] - market["b"])
        if margem <= 12:
            i, t = 3, f"Jogo renhido (mercado {market['a']}/{market['b']}) — over/under a acompanhar"
        elif margem <= 24:
            i, t = 2, f"Algum equilíbrio (margem {margem} p.p.) — acompanhar linhas"
    linhas.append(("Total Games", i, t))
    # Handicap Games
    i, t = 1, "Favoritismo claro — handicap pouco interessante"
    if market:
        margem = abs(market["a"] - market["b"])
        if margem < 15:
            i, t = 2, f"Jogo equilibrado (margem {margem} p.p.) — handicap curto"
        elif margem <= 40:
            i, t = 2, f"Handicap médio a acompanhar (margem {margem} p.p.)"
    linhas.append(("Handicap Games", i, t))
    # Tie-break — quantificado pela diferença de serviço
    i, t = 1, "Sem indicação clara"
    sv = f.get("servico")
    if isinstance(sv, dict):
        sd = sv.get("diff", 99)
        if sd < 3:
            i, t = 2, f"Serviços equilibrados (dif. {sd} p.p.) — tiebreaks prováveis"
    linhas.append(("Tie-break", i, t))
    return linhas


def _render_interesse_dots(nivel):
    """Bolinhas de interesse: 3 pontos, preenchidos conforme o nível (0-3).
    Cor: verde para 2-3, âmbar para 1, vermelho para 0 (sem edge)."""
    if nivel == 0:
        cor = "dot-red"
        cheios = 1  # 1 ponto vermelho
    elif nivel == 1:
        cor = "dot-amber"
        cheios = 1
    else:
        cor = "dot-green"
        cheios = nivel
    dots = ""
    for k in range(3):
        if k < cheios:
            dots += f'<span class="mo-dot {cor}"></span>'
        else:
            dots += '<span class="mo-dot dot-empty"></span>'
    return dots


# Alias público para o main.py calcular a divergência uma vez e partilhar
# via payload["divergencia"] com o analyze (Claude) e este report_html.
def calcular_divergencia_publico(payload):
    """Ponto de entrada público do motor de divergência (usado pelo main)."""
    return _calcular_divergencia(payload)


def _build_top_verdict(result: dict) -> str:
    """Veredicto no TOPO (logo após o cabeçalho) — é o que capta a atenção."""
    verdict = result.get("verdict")
    if not verdict:
        return ""
    flag = result.get("flag", "")
    return (f'<div class="verdict-box top"><div class="verdict-label">✅ Veredicto</div>'
            f'<div class="verdict-text">{_markdown_inline(verdict)}</div></div>')


def _compute_fatores_decisivos(payload):
    """Fatores-chave: 1 ideia curta por bullet, das features. Prioriza os
    fatores de PESO ALTO (H2H, piso, sets decisivos) definidos pelo utilizador."""
    f = payload.get("features") or {}
    a = payload.get("player_a", "A"); b = payload.get("player_b", "B")
    bullets = []
    # H2H (peso alto) — se houver amostra
    h = f.get("h2h")
    if isinstance(h, dict) and h.get("lider") not in (None, "igual"):
        tot = (h.get("a_wins", 0) + h.get("b_wins", 0))
        if tot >= 2:
            bullets.append(f"Confronto direto favorece {h['lider']}.")
    # Piso (peso alto)
    ps = f.get("piso")
    if isinstance(ps, dict):
        if ps.get("lider") in (None, "igual") or ps.get("diff", 0) < 5:
            bullets.append("Superfície sem vantagem relevante.")
        else:
            bullets.append(f"Superfície favorece {ps['lider']}.")
    # Sets decisivos (peso alto) — dos rich_stats
    ra = (payload.get("rich_stats_a") or {}).get("scenarios") or {}
    rb = (payload.get("rich_stats_b") or {}).get("scenarios") or {}
    da, db = ra.get("deciding_set_win_pct"), rb.get("deciding_set_win_pct")
    if da is not None and db is not None and abs(da - db) >= 5:
        quem = a if da > db else b
        bullets.append(f"Mais forte em sets decisivos: {quem}.")
    # Ranking (peso médio) — só se relevante
    rk = f.get("ranking")
    if isinstance(rk, dict) and rk.get("lider") not in (None, "igual"):
        diff = rk.get("diff", 0)
        if diff >= 5:
            intensidade = "clara" if diff >= 20 else ("moderada" if diff >= 8 else "ligeira")
            bullets.append(f"Ranking favorece {rk['lider']} ({intensidade}).")
    # Forma recente (peso médio-alto)
    fr = f.get("forma_recente")
    if isinstance(fr, dict):
        if fr.get("lider") in (None, "igual") or fr.get("diff", 0) < 10:
            bullets.append("Forma recente semelhante.")
        else:
            bullets.append(f"Forma recente favorece {fr['lider']}.")
    # Serviço (peso médio-baixo)
    sv = f.get("servico")
    if isinstance(sv, dict) and len(bullets) < 5:
        if sv.get("lider") in (None, "igual") or sv.get("diff", 0) < 3:
            bullets.append("Serviço equilibrado.")
        else:
            bullets.append(f"Serviço favorece {sv['lider']}.")
    return bullets[:5]


def _compute_pontos_atencao(payload):
    """Alertas/limitações factuais (sem H2H, amostra reduzida, sem fadiga)."""
    pts = []
    f = payload.get("features") or {}
    h2h = (payload.get("h2h") or {}).get("overall") or {}
    if not h2h.get("total_matches"):
        pts.append("Sem confronto direto (H2H) entre os jogadores.")
    elif h2h.get("total_matches", 0) < 3:
        pts.append(f"H2H com amostra reduzida ({h2h['total_matches']} jogo(s)).")
    piso = f.get("piso")
    if isinstance(piso, dict):
        amostra = min(piso.get("amostra_a") or 999, piso.get("amostra_b") or 999)
        if amostra < 30:
            pts.append(f"Amostra reduzida na superfície ({amostra} jogos).")
    fa = payload.get("fatigue_signal_a") or {}
    fb = payload.get("fatigue_signal_b") or {}
    if (fa.get("matches_last_7d") in (0, None)) and (fb.get("matches_last_7d") in (0, None)):
        pts.append("Sem sinais de fadiga recente.")
    ea = f.get("epoca_atual")
    if isinstance(ea, dict):
        amostra_ep = min(ea.get("amostra_a") or 999, ea.get("amostra_b") or 999)
        if amostra_ep < 15:
            pts.append(f"Poucos jogos na época atual ({amostra_ep}).")
    return pts[:5]


def _build_analysis_body(result: dict, payload: dict) -> str:
    """
    Nova estrutura orientada a TRADING. O Claude escreve só 3 blocos curtos
    (Executive Summary, Mercados a acompanhar, Veredicto — este vai ao topo).
    Tudo o resto (Model vs Market, Fatores decisivos, Pontos de atenção) é
    gerado pelo PYTHON a partir das features. Zero descrição pelo Claude.
    """
    out = []

    # 1. EXECUTIVE SUMMARY (Claude, curto)
    summary = result.get("executive_summary") or result.get("summary_line")
    if summary:
        out.append('<h2 class="sec-main">📋 Executive Summary</h2>')
        out.append(f'<div class="exec-summary">{_markdown_inline(summary)}</div>')

    # 2. MODEL vs MARKET (Python) — divergência classificada + justificada
    mvm = _compute_model_vs_market(payload)
    if mvm.get("market") and mvm.get("model"):
        a = payload.get("player_a", "A"); b = payload.get("player_b", "B")
        mk, md = mvm["market"], mvm["model"]
        clf = mvm.get("classificacao") or {}
        nivel = clf.get("nivel", 0)
        fav = mvm.get("favorecido")
        fatores = mvm.get("fatores_chave") or []
        merc_fav = mvm.get("mercado_favorece")
        # caixa de conclusão conforme o nível de divergência
        if nivel == 0:
            box = (f'<div class="mvm-align">✓ <b>Mercado eficiente</b> — os indicadores '
                   f'apontam na mesma direção do mercado. Sem divergência a assinalar.</div>')
        else:
            cor_cls = {1: "mvm-lig", 2: "mvm-mod", 3: "mvm-forte"}.get(nivel, "mvm-lig")
            just = ""
            if fatores and fav:
                fav_fatores = [f for f, quem in fatores if quem == fav]
                if fav_fatores:
                    just = f' Sustentada por: {", ".join(fav_fatores[:3])}.'
            box = (f'<div class="{cor_cls}">⚠️ <b>{_esc(clf.get("texto",""))}</b> — '
                   f'os indicadores favorecem <b>{_esc(fav)}</b>, mas o mercado favorece '
                   f'<b>{_esc(merc_fav)}</b>.{just}</div>')
        out.append('<h3 class="sec">⚖️ Indicadores vs Mercado</h3>')
        out.append(
            f'<table class="mvm-table"><thead><tr><th></th>'
            f'<th>{_esc(a)}</th><th>{_esc(b)}</th></tr></thead><tbody>'
            f'<tr><td>Mercado (s/ margem)</td><td>{mk["a"]}%</td><td>{mk["b"]}%</td></tr>'
            f'<tr><td>Índice de evidência</td><td>{md["a"]}/100</td><td>{md["b"]}/100</td></tr>'
            f'</tbody></table>{box}')

    # 3. MARKET OVERVIEW (Python) — mostra só os mercados que SE ADEQUAM à
    # análise (interesse relevante, nível >=2). Mercados sem interesse não
    # aparecem — evita ruído. Se nenhum for relevante, nota honesta.
    overview = _compute_market_overview(payload, mvm)
    relevantes = [(m, n, l) for (m, n, l) in overview if n >= 2]
    if overview:
        out.append('<h3 class="sec">📊 Market Overview</h3>')
        if relevantes:
            out.append('<table class="mo-table"><thead><tr>'
                       '<th>Mercado</th><th>Interesse</th><th>Leitura</th>'
                       '</tr></thead><tbody>')
            for merc, nivel, leitura in relevantes:
                dots = _render_interesse_dots(nivel)
                out.append(f'<tr><td><b>{_esc(merc)}</b></td>'
                           f'<td class="mo-dots">{dots}</td>'
                           f'<td>{_esc(leitura)}</td></tr>')
            out.append('</tbody></table>')
            out.append('<div class="mo-nota">Apenas os mercados com interesse para este jogo — nunca é recomendação de aposta.</div>')
        else:
            out.append('<div class="mo-empty">Sem mercados de interesse claro para este jogo. '
                       'O mercado parece eficiente face aos dados disponíveis.</div>')

    # 4. FATORES DECISIVOS (Python) — 5 bullets curtos das features
    fatores = _compute_fatores_decisivos(payload)
    if fatores:
        items = "".join(f'<li>{_esc(f)}</li>' for f in fatores)
        out.append(f'<h3 class="sec">🎯 Fatores decisivos</h3><ul class="fatores-list">{items}</ul>')

    # 5. PONTOS DE ATENÇÃO (Python) — limitações/alertas factuais
    atencao = _compute_pontos_atencao(payload)
    if atencao:
        items = "".join(f'<li>{_esc(p)}</li>' for p in atencao)
        out.append(f'<h3 class="sec">⚠️ Pontos de atenção</h3><ul class="atencao-list">{items}</ul>')

    return "".join(out)


def build_report_html(payload: dict, result: dict) -> str:
    """Gera a página HTML completa e autónoma para um jogo.

    REDESENHO V2 (auditoria do relatório): delega no build_report_html_v2, que
    aplica a nova arquitetura (decisão -> evidência -> detalhe), corrige escalas,
    estados de erro e cores. Se o V2 falhar por algum motivo inesperado, cai no
    gerador antigo (_build_report_html_v1) para nunca deixar um jogo sem página.
    """
    try:
        return build_report_html_v2(payload, result, _calcular_divergencia)
    except Exception as exc:
        import traceback
        print(f"[aviso] V2 falhou ({exc}); a usar o gerador antigo. "
              f"{traceback.format_exc().splitlines()[-1]}")
        return _build_report_html_v1(payload, result)


def _build_report_html_v1(payload: dict, result: dict) -> str:
    """Gerador antigo (V1) — mantido como fallback de segurança."""
    a = _esc(payload.get("player_a", "?"))
    b = _esc(payload.get("player_b", "?"))
    tournament = _esc(payload.get("tournament", ""))
    tier = _esc(payload.get("tier", ""))
    surface = _esc(payload.get("surface", ""))
    date_str = datetime.now(timezone.utc).strftime("%d/%m/%Y")

    # BOLA/FLAG vem do MOTOR (não do Claude) — coerente com a divergência.
    # Esquema escolhido (mapa de oportunidades): 🟢 divergência forte
    # (oportunidade clara) · 🟡 ligeira/moderada (espreitar) · 🔴 mercado
    # eficiente (pára, sem oportunidade).
    _mvm_flag = _compute_model_vs_market(payload)
    _nivel_flag = ((_mvm_flag or {}).get("classificacao") or {}).get("nivel", 0)
    if not (_mvm_flag and _mvm_flag.get("market")):
        flag = _esc(result.get("flag", "🟡"))  # fallback se não há dados de mercado
    else:
        flag = {3: "🟢", 2: "🟡", 1: "🟡", 0: "🔴"}.get(_nivel_flag, "🔴")
    _label_flag = {3: "oportunidade", 2: "a acompanhar", 1: "a acompanhar",
                   0: "mercado eficiente"}.get(_nivel_flag if (_mvm_flag and _mvm_flag.get("market")) else -1, "sinal")

    # Grau de confiança global (0-100) com cor por faixa
    # Confiança: dois eixos separados (auditoria) — cobertura de dados e
    # força do sinal. Retrocompatível com o formato antigo (confidence_score).
    def _compute_coverage(payload):
        """Cobertura CALCULADA (não subjetiva): conta as fontes de dados
        presentes no payload. Transparente — o número vem daqui, verificável.
        Devolve (pct, lista de (nome, presente))."""
        def _has(v):
            if v is None:
                return False
            if isinstance(v, dict):
                return len(v) > 0 and any(vv is not None for vv in v.values())
            return True
        rich_a = payload.get("rich_stats_a") or {}
        rich_b = payload.get("rich_stats_b") or {}
        fontes = [
            ("Odds do mercado", _has(payload.get("market_odds_decimal"))),
            ("Confronto direto (H2H)", _has(payload.get("h2h"))),
            ("Forma recente", _has(payload.get("recent_form_a")) and _has(payload.get("recent_form_b"))),
            ("Ranking", _has(payload.get("ranking_a")) and _has(payload.get("ranking_b"))),
            ("Desempenho por piso", _has(payload.get("surface_stats_a")) or _has(rich_a.get("by_surface"))),
            ("Serviço/resposta", _has(payload.get("serve_return_stats_a"))),
            ("Dados ricos de carreira", _has(rich_a.get("scenarios")) or _has(rich_a.get("vs_rank_level"))),
            ("Fadiga real (jogos recentes)", (payload.get("fatigue_signal_a") or {}).get("fatigue_source") == "api_recent"),
        ]
        presentes = sum(1 for _, ok in fontes if ok)
        pct = round(100 * presentes / len(fontes))
        return pct, fontes

    coverage_pct, coverage_fontes = _compute_coverage(payload)

    def _bar_html(label, v, extra=""):
        color = COLORS["mint"] if v >= 67 else (COLORS["amber"] if v >= 34 else COLORS["red"])
        lab = "alta" if v >= 67 else ("média" if v >= 34 else "baixa")
        return f"""
      <div class="conf-head">
        <span class="conf-title">{_esc(label)}</span>
        <span class="conf-num" style="color:{color}">{v}/100 · {lab}</span>
      </div>
      <div class="conf-track"><div class="conf-fill" style="width:{v}%;background:{color}"></div></div>{extra}"""

    def _div_bar_html(nivel, texto, extra=""):
        """Barra da DIVERGÊNCIA — mostra só a classificação (sem número
        arbitrário). Cor pelo esquema: verde=forte(oportunidade),
        amarelo=média/ligeira, vermelho=eficiente."""
        cor = {3: COLORS["mint"], 2: COLORS["amber"], 1: COLORS["amber"],
               0: COLORS["red"]}.get(nivel, COLORS["red"])
        largura = {0: 20, 1: 45, 2: 70, 3: 95}.get(nivel, 20)
        return f"""
      <div class="conf-head">
        <span class="conf-title">Divergência de sinais</span>
        <span class="conf-num" style="color:{cor}">{_esc(texto)}</span>
      </div>
      <div class="conf-track"><div class="conf-fill" style="width:{largura}%;background:{cor}"></div></div>{extra}"""

    conf_reason = _esc(result.get("confidence_reason", ""))

    # COBERTURA: número calculado pelo Python + decomposição das fontes
    # (transparente — vê-se exatamente que dados existem e quais faltam).
    presentes = sum(1 for _, ok in coverage_fontes if ok)
    chips = "".join(
        f'<span class="cov-chip {"on" if ok else "off"}">{"✓" if ok else "✗"} {_esc(nome)}</span>'
        for nome, ok in coverage_fontes
    )
    cov_extra = (f'<div class="cov-detail">{presentes}/{len(coverage_fontes)} fontes presentes'
                 f'<div class="cov-chips">{chips}</div></div>')
    cov_bar = _bar_html("Cobertura de dados", coverage_pct, cov_extra)

    # DIVERGÊNCIA (substitui a antiga "força do sinal" vaga): vem do MOTOR
    # ponderado, não do Claude. É a única fonte de verdade — a bola, esta
    # barra e o Model vs Market bebem todos daqui, por isso nunca se
    # contradizem. Mostra a classificação honesta + o gap que a justifica.
    _mvm_head = _compute_model_vs_market(payload)
    _clf = (_mvm_head or {}).get("classificacao") or {}
    _nivel_div = _clf.get("nivel", 0)
    _idx_head = (_mvm_head or {}).get("indice_evidencia") or {}
    _fav_head = (_mvm_head or {}).get("favorecido")
    force_bar = ""
    if _mvm_head and _mvm_head.get("market"):
        _label_div = _clf.get("texto", "Mercado eficiente")
        if _nivel_div >= 1 and _fav_head:
            _idx_fav = _idx_head.get("a") if _fav_head == payload.get("player_a") else _idx_head.get("b")
            _extra = f'<div class="cov-detail">Índice de evidência: {_idx_fav}/100 a favor de {_esc(_fav_head)}</div>'
        else:
            _extra = '<div class="cov-detail">Indicadores alinhados com o mercado</div>'
        force_bar = _div_bar_html(_nivel_div, _label_div, extra=_extra)

    conf_html = f"""
    <div class="confidence">{cov_bar}{force_bar}
      {f'<div class="conf-reason">{conf_reason}</div>' if conf_reason else ''}
    </div>"""

    # Info-chave no cabeçalho (sugestão do Hugo): ranking sob cada nome,
    # H2H e meteorologia numa linha central compacta. Tudo Python.
    _rank_a = (payload.get("ranking_a") or {}).get("rank")
    _rank_b = (payload.get("ranking_b") or {}).get("rank")
    _rank_a_txt = f'<div class="sb-rank">#{_rank_a}</div>' if _rank_a else ""
    _rank_b_txt = f'<div class="sb-rank">#{_rank_b}</div>' if _rank_b else ""
    # H2H central
    _h2h = (payload.get("h2h") or {}).get("overall") or {}
    _h2h_txt = ""
    if _h2h.get("total_matches"):
        _h2h_txt = f'H2H {_h2h.get("a_wins",0)}–{_h2h.get("b_wins",0)}'
    else:
        _h2h_txt = "H2H —"
    # Meteorologia central (só se ao ar livre e com dados)
    _w = payload.get("weather") or {}
    _meteo_txt = ""
    if _w.get("temp_max_c") is not None:
        _meteo_parts = [f'{_w["temp_max_c"]}°C']
        if _w.get("precipitation_mm") is not None:
            _meteo_parts.append(f'{_w["precipitation_mm"]}mm')
        _meteo_txt = " · ".join(_meteo_parts)
    _center_bits = [b for b in [_h2h_txt, _meteo_txt] if b]
    _center_line = f'<div class="sb-center">{" · ".join(_center_bits)}</div>' if _center_bits else ""
    odds = payload.get("market_odds_decimal") or {}
    name_a = payload.get("player_a", "")
    name_b = payload.get("player_b", "")

    def _find_odd(target_name):
        if not isinstance(odds, dict):
            return None
        # 1) chave direta player_a/player_b (formato antigo, por segurança)
        # 2) nome exato; 3) correspondência aproximada (apelido)
        for key in ("player_a", "player_b"):
            if key in odds and (key == "player_a") == (target_name == name_a):
                return odds[key]
        for k, v in odds.items():
            if k.lower() == target_name.lower():
                return v
        # apelido: última palavra do nome
        surname = target_name.split()[-1].lower() if target_name else ""
        for k, v in odds.items():
            if surname and surname in k.lower():
                return v
        return None

    odd_a = _find_odd(name_a)
    odd_b = _find_odd(name_b)

    # Probabilidade implícita sem margem (a "vig"), quando há as duas odds.
    # É só a leitura do que o mercado diz — não é um modelo próprio.
    prob_a_txt = prob_b_txt = ""
    try:
        if odd_a and odd_b:
            inv_a, inv_b = 1.0 / float(odd_a), 1.0 / float(odd_b)
            total = inv_a + inv_b
            prob_a_txt = f"{100 * inv_a / total:.0f}%"
            prob_b_txt = f"{100 * inv_b / total:.0f}%"
    except (ValueError, TypeError, ZeroDivisionError):
        pass

    odd_a_txt = f"{odd_a}" if odd_a else "—"
    odd_b_txt = f"{odd_b}" if odd_b else "—"

    charts = _build_charts(payload)
    data_sections = _build_data_sections(payload)

    # Alerta de topo: se houver discrepância(s) FORTE(s), destaca logo no
    # cabeçalho (bem visível, como pedido). Conta as fortes.
    strong = [d for d in (result.get("discrepancies") or [])
              if isinstance(d, dict) and (d.get("weight") or "").lower() == "forte"]
    top_alert = ""
    if strong:
        n = len(strong)
        top_alert = (
            f'<div class="top-alert">🔴 {n} sinal{"is" if n>1 else ""} forte{"s" if n>1 else ""} '
            f'de discrepância — ver "Discrepâncias" abaixo</div>'
        )

    # Nova estrutura de trading. Ordem: cabeçalho → VEREDICTO (topo, capta
    # atenção) → análise de mercado → dados estatísticos (referência).
    if result.get("full_report_markdown"):
        top_verdict = ""
        analysis_body = _render_markdown_body(result["full_report_markdown"])
        body = charts + data_sections + analysis_body
    else:
        top_verdict = _build_top_verdict(result)
        analysis_body = _build_analysis_body(result, payload)
        body = top_verdict + charts + analysis_body + data_sections

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
.sb-prob {{ font-size:12px; font-weight:400; color:var(--dim); margin-top:4px; }}
.sb-rank {{ font-size:14px; font-weight:600; color:var(--steel); margin-top:2px; }}
.sb-center {{ text-align:center; font-size:13px; color:var(--dim); margin-top:8px; letter-spacing:.02em; }}
.selos-legenda {{ display:flex; flex-wrap:wrap; gap:10px 16px; font-size:12px; color:var(--dim); margin:2px 0 12px; align-items:center; }}
.w-dot {{ display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:5px; vertical-align:middle; }}
.w-dot.red {{ background:var(--red); }}
.w-dot.amber {{ background:var(--amber); }}
.w-dot.white {{ background:var(--dim); }}
/* Barras de intensidade (auditoria P2): cor neutra azul-aço, a intensidade
   vem do nº de barras cheias — sem conflito de cor com a bola da conclusão. */
.w-bar {{ display:inline-block; width:22px; height:10px; margin-right:6px; vertical-align:middle;
  background:linear-gradient(90deg, var(--steel) 0 var(--fill,33%), rgba(120,140,160,.18) var(--fill,33%) 100%);
  border-radius:2px; }}
.w-bar-3 {{ --fill:100%; }}
.w-bar-2 {{ --fill:66%; }}
.w-bar-1 {{ --fill:33%; }}
.selos-nota {{ width:100%; font-style:italic; opacity:.8; margin-top:2px; }}
.sb-vs {{ font-size:12px; color:var(--dim); letter-spacing:.1em; margin:2px 0; }}
.sb-flag {{ display:inline-block; margin-top:14px; font-size:14px; padding:4px 12px; border-radius:20px; background:var(--surface); border:1px solid var(--line); }}

/* Alerta de topo (discrepância forte) */
.top-alert {{ margin-top:14px; padding:10px 16px; border-radius:10px; background:rgba(224,108,91,0.15); border:1px solid var(--red); color:var(--red); font-weight:700; font-size:14px; }}

/* Secções de dados factuais (montadas em Python — Medida 6) */
.data-sections {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; margin:20px 0; }}
@media (max-width:600px) {{ .data-sections {{ grid-template-columns:1fr; }} }}
.d-card {{ background:var(--surface); border:1px solid var(--line); border-radius:10px; padding:14px 16px; }}
.d-title {{ font-size:12px; text-transform:uppercase; letter-spacing:.06em; color:var(--dim); margin-bottom:8px; }}
.d-row {{ font-size:14px; margin:3px 0; }}

/* Pontos-chave */
.kp-list {{ list-style:none; padding:0; margin:8px 0 20px; }}
.kp-list li {{ padding:8px 14px; margin:6px 0; background:var(--surface); border-left:3px solid var(--steel); border-radius:6px; font-size:15px; }}

/* Discrepâncias com selos e destaque por peso */
.disc-item {{ padding:12px 16px; margin:8px 0; border-radius:8px; background:var(--surface); font-size:15px; display:flex; gap:10px; align-items:flex-start; }}
.disc-emoji {{ flex-shrink:0; }}
.disc-text {{ flex:1; }}
.risks-list {{ margin:8px 0; padding-left:22px; }}
.risks-list li {{ margin:6px 0; font-size:14px; color:var(--muted); }}
.markets-table {{ width:100%; border-collapse:collapse; margin:8px 0; font-size:14px; }}
.markets-table th {{ text-align:left; padding:8px 10px; color:var(--muted); font-weight:600; border-bottom:1px solid var(--border); font-size:12px; text-transform:uppercase; }}
.markets-table td {{ padding:10px; border-bottom:1px solid var(--border); vertical-align:top; }}
.conf-badge {{ padding:2px 10px; border-radius:12px; font-size:12px; font-weight:600; }}
.conf-alta {{ background:rgba(45,180,120,0.18); color:#2db478; }}
.conf-media {{ background:rgba(230,180,60,0.18); color:#e6b43c; }}
.conf-baixa {{ background:rgba(150,150,150,0.15); color:var(--muted); }}
.disc-strong {{ border-left:4px solid var(--red); background:rgba(224,108,91,0.08); }}
.disc-mid {{ border-left:4px solid var(--amber); }}
.disc-weak {{ border-left:4px solid var(--dim); opacity:.9; }}

/* Veredicto — caixa destacada a fechar */
.verdict-box {{ margin:24px 0 8px; padding:18px 20px; border-radius:12px; background:linear-gradient(180deg,rgba(78,205,196,0.12),var(--surface)); border:1px solid var(--mint); }}
.verdict-box.top {{ margin:16px 0 20px; }}
.exec-summary {{ background:var(--surface); border-left:3px solid var(--steel); padding:14px 16px; border-radius:8px; margin:8px 0 4px; font-size:15px; }}
.mvm-table {{ width:100%; border-collapse:collapse; margin:8px 0; font-size:14px; }}
.mvm-table th {{ text-align:center; padding:8px 10px; color:var(--dim); font-size:12px; text-transform:uppercase; border-bottom:1px solid var(--line); }}
.mvm-table th:first-child {{ text-align:left; }}
.mvm-table td {{ padding:9px 10px; border-bottom:1px solid var(--line); text-align:center; font-weight:600; }}
.mvm-table td:first-child {{ text-align:left; font-weight:400; color:var(--dim); }}
.mvm-diverg {{ background:rgba(230,180,60,0.12); border-left:3px solid var(--amber); padding:10px 14px; border-radius:8px; margin:6px 0; font-size:14px; }}
.mvm-align {{ background:rgba(78,205,196,0.10); border-left:3px solid var(--mint); padding:10px 14px; border-radius:8px; margin:6px 0; font-size:14px; }}
.mvm-lig {{ background:rgba(230,180,60,0.10); border-left:3px solid var(--amber); padding:10px 14px; border-radius:8px; margin:6px 0; font-size:14px; }}
.mvm-mod {{ background:rgba(230,140,60,0.14); border-left:3px solid #e68c3c; padding:10px 14px; border-radius:8px; margin:6px 0; font-size:14px; }}
.mvm-forte {{ background:rgba(224,108,91,0.16); border-left:3px solid var(--red); padding:10px 14px; border-radius:8px; margin:6px 0; font-size:14px; }}
.fatores-list, .atencao-list {{ margin:8px 0; padding-left:22px; }}
.fatores-list li {{ margin:6px 0; font-size:15px; }}
.atencao-list li {{ margin:6px 0; font-size:14px; color:var(--dim); }}
.mo-table {{ width:100%; border-collapse:collapse; margin:8px 0 4px; font-size:14px; }}
.mo-table th {{ text-align:left; padding:8px 10px; color:var(--dim); font-size:12px; text-transform:uppercase; border-bottom:1px solid var(--line); }}
.mo-table td {{ padding:10px; border-bottom:1px solid var(--line); vertical-align:middle; }}
.mo-dots {{ white-space:nowrap; }}
.mo-dot {{ display:inline-block; width:11px; height:11px; border-radius:50%; margin-right:3px; }}
.mo-dot.dot-green {{ background:var(--mint); }}
.mo-dot.dot-amber {{ background:var(--amber); }}
.mo-dot.dot-red {{ background:var(--red); }}
.mo-dot.dot-empty {{ background:transparent; border:1px solid var(--line); }}
.mo-nota {{ font-size:12px; color:var(--dim); font-style:italic; margin:4px 0 8px; }}
.mo-empty {{ background:rgba(224,108,91,0.08); border-left:3px solid var(--red); padding:12px 14px; border-radius:8px; margin:6px 0; font-size:14px; color:var(--dim); }}
.verdict-label {{ font-size:13px; text-transform:uppercase; letter-spacing:.08em; color:var(--mint); font-weight:700; margin-bottom:6px; }}
.verdict-text {{ font-size:16px; line-height:1.5; }}

/* Confiança da leitura */
.confidence {{ margin-top:16px; max-width:420px; }}
.conf-head {{ display:flex; justify-content:space-between; align-items:baseline; margin-bottom:6px; }}
.conf-title {{ font-size:12px; text-transform:uppercase; letter-spacing:.08em; color:var(--dim); }}
.conf-num {{ font-size:15px; font-weight:700; }}
.conf-track {{ height:8px; background:var(--surface-alt); border-radius:5px; overflow:hidden; }}
.conf-fill {{ height:100%; border-radius:5px; }}
.conf-reason {{ font-size:13px; color:var(--dim); margin-top:6px; font-style:italic; }}
.cov-detail {{ font-size:12px; color:var(--dim); margin-top:6px; }}
.cov-chips {{ display:flex; flex-wrap:wrap; gap:5px; margin-top:6px; }}
.cov-chip {{ font-size:11px; padding:2px 7px; border-radius:10px; border:1px solid var(--line); }}
.cov-chip.on {{ color:var(--mint); border-color:var(--mint); }}
.cov-chip.off {{ color:var(--dim); opacity:.6; }}

/* Gráficos */
.charts {{ margin:26px 0; }}
.chart-block {{ background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:18px; margin-bottom:16px; }}
.chart-title {{ font-size:13px; text-transform:uppercase; letter-spacing:.08em; color:var(--dim); margin-bottom:14px; }}
.cmp {{ margin:10px 0; }}
.cmp-label {{ font-size:13px; color:var(--dim); margin-bottom:4px; text-align:center; }}
.cmp-label b {{ color:var(--text); font-size:14px; }}
.lvl-games {{ font-size:11px; color:var(--dim); opacity:0.7; }}
.avb-head {{ display:grid; grid-template-columns:1fr auto auto; gap:8px 16px; padding:4px 0 6px; border-bottom:1px solid var(--line); margin-bottom:4px; }}
.avb-head .avb-a, .avb-head .avb-b {{ font-size:12px; font-weight:700; color:var(--steel); min-width:52px; text-align:right; }}
.avb-row {{ display:grid; grid-template-columns:1fr auto auto; gap:8px 16px; padding:5px 0; font-size:14px; }}
.avb-lbl {{ color:var(--dim); }}
.avb-a, .avb-b {{ min-width:52px; text-align:right; font-weight:600; }}
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
.item.w-bar-3 {{ border-left:4px solid var(--steel); }}
.item.w-bar-2 {{ border-left:4px solid rgba(120,140,160,.6); }}
.item.w-bar-1 {{ border-left:4px solid rgba(120,140,160,.3); opacity:.85; }}
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
      <div class="sb-name">{a}{_rank_a_txt}<div class="sb-prob">{prob_a_txt}{' s/ margem' if prob_a_txt else ''}</div></div>
      <div class="sb-odds">
        <div class="sb-odd">{odd_a_txt}</div>
        <div class="sb-vs">VS</div>
        <div class="sb-odd">{odd_b_txt}</div>
      </div>
      <div class="sb-name right">{b}{_rank_b_txt}<div class="sb-prob">{prob_b_txt}{' s/ margem' if prob_b_txt else ''}</div></div>
    </div>
    {_center_line}
    <div class="sb-flag">{flag} {_label_flag}</div>
    {conf_html}
    {top_alert}
  </div>
</header>
<div class="wrap">
  {body}
  <div class="footer">Tennis Pre-Live Bot · análise informativa, não é recomendação de aposta</div>
</div>
</body>
</html>"""

# ============================================================
# RELATÓRIO V2 (redesenho da auditoria) — integrado
# ============================================================
# ---- ESCALA ÚNICA (auditoria P0.2): normaliza %, aceita 0.68 ou 68 ----
def _pct(v):
    """Normaliza qualquer valor de percentagem para 0-100. Aceita fração
    (0.68 -> 68) ou já-percentagem (68 -> 68). Função ÚNICA de normalização,
    usada em TODO o relatório antes de renderizar (resolve o 6800%)."""
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return round(v * 100, 1) if v <= 1.5 else round(v, 1)


def _pct_str(v, casas=0):
    p = _pct(v)
    if p is None:
        return "—"
    return f"{p:.{casas}f}%"


# ---- PALETA V2 (cada cor com um só significado) ----
COLORS_V2 = {
    "bg": "#0f1419", "surface": "#161c23", "surface2": "#1c242d",
    "text": "#e6edf3", "dim": "#8896a5", "line": "#2a333d",
    "a": "#4aa3df",        # jogador A — azul-ciano (frio)
    "b": "#e8935a",        # jogador B — laranja-âmbar (quente, contrasta com A)
    "mint": "#3fb9a8",     # divergência relevante / oportunidade
    "amber": "#d9a441",    # a acompanhar
    "neutral": "#5a6b7a",  # mercado eficiente / sem divergência
    "error": "#e06c5b",    # SÓ erro / dados indisponíveis
}


# ---- DETEÇÃO DE ESTADO (auditoria P0.3 + #17) ----
def detetar_estado(payload, result, divergencia):
    """Determina o estado do relatório, que muda o layout.
    Devolve: (chave, cor, label, bola)
      - 'erro': sem análise E/ou dados corrompidos -> layout parcial
      - 'sem_odds': sem mercado -> não avalia eficiência, sem sinal
      - 'eficiente': mercado alinhado com indicadores
      - 'acompanhar': divergência ligeira/moderada
      - 'oportunidade': divergência forte
    """
    tem_odds = bool(divergencia and divergencia.get("market"))
    analise_falhou = bool(result.get("analysis_error") or result.get("llm_error"))
    if analise_falhou and not tem_odds:
        return ("erro", COLORS_V2["error"], "Análise parcial", "⚠️")
    if not tem_odds:
        return ("sem_odds", COLORS_V2["neutral"], "Sem odds — comparação indisponível", "⚪")
    nivel = (divergencia.get("classificacao") or {}).get("nivel", 0)
    tipo = divergencia.get("tipo", "")
    if nivel >= 3:
        lbl = "Convicção forte" if tipo == "conviccao" else "Divergência forte"
        return ("oportunidade", COLORS_V2["mint"], lbl, "🟢")
    if nivel >= 1:
        return ("acompanhar", COLORS_V2["amber"], "A acompanhar", "🟡")
    return ("eficiente", COLORS_V2["neutral"], "Mercado eficiente", "⚪")


def _css():
    c = COLORS_V2
    return f"""
:root {{
  --bg:{c['bg']}; --surface:{c['surface']}; --surface2:{c['surface2']};
  --text:{c['text']}; --dim:{c['dim']}; --line:{c['line']};
  --a:{c['a']}; --b:{c['b']}; --mint:{c['mint']}; --amber:{c['amber']};
  --neutral:{c['neutral']}; --error:{c['error']};
}}
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ background:var(--bg); color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;
  line-height:1.5; font-variant-numeric:tabular-nums;
  -webkit-font-smoothing:antialiased; padding:16px; }}
.wrap {{ max-width:1080px; margin:0 auto; }}
.wrap-text {{ max-width:720px; margin-left:auto; margin-right:auto; }}
.num {{ font-variant-numeric:tabular-nums; }}

/* --- MATCHUP HEADER (ficha de combate) --- */
.mh {{ background:var(--surface); border:1px solid var(--line); border-radius:14px;
  padding:20px; margin-bottom:14px; }}
.mh-top {{ display:grid; grid-template-columns:1fr auto 1fr; gap:12px; align-items:start; }}
.mh-name {{ font-size:22px; font-weight:700; letter-spacing:-.3px;
  border-left:3px solid var(--a); padding-left:8px; }}
.mh-name.b {{ text-align:right; border-left:none;
  border-right:3px solid var(--b); padding-left:0; padding-right:8px; }}
.mh-sub {{ font-size:13px; color:var(--dim); margin-top:3px; }}
.mh-sub.b {{ text-align:right; }}
.mh-vs {{ font-size:12px; color:var(--dim); text-align:center; padding-top:6px;
  font-weight:600; letter-spacing:1px; }}
.mh-tourn {{ font-size:11px; color:var(--dim); text-align:center; margin-top:4px;
  text-transform:uppercase; letter-spacing:.5px; }}
.mh-odds {{ display:grid; grid-template-columns:1fr auto 1fr; gap:12px;
  margin-top:14px; padding-top:14px; border-top:1px solid var(--line); }}
.mh-odd {{ font-size:20px; font-weight:700; }}
.mh-odd.b {{ text-align:right; }}
.mh-odd small {{ display:block; font-size:12px; color:var(--dim); font-weight:400; }}
.mh-mid {{ text-align:center; font-size:12px; color:var(--dim); }}

/* --- LEITURA DO JOGO (a decisão, 1 frase) --- */
.leitura {{ border-radius:12px; padding:14px 16px; margin-bottom:14px;
  border:1px solid var(--line); display:flex; gap:12px; align-items:center; }}
.leitura-bola {{ font-size:24px; }}
.leitura-txt b {{ font-size:15px; }}
.leitura-txt div {{ font-size:13px; color:var(--dim); margin-top:2px; }}

/* --- 4 FATORES (chips) --- */
.fatores {{ display:grid; grid-template-columns:repeat(4,1fr); gap:8px; margin-bottom:14px; }}
@media(max-width:640px){{ .fatores {{ grid-template-columns:repeat(2,1fr); }} }}
.fator {{ background:var(--surface); border:1px solid var(--line); border-radius:10px;
  padding:10px; text-align:center; }}
.fator-lbl {{ font-size:10px; color:var(--dim); text-transform:uppercase;
  letter-spacing:.5px; margin-bottom:4px; }}
.fator-val {{ font-size:14px; font-weight:600; }}
.fator-fav {{ font-size:11px; margin-top:2px; }}

/* --- MERCADO vs SINAL (gráfico central) --- */
.mvs {{ background:var(--surface); border:1px solid var(--line); border-radius:12px;
  padding:18px; margin-bottom:14px; }}
.mvs h3, .card h3 {{ font-size:12px; text-transform:uppercase; letter-spacing:1px;
  color:var(--dim); margin-bottom:14px; font-weight:600; }}
.mvs-row {{ margin-bottom:14px; }}
.mvs-row-lbl {{ display:flex; justify-content:space-between; font-size:12px;
  color:var(--dim); margin-bottom:5px; }}
.mvs-track {{ position:relative; height:26px; background:var(--surface2);
  border-radius:6px; overflow:hidden; }}
.mvs-fill {{ position:absolute; top:0; bottom:0; left:0; border-radius:6px; }}
.mvs-mid {{ position:absolute; left:50%; top:0; bottom:0; width:1px;
  background:var(--dim); opacity:.4; }}
.mvs-val {{ position:absolute; top:50%; transform:translateY(-50%); font-size:12px;
  font-weight:700; padding:0 8px; }}
.mvs-delta {{ text-align:center; font-size:13px; margin-top:10px; font-weight:600; }}

/* --- CARDS genéricos --- */
.card {{ background:var(--surface); border:1px solid var(--line); border-radius:12px;
  padding:16px; margin-bottom:14px; }}
.grid2 {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; }}
@media(max-width:760px){{ .grid2 {{ grid-template-columns:1fr; }} }}

/* --- barra comparativa (forma, serviço) --- */
.cmp {{ margin-bottom:12px; }}
.cmp:last-child {{ margin-bottom:0; }}
.cmp-lbl {{ font-size:12px; color:var(--dim); margin-bottom:6px; }}
.cmp-row {{ display:grid; grid-template-columns:90px 1fr 54px; gap:8px;
  align-items:center; margin-bottom:4px; }}
.cmp-name {{ font-size:12px; color:var(--dim); overflow:hidden;
  text-overflow:ellipsis; white-space:nowrap; }}
.cmp-bar {{ height:14px; background:var(--surface2); border-radius:4px; overflow:hidden; }}
.cmp-bar span {{ display:block; height:100%; border-radius:4px; }}
.cmp-num {{ font-size:13px; font-weight:600; text-align:right; }}
.cmp-delta {{ font-size:11px; text-align:center; color:var(--mint); margin-top:3px; }}

/* amostra (auditoria #8): esbatido se n<10 */
.samp-low {{ opacity:.5; }}
.samp-tag {{ font-size:10px; color:var(--dim); }}

/* --- fadiga --- */
.fadiga-cmp {{ display:grid; grid-template-columns:1fr auto 1fr; gap:12px; align-items:center; }}
.fadiga-side {{ font-size:13px; }}
.fadiga-side.b {{ text-align:right; }}
.fadiga-big {{ font-size:18px; font-weight:700; }}
.fadiga-delta {{ text-align:center; font-size:12px; color:var(--amber); font-weight:600; }}

/* --- details (mais estatísticas) --- */
details.more {{ background:var(--surface); border:1px solid var(--line);
  border-radius:12px; margin-bottom:14px; }}
details.more>summary {{ padding:14px 16px; cursor:pointer; font-size:13px;
  font-weight:600; color:var(--dim); list-style:none; }}
details.more>summary::-webkit-details-marker {{ display:none; }}
details.more>summary::before {{ content:"▸ "; }}
details.more[open]>summary::before {{ content:"▾ "; }}
details.more .more-body {{ padding:0 16px 16px; }}

/* --- estado parcial/erro --- */
.parcial {{ background:rgba(224,108,91,.1); border:1px solid var(--error);
  border-radius:12px; padding:16px; margin-bottom:14px; }}
.parcial b {{ color:var(--error); }}

/* --- veredicto --- */
.veredicto {{ background:var(--surface); border:1px solid var(--line);
  border-radius:12px; padding:18px; margin-bottom:14px; }}
.veredicto h3 {{ font-size:12px; text-transform:uppercase; letter-spacing:1px;
  color:var(--dim); margin-bottom:10px; }}
.merc-linha {{ display:flex; align-items:center; gap:10px; padding:7px 0;
  border-bottom:1px solid var(--line); font-size:13px; }}
.merc-linha:last-of-type {{ border-bottom:none; }}
.merc-bola {{ font-size:14px; }}
.merc-nome {{ font-weight:600; min-width:130px; }}
.merc-nota {{ color:var(--dim); font-size:12px; }}
.merc-aviso {{ font-size:11px; color:var(--dim); margin-top:10px;
  padding-top:8px; border-top:1px solid var(--line); }}
.h2h-line {{ font-size:14px; line-height:1.6; }}
.foot {{ text-align:center; font-size:11px; color:var(--dim); margin-top:20px;
  padding-top:14px; border-top:1px solid var(--line); }}
"""


# ============ MÓDULOS DE RENDERIZAÇÃO ============

def _mod_header(payload, div, estado):
    """Módulo 1: Matchup header (ficha de combate)."""
    a = _esc(payload.get("player_a", "?")); b = _esc(payload.get("player_b", "?"))
    ra = payload.get("rank_a") or {}; rb = payload.get("rank_b") or {}
    rank_a = f"#{ra.get('rank')}" if ra.get("rank") else ""
    rank_b = f"#{rb.get('rank')}" if rb.get("rank") else ""
    tourn = _esc(payload.get("tournament", "")); tier = _esc(payload.get("tier", ""))
    surf = _esc(payload.get("surface", ""))
    odds = payload.get("market_odds_decimal") or {}
    oa = odds.get(payload.get("player_a")) or "—"
    ob = odds.get(payload.get("player_b")) or "—"
    # prob mercado
    pa = pb = None
    if div and div.get("market"):
        pa = div["market"]["a"]; pb = div["market"]["b"]
    # forma resumida
    fa = payload.get("recent_form_a") or {}; fb = payload.get("recent_form_b") or {}
    forma_a = f"Forma {fa.get('wins','?')}–{fa.get('losses','?')}" if fa else ""
    forma_b = f"Forma {fb.get('wins','?')}–{fb.get('losses','?')}" if fb else ""
    # meteo à hora do jogo (contextual)
    w = payload.get("weather") or {}
    meteo = ""
    if w:
        bits = []
        if w.get("hour_local"): bits.append(_esc(w["hour_local"]))
        if w.get("temp_c") is not None: bits.append(f"{w['temp_c']:.0f}°C")
        if w.get("humidity") is not None: bits.append(f"{w['humidity']:.0f}% HR")
        if w.get("wind_kmh") is not None: bits.append(f"vento {w['wind_kmh']:.0f} km/h")
        if w.get("precip_mm"): bits.append(f"{w['precip_mm']:.0f}mm chuva")
        meteo = " · ".join(bits)
    return f"""
<div class="mh">
  <div class="mh-top">
    <div>
      <div class="mh-name">{a}</div>
      <div class="mh-sub">{rank_a} · {forma_a}</div>
    </div>
    <div>
      <div class="mh-vs">VS</div>
      <div class="mh-tourn">{tourn}<br>{tier} · {surf}</div>
    </div>
    <div>
      <div class="mh-name b">{b}</div>
      <div class="mh-sub b">{rank_b} · {forma_b}</div>
    </div>
  </div>
  <div class="mh-odds">
    <div class="mh-odd">{oa}<small>{f'{pa}% mercado' if pa is not None else 'sem odds'}</small></div>
    <div class="mh-mid">{_esc(meteo)}</div>
    <div class="mh-odd b">{ob}<small>{f'{pb}% mercado' if pb is not None else ''}</small></div>
  </div>
</div>"""


def _mod_leitura(payload, div, estado, result):
    """Módulo 2: Leitura do jogo — a decisão numa frase."""
    chave, cor, label, bola = estado
    a = _esc(payload.get("player_a", "?")); b = _esc(payload.get("player_b", "?"))
    if chave in ("erro", "sem_odds"):
        sub = ("Sem odds de mercado para comparar — mostramos só os dados factuais."
               if chave == "sem_odds" else "Análise indisponível — dados factuais apenas.")
        return f"""
<div class="leitura" style="border-color:{cor}">
  <div class="leitura-bola">{bola}</div>
  <div class="leitura-txt"><b>{label}</b><div>{sub}</div></div>
</div>"""
    fav = div.get("favorecido")
    idx = div.get("indice_evidencia") or {}
    idx_fav = idx.get("a") if fav == payload.get("player_a") else idx.get("b")
    merc_fav = div.get("mercado_favorece")
    tipo = div.get("tipo", "")
    if chave == "eficiente":
        frase = f"Os indicadores e o mercado concordam ({_esc(merc_fav)} favorito). Sem valor aparente."
    elif tipo == "conviccao":
        # favorito subvalorizado: mercado e índice no mesmo lado, mas índice mais forte
        frase = (f"<b>{_esc(fav)}</b> é favorito do mercado <b>e</b> dos indicadores "
                 f"(índice {idx_fav}/100) — mas os dados suportam-no mais do que a odd "
                 f"reflete. Favorito a acompanhar.")
    else:
        # divergência de direção: contra o mercado
        frase = (f"Os indicadores apontam para <b>{_esc(fav)}</b> (índice {idx_fav}/100), "
                 f"mas o mercado favorece <b>{_esc(merc_fav)}</b>.")
    return f"""
<div class="leitura" style="border-color:{cor}">
  <div class="leitura-bola">{bola}</div>
  <div class="leitura-txt"><b>{label}</b><div>{frase}</div></div>
</div>"""


def _mod_fatores(payload, div):
    """Módulo 3: os 4 fatores decisivos em chips."""
    fatores = (div or {}).get("fatores_chave") or []
    if not fatores:
        return ""
    chips = []
    for nome, quem in fatores[:4]:
        quem_esc = _esc(quem)
        chips.append(f"""
<div class="fator">
  <div class="fator-lbl">{_esc(nome)}</div>
  <div class="fator-fav" style="color:var(--mint)">▲ {quem_esc}</div>
</div>""")
    while len(chips) < 4:
        chips.append('<div class="fator"><div class="fator-lbl">—</div></div>')
    return f'<div class="fatores">{"".join(chips)}</div>'


def _mod_mercado_vs_sinal(payload, div):
    """Módulo 4: Mercado vs Sinal — o gráfico central. Índice de evidência,
    não pseudo-probabilidade (auditoria #15)."""
    if not div or not div.get("market"):
        return ""
    a = _esc(payload.get("player_a", "?")); b = _esc(payload.get("player_b", "?"))
    mk = div["market"]; idx = div.get("indice_evidencia") or {}
    ca, cb = COLORS_V2["a"], COLORS_V2["b"]

    def barra(titulo, va, vb, sufixo=""):
        return f"""
<div class="mvs-row">
  <div class="mvs-row-lbl"><span>{a}</span><span>{titulo}</span><span>{b}</span></div>
  <div class="mvs-track">
    <div class="mvs-fill" style="width:{va}%; background:{ca}; opacity:.7"></div>
    <div class="mvs-mid"></div>
    <div class="mvs-val" style="left:0; color:#fff">{va}{sufixo}</div>
    <div class="mvs-val" style="right:0; color:#fff">{vb}{sufixo}</div>
  </div>
</div>"""

    merc = barra("Mercado", mk["a"], mk["b"], "%")
    sinal = barra("Índice de sinais", idx.get("a", 50), idx.get("b", 50), "/100")
    fav = div.get("favorecido")
    clf = (div.get("classificacao") or {}).get("texto", "")
    delta = ""
    if fav:
        delta = f'<div class="mvs-delta" style="color:var(--mint)">{clf} — indicadores a favor de {_esc(fav)}</div>'
    return f"""
<div class="mvs">
  <h3>Mercado vs Sinal</h3>
  {merc}{sinal}{delta}
</div>"""


def _barra_cmp(nome, valor, cor, largura_pct, sufixo="%", amostra=None):
    """Uma linha de barra comparativa com nome, barra e número."""
    tag = ""
    cls = ""
    if amostra is not None:
        tag = f' <span class="samp-tag">n={amostra}</span>'
        if amostra < 10:
            cls = " samp-low"
    return f"""
<div class="cmp-row{cls}">
  <div class="cmp-name"><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:{cor};margin-right:5px;vertical-align:middle"></span>{_esc(nome)}</div>
  <div class="cmp-bar"><span style="width:{largura_pct}%; background:{cor}"></span></div>
  <div class="cmp-num">{valor}{sufixo}{tag}</div>
</div>"""


def _mod_forma(payload):
    """Módulo 5: Forma + época num só card (auditoria #6 — elimina gauges
    duplicados e o card textual)."""
    a = _esc(payload.get("player_a", "?")); b = _esc(payload.get("player_b", "?"))
    fa = payload.get("recent_form_a") or {}; fb = payload.get("recent_form_b") or {}
    sa = payload.get("season_a") or {}; sb = payload.get("season_b") or {}
    if not (fa and fb):
        return ""
    ca, cb = COLORS_V2["a"], COLORS_V2["b"]

    def pct_form(d):
        if not d or not d.get("matches"):
            return None
        return round(100 * d["wins"] / d["matches"])
    fpa, fpb = pct_form(fa), pct_form(fb)
    spa, spb = pct_form(sa), pct_form(sb)
    forma_bloc = f"""
<div class="cmp">
  <div class="cmp-lbl">Forma (últimos {fa.get('matches','?')})</div>
  {_barra_cmp(a, f"{fa.get('wins')}–{fa.get('losses')} · {fpa}", ca, fpa or 0, "%")}
  {_barra_cmp(b, f"{fb.get('wins')}–{fb.get('losses')} · {fpb}", cb, fpb or 0, "%")}
</div>"""
    epoca_bloc = ""
    if sa and sb and spa is not None and spb is not None:
        epoca_bloc = f"""
<div class="cmp">
  <div class="cmp-lbl">Época atual</div>
  {_barra_cmp(a, f"{sa.get('wins')}–{sa.get('losses')} · {spa}", ca, spa, "%")}
  {_barra_cmp(b, f"{sb.get('wins')}–{sb.get('losses')} · {spb}", cb, spb, "%")}
</div>"""
    return f'<div class="card"><h3>Forma</h3>{forma_bloc}{epoca_bloc}</div>'


def _mod_servico(payload):
    """Módulo 6: Serviço/resposta com DELTAS explícitos (auditoria #7)."""
    sa = payload.get("serve_return_stats_a") or {}
    sb = payload.get("serve_return_stats_b") or {}
    if not (sa and sb):
        return ""
    a = payload.get("player_a", "A"); b = payload.get("player_b", "B")
    metricas = [
        ("1º serviço ganho", "avg_first_serve_won_pct"),
        ("BP salvos", "avg_break_points_saved_pct"),
        ("Resposta ganha", "avg_return_points_won_pct"),
        ("BP convertidos", "avg_break_points_converted_pct"),
    ]
    linhas = []
    for label, key in metricas:
        va, vb = _pct(sa.get(key)), _pct(sb.get(key))
        if va is None or vb is None:
            continue
        delta = va - vb
        if abs(delta) < 0.5:
            vant = "="
            cor_d = COLORS_V2["dim"]
        elif delta > 0:
            vant = f"+{delta:.1f} {_esc(a.split()[-1])}"
            cor_d = COLORS_V2["a"]
        else:
            vant = f"+{abs(delta):.1f} {_esc(b.split()[-1])}"
            cor_d = COLORS_V2["b"]
        linhas.append(f"""
<div class="cmp-row" style="grid-template-columns:1fr 70px 90px 70px">
  <div class="cmp-name">{_esc(label)}</div>
  <div class="cmp-num">{va:.1f}%</div>
  <div class="cmp-delta" style="color:{cor_d}">{vant}</div>
  <div class="cmp-num">{vb:.1f}%</div>
</div>""")
    if not linhas:
        return ""
    return f"""
<div class="card"><h3>Serviço / Resposta</h3>
  <div class="cmp-row" style="grid-template-columns:1fr 70px 90px 70px; color:var(--dim); font-size:11px">
    <div></div><div class="cmp-num">{_esc(a.split()[-1])}</div>
    <div class="cmp-delta" style="color:var(--dim)">vantagem</div>
    <div class="cmp-num">{_esc(b.split()[-1])}</div>
  </div>
  {"".join(linhas)}
</div>"""


def _mod_fadiga(payload):
    """Módulo 7: Fadiga como comparador em destaque (auditoria — sobe muito)."""
    fa = payload.get("fatigue_signal_a") or {}
    fb = payload.get("fatigue_signal_b") or {}
    if not (fa.get("matches_last_7d") is not None and fb.get("matches_last_7d") is not None):
        return ""
    a = _esc(payload.get("player_a", "A")); b = _esc(payload.get("player_b", "B"))
    ja, jb = fa.get("matches_last_7d", 0), fb.get("matches_last_7d", 0)
    seta, setb = fa.get("sets_last_7d", 0), fb.get("sets_last_7d", 0)
    delta_sets = seta - setb
    delta_txt = ""
    if delta_sets != 0:
        mais = a if delta_sets > 0 else b
        delta_txt = f"Δ +{abs(delta_sets)} sets {_esc(mais)}"
    return f"""
<div class="card"><h3>Carga (7 dias)</h3>
  <div class="fadiga-cmp">
    <div class="fadiga-side">
      <div class="fadiga-big">{ja} jogos</div>
      <div class="samp-tag">{seta} sets · {fa.get('days_since_last_match','?')}d descanso</div>
    </div>
    <div class="fadiga-delta">{delta_txt}</div>
    <div class="fadiga-side b">
      <div class="fadiga-big">{jb} jogos</div>
      <div class="samp-tag">{setb} sets · {fb.get('days_since_last_match','?')}d descanso</div>
    </div>
  </div>
</div>"""


def _mod_cenarios(payload):
    """Módulo 9: cenários — só os DIFERENCIADORES (auditoria)."""
    ra = (payload.get("rich_stats_a") or {}).get("scenarios") or {}
    rb = (payload.get("rich_stats_b") or {}).get("scenarios") or {}
    if not (ra and rb):
        return ""
    a = _esc(payload.get("player_a", "A")); b = _esc(payload.get("player_b", "B"))
    ca, cb = COLORS_V2["a"], COLORS_V2["b"]
    cenarios = [
        ("Set decisivo", "deciding_set_win_pct", "deciding_set_count"),
        ("Recupera após perder 1º set", "first_set_lose_then_win_pct", "first_set_lose_count"),
    ]
    linhas = []
    for label, key, ckey in cenarios:
        va, vb = ra.get(key), rb.get(key)
        if va is None or vb is None:
            continue
        # só mostra se diferencia (>=8 p.p.)
        if abs(va - vb) < 8:
            continue
        na, nb = ra.get(ckey), rb.get(ckey)
        linhas.append(f"""
<div class="cmp">
  <div class="cmp-lbl">{_esc(label)}</div>
  {_barra_cmp(a, f"{va}", ca, va, "%", amostra=na)}
  {_barra_cmp(b, f"{vb}", cb, vb, "%", amostra=nb)}
</div>""")
    if not linhas:
        return ""
    return f'<div class="card"><h3>Cenários decisivos</h3>{"".join(linhas)}</div>'


def _mod_h2h(payload):
    """Módulo H2H (auditoria 2, ponto 2): o H2H tem peso 10 no motor mas não
    aparecia no V2. Mostra de forma clara e curta, com as regras pedidas:
    - histórico suficiente -> 'X lidera 3–1' (+ piso se relevante)
    - equilibrado -> '2–2 sem vantagem'
    - 1 confronto -> 'amostra insuficiente'
    - nenhum -> 'sem confrontos'"""
    h = payload.get("h2h")
    a = _esc(payload.get("player_a", "A")); b = _esc(payload.get("player_b", "B"))
    if not h:
        overall = None
    else:
        overall = h.get("overall") or h
    if not overall or overall.get("total_matches", overall.get("total", 0)) in (0, None):
        texto = "Sem confrontos diretos entre as duas jogadoras."
        return f'<div class="card"><h3>Confronto direto (H2H)</h3><div class="h2h-line">{texto}</div></div>'
    aw = overall.get("a_wins", 0); bw = overall.get("b_wins", 0)
    total = overall.get("total_matches", overall.get("total", aw + bw))
    # piso, se houver
    surf = (h.get("surface") or {}) if isinstance(h, dict) else {}
    saw, sbw = surf.get("a_wins"), surf.get("b_wins")
    surf_txt = ""
    if saw is not None and sbw is not None and (saw + sbw) > 0:
        piso_nome = _esc(payload.get("surface", "piso"))
        lider_s = a if saw > sbw else (b if sbw > saw else None)
        if lider_s:
            surf_txt = f"; {max(saw,sbw)}–{min(saw,sbw)} em {piso_nome.lower()}"
    if total == 1:
        texto = f"1 confronto apenas — amostra insuficiente para sinal relevante."
    elif aw == bw:
        texto = f"{aw}–{bw} — sem vantagem relevante no confronto direto."
    else:
        lider = a if aw > bw else b
        texto = f"<b>{lider}</b> lidera {max(aw,bw)}–{min(aw,bw)} nos confrontos anteriores{surf_txt}."
    return f'<div class="card"><h3>Confronto direto (H2H)</h3><div class="h2h-line">{texto}</div></div>'


def _mod_mercados(payload, div):
    """Mercados a acompanhar (auditoria pontos 7, 16): marca INTERESSE, nunca
    'valor' (só temos odds de Moneyline). 'acompanhar' ≠ 'apostar'."""
    if not div or not div.get("market"):
        return ""
    a = payload.get("player_a", "A"); b = payload.get("player_b", "B")
    mk = div["market"]
    fav = div.get("favorecido")
    nivel = (div.get("classificacao") or {}).get("nivel", 0)
    linhas = []
    # Moneyline — vem do motor (é o único mercado com odds)
    if nivel >= 2 and fav:
        linhas.append(("🟢", f"Moneyline {_esc(fav)}", "indicadores divergem do mercado"))
    elif nivel == 1 and fav:
        linhas.append(("🟡", f"Moneyline {_esc(fav)}", "divergência ligeira"))
    else:
        linhas.append(("⚪", "Moneyline", "mercado alinhado com os indicadores"))
    # Total Games e Handicap — só marcam interesse pelo equilíbrio (NÃO valor,
    # não temos odds destes mercados)
    margem = abs(mk["a"] - mk["b"])
    if margem <= 12:
        linhas.append(("🟡", "Total Games", "jogo equilibrado — acompanhar linhas ao vivo"))
        linhas.append(("🟡", "Handicap Games", "equilíbrio pode dar interesse ao handicap"))
    itens = "".join(
        f'<div class="merc-linha"><span class="merc-bola">{bola}</span>'
        f'<span class="merc-nome">{nome}</span>'
        f'<span class="merc-nota">{_esc(nota)}</span></div>'
        for bola, nome, nota in linhas
    )
    return (f'<div class="card"><h3>Mercados a acompanhar</h3>{itens}'
            f'<div class="merc-aviso">Marcação de <b>interesse</b> para observação — '
            f'não indica valor nem sugere aposta. Só o Moneyline tem odds.</div></div>')


def _mod_veredicto(result):
    """Veredicto do Claude (quando existe)."""
    verd = result.get("verdict") or result.get("executive_summary")
    if not verd:
        return ""
    return f'<div class="veredicto"><h3>Leitura</h3><div>{_esc(verd)}</div></div>'


def _normalizar_div(raw):
    """Converte o output do _calcular_divergencia (chaves prob_mercado_a etc.)
    no formato que o V2 usa (market/indice_evidencia estruturados)."""
    if not raw:
        return None
    if raw.get("prob_mercado_a") is None:
        return {"market": None, "indice_evidencia": None,
                "classificacao": raw.get("classificacao"), "favorecido": raw.get("favorecido")}
    return {
        "market": {"a": raw["prob_mercado_a"], "b": raw["prob_mercado_b"]},
        "indice_evidencia": {"a": raw["indice_evidencia_a"], "b": raw["indice_evidencia_b"]},
        "classificacao": raw.get("classificacao"),
        "favorecido": raw.get("favorecido"),
        "tipo": raw.get("tipo"),
        "mercado_favorece": raw.get("mercado_favorece"),
        "indice_favorece": raw.get("indice_favorece"),
        "fatores_chave": raw.get("fatores_chave"),
    }


def build_report_html_v2(payload, result, calcular_divergencia_fn, mvm_fn=None):
    """Monta a página V2 completa. Recebe a função do motor (índice de
    evidência) de fora, para reaproveitar o report_html original.
    Arquitetura: Decisão -> explicação -> evidência -> detalhe."""
    a = _esc(payload.get("player_a", "?")); b = _esc(payload.get("player_b", "?"))
    # usar o wrapper (tem market/model/indice_evidencia estruturados) se dado,
    # senão o motor direto (e normalizamos as chaves)
    if mvm_fn is not None:
        div = mvm_fn(payload)
    else:
        raw = payload.get("divergencia") or calcular_divergencia_fn(payload)
        div = _normalizar_div(raw)
    estado = detetar_estado(payload, result, div)
    chave = estado[0]

    partes = ['<div class="wrap">']
    # 1. Header (sempre)
    partes.append(_mod_header(payload, div, estado))
    # 2. Leitura do jogo (sempre — muda conforme estado)
    partes.append(_mod_leitura(payload, div, estado, result))

    # ESTADO PARCIAL/ERRO: layout reduzido (auditoria #17)
    if chave == "erro":
        partes.append(f"""
<div class="parcial">
  <b>⚠️ Análise parcial</b> — odds indisponíveis e análise não gerada.
  Mostramos apenas os dados factuais abaixo, sem sinal nem veredicto.
</div>""")
        # só dados factuais, sem mercado/sinal/veredicto
        partes.append(f'<div class="grid2">{_mod_forma(payload)}{_mod_servico(payload)}</div>')
        partes.append(_mod_fadiga(payload))
        partes.append('</div>')
        return _pagina(a, b, "".join(partes))

    # 3. 4 fatores (se há divergência)
    if chave in ("acompanhar", "oportunidade"):
        partes.append(_mod_fatores(payload, div))
    # 4. Mercado vs Sinal (só com odds)
    if chave not in ("sem_odds",):
        partes.append(_mod_mercado_vs_sinal(payload, div))
        partes.append(_mod_mercados(payload, div))
    # 5-9. Evidência (grelha 2 colunas)
    partes.append(f'<div class="grid2">{_mod_forma(payload)}{_mod_servico(payload)}</div>')
    partes.append(_mod_fadiga(payload))
    partes.append(_mod_h2h(payload))
    partes.append(_mod_cenarios(payload))
    # Veredicto (se há)
    partes.append(_mod_veredicto(result))
    partes.append('</div>')
    return _pagina(a, b, "".join(partes))


def _pagina(a, b, corpo):
    hoje = datetime.now(timezone.utc).strftime("%d/%m/%Y")
    return f"""<!DOCTYPE html>
<html lang="pt"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{a} vs {b}</title>
<style>{_css()}</style></head>
<body>{corpo}
<div class="wrap"><div class="foot">Gerado em {hoje} · Pontos de observação para leitura pré-live e ao vivo — não são recomendações de aposta.</div></div>
</body></html>"""
