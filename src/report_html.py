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

try:  # também suporta tests/test_motor.py, que importa este módulo diretamente
    from .config import SITE_BASE_URL
except ImportError:  # pragma: no cover - caminho de compatibilidade legado
    from config import SITE_BASE_URL


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

    bsa = (payload.get("rich_stats_a") if isinstance(payload.get("rich_stats_a"), dict) else {}).get("by_surface") if isinstance((payload.get("rich_stats_a") if isinstance(payload.get("rich_stats_a"), dict) else {}).get("by_surface"), dict) else {}
    bsb = (payload.get("rich_stats_b") if isinstance(payload.get("rich_stats_b"), dict) else {}).get("by_surface") if isinstance((payload.get("rich_stats_b") if isinstance(payload.get("rich_stats_b"), dict) else {}).get("by_surface"), dict) else {}
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
        bla = (payload.get("rich_stats_a") if isinstance(payload.get("rich_stats_a"), dict) else {}).get("by_level") if isinstance((payload.get("rich_stats_a") if isinstance(payload.get("rich_stats_a"), dict) else {}).get("by_level"), dict) else {}
        blb = (payload.get("rich_stats_b") if isinstance(payload.get("rich_stats_b"), dict) else {}).get("by_level") if isinstance((payload.get("rich_stats_b") if isinstance(payload.get("rich_stats_b"), dict) else {}).get("by_level"), dict) else {}
        la, lb = bla.get(lkey), blb.get(lkey)
        if la and lb and la.get("matches") and lb.get("matches"):
            rows = [f"<b>Neste nível ({_esc(lnome)}):</b> "
                    f"{a} {la['win_pct']}% ({la['matches']} jogos) · "
                    f"{b} {lb['win_pct']}% ({lb['matches']} jogos)"]
            cards.append(_data_card("Desempenho por nível de torneio (carreira)", rows))

    # Fadiga
    fga, fgb = (payload.get("fatigue_signal_a") if isinstance(payload.get("fatigue_signal_a"), dict) else {}), (payload.get("fatigue_signal_b") if isinstance(payload.get("fatigue_signal_b"), dict) else {})
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
    sca = (payload.get("rich_stats_a") if isinstance(payload.get("rich_stats_a"), dict) else {}).get("scenarios") if isinstance((payload.get("rich_stats_a") if isinstance(payload.get("rich_stats_a"), dict) else {}).get("scenarios"), dict) else {}
    scb = (payload.get("rich_stats_b") if isinstance(payload.get("rich_stats_b"), dict) else {}).get("scenarios") if isinstance((payload.get("rich_stats_b") if isinstance(payload.get("rich_stats_b"), dict) else {}).get("scenarios"), dict) else {}
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
    sta = (payload.get("rich_stats_a") if isinstance(payload.get("rich_stats_a"), dict) else {}).get("style") if isinstance((payload.get("rich_stats_a") if isinstance(payload.get("rich_stats_a"), dict) else {}).get("style"), dict) else {}
    stb = (payload.get("rich_stats_b") if isinstance(payload.get("rich_stats_b"), dict) else {}).get("style") if isinstance((payload.get("rich_stats_b") if isinstance(payload.get("rich_stats_b"), dict) else {}).get("style"), dict) else {}
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
    doma = (payload.get("rich_stats_a") if isinstance(payload.get("rich_stats_a"), dict) else {}).get("domination") if isinstance((payload.get("rich_stats_a") if isinstance(payload.get("rich_stats_a"), dict) else {}).get("domination"), dict) else {}
    domb = (payload.get("rich_stats_b") if isinstance(payload.get("rich_stats_b"), dict) else {}).get("domination") if isinstance((payload.get("rich_stats_b") if isinstance(payload.get("rich_stats_b"), dict) else {}).get("domination"), dict) else {}
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
        resp_a = (payload.get("rich_stats_a") if isinstance(payload.get("rich_stats_a"), dict) else {}).get("response_stats") if isinstance((payload.get("rich_stats_a") if isinstance(payload.get("rich_stats_a"), dict) else {}).get("response_stats"), dict) else {}
        resp_b = (payload.get("rich_stats_b") if isinstance(payload.get("rich_stats_b"), dict) else {}).get("response_stats") if isinstance((payload.get("rich_stats_b") if isinstance(payload.get("rich_stats_b"), dict) else {}).get("response_stats"), dict) else {}
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
    ra = (payload.get("rich_stats_a") if isinstance(payload.get("rich_stats_a"), dict) else {}).get("vs_rank_level") if isinstance((payload.get("rich_stats_a") if isinstance(payload.get("rich_stats_a"), dict) else {}).get("vs_rank_level"), dict) else {}
    rb = (payload.get("rich_stats_b") if isinstance(payload.get("rich_stats_b"), dict) else {}).get("vs_rank_level") if isinstance((payload.get("rich_stats_b") if isinstance(payload.get("rich_stats_b"), dict) else {}).get("vs_rank_level"), dict) else {}
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
    "h2h_piso": 12,             # MUITO ALTO — confronto direto NESTE piso (mais específico que o global)
    "piso": 8,                 # ALTO — desce ligeiramente (10->8), partilha família com velocidade_piso
    "velocidade_piso": 10,     # ALTO — mais específico que "piso" (dentro do mesmo tipo, courts diferem em rapidez); cobertura parcial (14/08/2026, a pedido)
    "recuperacao_sets": 9,     # ALTO — recuperar 1 set abaixo / sets decisivos
    "qualidade_vitorias": 8,   # ALTO — vitórias vs top-10/20/50 nos últimos 90 dias (14/08/2026, a pedido)
    "matchup_maos": 8,         # ALTO quando envolve canhoto — MÉDIO-BAIXO (×0.3) se destro vs destro
    "forma_recente": 7,        # MÉDIO-ALTO — ritmo/confiança, janela de 45 dias (não 10 jogos)
    "sazonal": 6,              # MÉDIO — forma na mesma altura do ano, anos anteriores (14/08/2026, a pedido)
    "h2h": 6,                  # MÉDIO — confronto direto na carreira toda (o piso é mais relevante)
    "indoor_outdoor": 6,       # MÉDIO — performance no mesmo contexto (indoor/outdoor) do jogo de hoje (14/08/2026, a pedido)
    "ranking": 5,              # MÉDIO — conta, mas dá falsos positivos
    "ranking_evolucao": 6,     # MÉDIO — tendência de subida/descida em pontos, 6m/12m (14/08/2026, a pedido)
    "lesao": 5,                # MÉDIO — só ativa em regressos claros/longos
    "tiebreak": 5,             # MÉDIO — competência estreita, distinta de "sets decisivos" (14/08/2026, a pedido)
    "pressao_ronda": 6,        # MÉDIO — desempenho em rondas decisivas (QF+), carreira toda (18/08/2026, a pedido)
    "nivel_adversario": 7,     # MÉDIO-ALTO — desempenho vs nível do adversário de hoje, carreira toda (18/08/2026, a pedido)
    "comeback_set1": 7,        # MÉDIO-ALTO — recuperação após perder o 1º set, relevante para observação em live (14/08/2026, a pedido)
    "fadiga": 4,               # MÉDIO-BAIXO — sobe se último jogo foi longo
    "servico_recente": 5,      # MÉDIO — últimos 2 jogos (14/08/2026, a pedido)
    "servico_carreira": 3,     # MÉDIO-BAIXO — desceu (4->3), agora coexiste com a versão recente
    "meteo": 1,                # BAIXO — raramente decisiva
}

# Fatores correlacionados partilham um teto conjunto. Além de evitar dupla
# contagem no motor, estas constantes alimentam a área de transparência do
# relatório: o leitor consegue ver não só o peso-base, mas também o limite
# aplicado à família a que o fator pertence.
FAMILIAS_PESOS = {
    "forca_base": {"servico_recente", "servico_carreira", "forma_recente"},
    "matchup": {"matchup_maos", "h2h", "h2h_piso"},
    "superficie": {"piso", "velocidade_piso", "indoor_outdoor"},
    "resiliencia": {"recuperacao_sets", "tiebreak", "comeback_set1", "pressao_ronda"},
    "ranking_fam": {"ranking", "ranking_evolucao"},
    "contexto": {"fadiga", "lesao", "meteo"},
}
CAPS_FAMILIAS_PESOS = {
    "forca_base": 10, "matchup": 18, "superficie": 16,
    "resiliencia": 19, "ranking_fam": 9, "contexto": 6,
}

def _nome_fator(chave):
    return {
        "h2h": "confronto direto", "h2h_piso": "confronto direto (piso)",
        "piso": "superfície",
        "recuperacao_sets": "resiliência em sets", "matchup_maos": "matchup de mão",
        "forma_recente": "forma recente", "qualidade_vitorias": "qualidade de vitórias (90d)",
        "ranking": "ranking",
        "ranking_evolucao": "evolução de ranking",
        "lesao": "regresso após paragem", "fadiga": "fadiga",
        "servico_recente": "serviço (2 jogos)", "servico_carreira": "serviço (carreira)", "velocidade_piso": "velocidade do piso", "indoor_outdoor": "indoor/outdoor", "tiebreak": "tie-break", "pressao_ronda": "pressão de ronda decisiva", "nivel_adversario": "nível do adversário", "comeback_set1": "recuperação pós-1º set", "sazonal": "padrão sazonal", "meteo": "meteorologia",
    }.get(chave, chave)


def _calcular_divergencia(payload):
    """
    Núcleo do V3. Devolve:
    - indice_evidencia: distribuição ponderada dos sinais (0-100)
    - prob_mercado: probabilidade implícita do mercado (sem margem)
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
    componentes_peso = {}
    # ESTADO DE TODOS OS FATORES (11/08/2026) — para o módulo "Fatores
    # Detalhados" do relatório: ao contrário de `contribuicoes` (só os que
    # pesaram na decisão), isto regista TODOS os fatores aplicáveis, mesmo
    # os que não contribuíram (sem dados, empate, ou abaixo do limiar) —
    # 100% Python, o Claude nunca vê nem decide isto.
    status: dict = {}

    def _reg_status(chave, disponivel, lider=None, motivo_exclusao=None, **extra):
        entry = {"disponivel": disponivel, "lider": lider, "motivo_exclusao": motivo_exclusao}
        entry.update(extra)
        status[chave] = entry

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
        else:
            return
        componentes_peso[chave] = {
            "peso_base_configurado": round(float(PESOS.get(chave, 0)), 3),
            "peso_base_aplicado": round(float(base), 3),
            "multiplicador_forca": round(float(forca_rel), 3),
            "confianca_amostra": round(float(conf_amostra), 3),
            "peso_antes_cap": round(abs(float(peso)), 3),
        }

    # H2H NO PISO — peso mais alto do motor (auditoria 11/08/2026: dado que
    # já existia em compute_h2h [on_surface] mas nunca era usado por
    # ninguém). Mais específico que o global, por isso pesa mais.
    hp = feats.get("h2h_piso")
    if isinstance(hp, dict) and hp.get("lider") not in (None, "igual"):
        _hp_total = hp.get("a_wins", 0) + hp.get("b_wins", 0)
        if _hp_total >= 1:  # amostra por piso é sempre pequena; 1 jogo já conta, com confiança baixa
            forca = min(_hp_total / 3.0, 1.0)
            _add("h2h_piso", hp["lider"], max(forca, 0.5), conf_amostra=_conf_amostra(_hp_total, 6))
            _reg_status("h2h_piso", True, hp["lider"], valor_a=hp.get("a_wins"), valor_b=hp.get("b_wins"), amostra=_hp_total)
        else:
            _reg_status("h2h_piso", True, "igual", "amostra insuficiente")
    elif isinstance(hp, dict) and hp.get("lider") == "igual":
        _reg_status("h2h_piso", True, "igual")
    else:
        _reg_status("h2h_piso", False)

    # H2H global — só conta com amostra mínima (1 jogo não é evidência
    # fiável) e com força proporcional ao domínio do confronto.
    h = feats.get("h2h")
    if isinstance(h, dict) and h.get("lider") not in (None, "igual"):
        _h_total = (h.get("a_wins", 0) + h.get("b_wins", 0)) or h.get("diff", 0)
        if _h_total >= 2:  # ignora H2H de 1 só jogo
            forca = min(_h_total / 4.0, 1.0)  # 4+ jogos = peso total
            _add("h2h", h["lider"], max(forca, 0.5))
            _reg_status("h2h", True, h["lider"], valor_a=h.get("a_wins"), valor_b=h.get("b_wins"), amostra=_h_total)
        else:
            _reg_status("h2h", True, h["lider"], "amostra insuficiente (1 jogo)")
    elif isinstance(h, dict) and h.get("lider") == "igual":
        _reg_status("h2h", True, "igual")
    else:
        _reg_status("h2h", False)

    # Piso — com confiança de amostra (auditoria: 8 jogos não pesa como 300)
    # CORREÇÃO (12/08/2026, feedback de teste): faltava o limiar mínimo que
    # os outros fatores percentuais já tinham — 51% vs 49% contava como
    # "vantagem" (força pequena, mas ainda assim contribuía e aparecia como
    # ▲ nos Fatores Detalhados). Alinhado com o mesmo limiar de 3 p.p. já
    # usado em recuperação de sets / matchup de mão.
    ps = feats.get("piso")
    if isinstance(ps, dict) and ps.get("lider") not in (None, "igual") and abs(ps.get("diff") or 0) >= 3:
        forca = min((ps.get("diff") or 5) / 15.0, 1.0)
        # amostra: nº de jogos no piso (o menor dos dois jogadores, conservador)
        _n_piso = min(ps.get("amostra_a") or 0, ps.get("amostra_b") or 0) or ps.get("amostra") or 0
        _add("piso", ps["lider"], max(forca, 0.4), conf_amostra=_conf_amostra(_n_piso, 40))
        _reg_status("piso", True, ps["lider"], valor_a=ps.get("valor_a"), valor_b=ps.get("valor_b"), amostra=_n_piso)
    elif isinstance(ps, dict) and ps.get("lider") == "igual":
        _reg_status("piso", True, "igual", valor_a=ps.get("valor_a"), valor_b=ps.get("valor_b"))
    elif isinstance(ps, dict) and ps.get("lider") is not None:
        _reg_status("piso", True, ps["lider"], "abaixo do limiar (<3 p.p.)",
                    valor_a=ps.get("valor_a"), valor_b=ps.get("valor_b"))
    else:
        _reg_status("piso", False)

    # Recuperação de sets — set decisivo (auditoria 11/08/2026: o motor só
    # lia rich_stats.scenarios, que vem dum endpoint com ORÇAMENTO LIMITADO
    # por execução e cache local — frequentemente indisponível. Ignorava
    # `deciding_set_stats_a/b`, uma fonte separada e muito mais disponível
    # (RapidAPI recent-stats, com fallback Sackmann/histórico). Adicionado
    # fallback: se o "rich" não tiver o dado, tenta a outra fonte — que tem
    # DUAS formas possíveis (plana da RapidAPI, ou bo3/bo5 do histórico),
    # por isso a extração trata as duas.
    def _deciding_set_signal(d):
        """Devolve (win_pct, contagem) de set decisivo, aceitando tanto a
        forma plana (RapidAPI recent-stats: deciding_set_win_pct/_count)
        como a forma bo3/bo5 (Sackmann/histórico: combina as duas)."""
        if not isinstance(d, dict):
            return None, None
        if d.get("deciding_set_win_pct") is not None:
            return d["deciding_set_win_pct"], d.get("deciding_set_count")
        wins = matches = 0
        tem_dados = False
        for label in ("bo3", "bo5"):
            cell = d.get(label)
            if isinstance(cell, dict) and cell.get("matches_went_the_distance"):
                tem_dados = True
                matches += cell["matches_went_the_distance"]
                wins += cell.get("wins", 0)
        if not tem_dados or matches == 0:
            return None, None
        return round(100 * wins / matches, 1), matches

    ra = (payload.get("rich_stats_a") if isinstance(payload.get("rich_stats_a"), dict) else {}).get("scenarios") if isinstance((payload.get("rich_stats_a") if isinstance(payload.get("rich_stats_a"), dict) else {}).get("scenarios"), dict) else {}
    rb = (payload.get("rich_stats_b") if isinstance(payload.get("rich_stats_b"), dict) else {}).get("scenarios") if isinstance((payload.get("rich_stats_b") if isinstance(payload.get("rich_stats_b"), dict) else {}).get("scenarios"), dict) else {}
    dec_a, dec_a_n = ra.get("deciding_set_win_pct"), ra.get("deciding_set_count")
    dec_b, dec_b_n = rb.get("deciding_set_win_pct"), rb.get("deciding_set_count")
    if dec_a is None:
        dec_a, dec_a_n = _deciding_set_signal(payload.get("deciding_set_stats_a"))
    if dec_b is None:
        dec_b, dec_b_n = _deciding_set_signal(payload.get("deciding_set_stats_b"))
    if dec_a is not None and dec_b is not None:
        lider = a if dec_a > dec_b else (b if dec_b > dec_a else "igual")
        if lider != "igual" and abs(dec_a - dec_b) >= 3:
            forca = min(abs(dec_a - dec_b) / 15.0, 1.0)
            _n_dec = min(dec_a_n or 0, dec_b_n or 0)
            _add("recuperacao_sets", lider, max(forca, 0.4), conf_amostra=_conf_amostra(_n_dec, 20))
            _reg_status("recuperacao_sets", True, lider, valor_a=dec_a, valor_b=dec_b, amostra=_n_dec)
        else:
            _reg_status("recuperacao_sets", True, lider, "diferença irrelevante" if lider == "igual" else "abaixo do limiar (<3 p.p.)")
    else:
        _reg_status("recuperacao_sets", False)

    # Matchup de mão (handedness)
    # CORREÇÃO (14/08/2026, a pedido): confrontos destro-vs-destro (a
    # maioria) não são estilisticamente distintivos — o peso a sério deve
    # reservar-se para quando há um canhoto envolvido (padrão real). O
    # opponent_hand já vem guardado em resolve_handedness_matchup.
    hm = payload.get("handedness_matchup_a") or {}
    hmb = payload.get("handedness_matchup_b") or {}
    wa = hm.get("win_pct"); wb = hmb.get("win_pct")
    _op_hand_b = hm.get("opponent_hand")   # mão de B, vista do lado de A
    _op_hand_a = hmb.get("opponent_hand")  # mão de A, vista do lado de B
    _envolve_canhoto = "L" in (_op_hand_a, _op_hand_b)
    _peso_mao = PESOS["matchup_maos"] if _envolve_canhoto else round(PESOS["matchup_maos"] * 0.3, 1)
    if wa is not None and wb is not None:
        lider = a if wa > wb else (b if wb > wa else "igual")
        if lider != "igual" and abs(wa - wb) >= 3:
            forca = min(abs(wa - wb) / 15.0, 1.0)
            _add("matchup_maos", lider, max(forca, 0.4), peso_override=_peso_mao)
            _reg_status("matchup_maos", True, lider, valor_a=wa, valor_b=wb)
        else:
            _reg_status("matchup_maos", True, lider, "diferença irrelevante" if lider == "igual" else "abaixo do limiar (<3 p.p.)")
    else:
        _reg_status("matchup_maos", False)

    # Forma recente
    # CORREÇÃO (12/08/2026): mesmo limiar de 3 p.p. (ver nota do piso acima).
    fr = feats.get("forma_recente")
    if isinstance(fr, dict) and fr.get("lider") not in (None, "igual") and abs(fr.get("diff") or 0) >= 3:
        forca = min((fr.get("diff") or 10) / 25.0, 1.0)
        _add("forma_recente", fr["lider"], max(forca, 0.4))
        _reg_status("forma_recente", True, fr["lider"], valor_a=fr.get("valor_a"), valor_b=fr.get("valor_b"), amostra=fr.get("amostra_a"))
    elif isinstance(fr, dict) and fr.get("lider") == "igual":
        _reg_status("forma_recente", True, "igual", valor_a=fr.get("valor_a"), valor_b=fr.get("valor_b"))
    elif isinstance(fr, dict) and fr.get("lider") is not None:
        _reg_status("forma_recente", True, fr["lider"], "abaixo do limiar (<3 p.p.)",
                    valor_a=fr.get("valor_a"), valor_b=fr.get("valor_b"))
    else:
        _reg_status("forma_recente", False)

    # NOVO (14/08/2026, a pedido): qualidade das vitórias recentes (vs
    # top-10/20/50 nos últimos 90 dias) — capta um jogador "em explosão"
    # que a forma recente (win/loss simples) não mostra bem (ex: caso
    # real discutido: indicadores gerais favoreciam um lado, mas o outro
    # vinha de bater vários top-20 recentemente).
    qv = feats.get("qualidade_vitorias")
    if isinstance(qv, dict) and qv.get("lider") not in (None, "igual"):
        _sa, _sb = qv.get("valor_a", 0), qv.get("valor_b", 0)
        forca = min(abs(_sa - _sb) / 4.0, 1.0)
        _n_qv = min(
            (payload.get("recent_quality_a") or {}).get("matches") or 0,
            (payload.get("recent_quality_b") or {}).get("matches") or 0,
        )
        _add("qualidade_vitorias", qv["lider"], max(forca, 0.4), conf_amostra=_conf_amostra(_n_qv, 8))
        _reg_status("qualidade_vitorias", True, qv["lider"], valor_a=_sa, valor_b=_sb)
    elif isinstance(qv, dict) and qv.get("lider") == "igual":
        _reg_status("qualidade_vitorias", True, "igual", valor_a=qv.get("valor_a"), valor_b=qv.get("valor_b"))
    else:
        _reg_status("qualidade_vitorias", False)

    # Ranking — só conta se a diferença for RELEVANTE. Um limiar fixo de
    # POSIÇÕES falha nos extremos do ranking: #1 vs #5 (diferença de 4
    # posições, "irrelevante" pelo limiar antigo) é uma queda de qualidade
    # brutal em pontos reais; #200 vs #204 (mesma diferença de posições) é
    # insignificante. CORREÇÃO (12/08/2026, feedback de teste): usa também
    # a diferença RELATIVA de pontos como critério alternativo — conta se a
    # posição OU os pontos indicarem uma diferença real.
    rk = feats.get("ranking")
    if isinstance(rk, dict) and rk.get("lider") not in (None, "igual"):
        _rk_diff = rk.get("diff", 0)
        _pts_a, _pts_b = rk.get("pontos_a"), rk.get("pontos_b")
        _pts_gap_rel = None
        if _pts_a and _pts_b and max(_pts_a, _pts_b) > 0:
            _pts_gap_rel = abs(_pts_a - _pts_b) / max(_pts_a, _pts_b) * 100
        _relevante = _rk_diff >= 5 or (_pts_gap_rel is not None and _pts_gap_rel >= 15)
        if _relevante:
            forca = min(_rk_diff / 50.0, 1.0)
            if _pts_gap_rel is not None:
                # a força também pode vir dos pontos (ex: #1 vs #5 com gap de
                # pontos enorme, mas diferença de posições pequena)
                forca = max(forca, min(_pts_gap_rel / 40.0, 1.0))
            _add("ranking", rk["lider"], max(forca, 0.3))
            _reg_status("ranking", True, rk["lider"], valor_a=rk.get("valor_a"), valor_b=rk.get("valor_b"),
                        pontos_a=_pts_a, pontos_b=_pts_b)
        else:
            _reg_status("ranking", True, rk["lider"], "diferença irrelevante (posições e pontos próximos)",
                        valor_a=rk.get("valor_a"), valor_b=rk.get("valor_b"))
    elif isinstance(rk, dict) and rk.get("lider") == "igual":
        _reg_status("ranking", True, "igual")
    else:
        _reg_status("ranking", False)

    # NOVO (14/08/2026, a pedido): evolução de ranking — escala diferente
    # dos outros fatores (variação % relativa, não 0-100), por isso usa o
    # seu próprio limiar (15, não 3) e escala de força (÷60, não ÷15).
    re_ = feats.get("ranking_evolucao")
    if isinstance(re_, dict) and re_.get("lider") not in (None, "igual") and abs(re_.get("diff") or 0) >= 15:
        forca = min(abs(re_.get("diff") or 0) / 60.0, 1.0)
        _add("ranking_evolucao", re_["lider"], max(forca, 0.4))
        _reg_status("ranking_evolucao", True, re_["lider"], valor_a=re_.get("valor_a"), valor_b=re_.get("valor_b"))
    elif isinstance(re_, dict) and re_.get("lider") == "igual":
        _reg_status("ranking_evolucao", True, "igual", valor_a=re_.get("valor_a"), valor_b=re_.get("valor_b"))
    elif isinstance(re_, dict) and re_.get("lider") is not None:
        _reg_status("ranking_evolucao", True, re_["lider"], "abaixo do limiar (<15 p.p. de variação)",
                    valor_a=re_.get("valor_a"), valor_b=re_.get("valor_b"))
    else:
        _reg_status("ranking_evolucao", False)

    # REMOVIDO (14/08/2026, a pedido): "época atual" ficou redundante como
    # fator do motor (ver nota em main.py, mesma alteração).

    # NOVO (14/08/2026, a pedido): indoor vs outdoor — mesmo limiar de 3 p.p.
    io = feats.get("indoor_outdoor")
    if isinstance(io, dict) and io.get("lider") not in (None, "igual") and abs(io.get("diff") or 0) >= 3:
        _add("indoor_outdoor", io["lider"])
        _reg_status("indoor_outdoor", True, io["lider"], valor_a=io.get("valor_a"), valor_b=io.get("valor_b"))
    elif isinstance(io, dict) and io.get("lider") == "igual":
        _reg_status("indoor_outdoor", True, "igual", valor_a=io.get("valor_a"), valor_b=io.get("valor_b"))
    elif isinstance(io, dict) and io.get("lider") is not None:
        _reg_status("indoor_outdoor", True, io["lider"], "abaixo do limiar (<3 p.p.)",
                    valor_a=io.get("valor_a"), valor_b=io.get("valor_b"))
    else:
        _reg_status("indoor_outdoor", False)

    # NOVO (14/08/2026, a pedido): velocidade do piso — mesmo limiar de
    # 3 p.p. Cobertura limitada (só Slams/Masters1000/ATP Finals) — "sem
    # dados" é o resultado esperado na maioria dos jogos, por desenho.
    vp = feats.get("velocidade_piso")
    if isinstance(vp, dict) and vp.get("lider") not in (None, "igual") and abs(vp.get("diff") or 0) >= 3:
        _add("velocidade_piso", vp["lider"])
        _reg_status("velocidade_piso", True, vp["lider"], valor_a=vp.get("valor_a"), valor_b=vp.get("valor_b"))
    elif isinstance(vp, dict) and vp.get("lider") == "igual":
        _reg_status("velocidade_piso", True, "igual", valor_a=vp.get("valor_a"), valor_b=vp.get("valor_b"))
    elif isinstance(vp, dict) and vp.get("lider") is not None:
        _reg_status("velocidade_piso", True, vp["lider"], "abaixo do limiar (<3 p.p.)",
                    valor_a=vp.get("valor_a"), valor_b=vp.get("valor_b"))
    else:
        _reg_status("velocidade_piso", False)

    # NOVO (14/08/2026, a pedido): tie-break — mesmo limiar de 3 p.p.
    tb = feats.get("tiebreak")
    if isinstance(tb, dict) and tb.get("lider") not in (None, "igual") and abs(tb.get("diff") or 0) >= 3:
        _add("tiebreak", tb["lider"])
        _reg_status("tiebreak", True, tb["lider"], valor_a=tb.get("valor_a"), valor_b=tb.get("valor_b"))
    elif isinstance(tb, dict) and tb.get("lider") == "igual":
        _reg_status("tiebreak", True, "igual", valor_a=tb.get("valor_a"), valor_b=tb.get("valor_b"))
    elif isinstance(tb, dict) and tb.get("lider") is not None:
        _reg_status("tiebreak", True, tb["lider"], "abaixo do limiar (<3 p.p.)",
                    valor_a=tb.get("valor_a"), valor_b=tb.get("valor_b"))
    else:
        _reg_status("tiebreak", False)

    # NOVO (18/08/2026, a pedido): pressão de ronda decisiva — mesmo
    # limiar de 3 p.p. já usado nos outros fatores percentuais.
    pr = feats.get("pressao_ronda")
    if isinstance(pr, dict) and pr.get("lider") not in (None, "igual") and abs(pr.get("diff") or 0) >= 3:
        _add("pressao_ronda", pr["lider"])
        _reg_status("pressao_ronda", True, pr["lider"], valor_a=pr.get("valor_a"), valor_b=pr.get("valor_b"))
    elif isinstance(pr, dict) and pr.get("lider") == "igual":
        _reg_status("pressao_ronda", True, "igual", valor_a=pr.get("valor_a"), valor_b=pr.get("valor_b"))
    elif isinstance(pr, dict) and pr.get("lider") is not None:
        _reg_status("pressao_ronda", True, pr["lider"], "abaixo do limiar (<3 p.p.)",
                    valor_a=pr.get("valor_a"), valor_b=pr.get("valor_b"))
    else:
        _reg_status("pressao_ronda", False)

    # NOVO (18/08/2026, a pedido): desempenho vs nível do adversário de hoje
    nv = feats.get("nivel_adversario")
    if isinstance(nv, dict) and nv.get("lider") not in (None, "igual") and abs(nv.get("diff") or 0) >= 3:
        _add("nivel_adversario", nv["lider"])
        _reg_status("nivel_adversario", True, nv["lider"], valor_a=nv.get("valor_a"), valor_b=nv.get("valor_b"))
    elif isinstance(nv, dict) and nv.get("lider") == "igual":
        _reg_status("nivel_adversario", True, "igual", valor_a=nv.get("valor_a"), valor_b=nv.get("valor_b"))
    elif isinstance(nv, dict) and nv.get("lider") is not None:
        _reg_status("nivel_adversario", True, nv["lider"], "abaixo do limiar (<3 p.p.)",
                    valor_a=nv.get("valor_a"), valor_b=nv.get("valor_b"))
    else:
        _reg_status("nivel_adversario", False)

    # NOVO (14/08/2026, a pedido): recuperação após perder o 1º set —
    # mesmo limiar de 3 p.p. Sinal relevante sobretudo para observação em
    # live (favorito que recupera bem quando começa a perder).
    cb = feats.get("comeback_set1")
    if isinstance(cb, dict) and cb.get("lider") not in (None, "igual") and abs(cb.get("diff") or 0) >= 3:
        _add("comeback_set1", cb["lider"])
        _reg_status("comeback_set1", True, cb["lider"], valor_a=cb.get("valor_a"), valor_b=cb.get("valor_b"))
    elif isinstance(cb, dict) and cb.get("lider") == "igual":
        _reg_status("comeback_set1", True, "igual", valor_a=cb.get("valor_a"), valor_b=cb.get("valor_b"))
    elif isinstance(cb, dict) and cb.get("lider") is not None:
        _reg_status("comeback_set1", True, cb["lider"], "abaixo do limiar (<3 p.p.)",
                    valor_a=cb.get("valor_a"), valor_b=cb.get("valor_b"))
    else:
        _reg_status("comeback_set1", False)

    # NOVO (14/08/2026, a pedido): padrão sazonal — mesmo limiar de 3 p.p.
    saz = feats.get("sazonal")
    if isinstance(saz, dict) and saz.get("lider") not in (None, "igual") and abs(saz.get("diff") or 0) >= 3:
        _add("sazonal", saz["lider"])
        _reg_status("sazonal", True, saz["lider"], valor_a=saz.get("valor_a"), valor_b=saz.get("valor_b"))
    elif isinstance(saz, dict) and saz.get("lider") == "igual":
        _reg_status("sazonal", True, "igual", valor_a=saz.get("valor_a"), valor_b=saz.get("valor_b"))
    elif isinstance(saz, dict) and saz.get("lider") is not None:
        _reg_status("sazonal", True, saz["lider"], "abaixo do limiar (<3 p.p.)",
                    valor_a=saz.get("valor_a"), valor_b=saz.get("valor_b"))
    else:
        _reg_status("sazonal", False)

    # Serviço — CARREIRA e RECENTE como fatores separados, pesos diferentes
    # (14/08/2026, a pedido; ver nota em main.py).
    # CORREÇÃO (12/08/2026): mesmo limiar de 3 p.p.
    sv = feats.get("servico_carreira")
    if isinstance(sv, dict) and sv.get("lider") not in (None, "igual") and abs(sv.get("diff") or 0) >= 3:
        _add("servico_carreira", sv["lider"])
        _reg_status("servico_carreira", True, sv["lider"], valor_a=sv.get("valor_a"), valor_b=sv.get("valor_b"))
    elif isinstance(sv, dict) and sv.get("lider") == "igual":
        _reg_status("servico_carreira", True, "igual", valor_a=sv.get("valor_a"), valor_b=sv.get("valor_b"))
    elif isinstance(sv, dict) and sv.get("lider") is not None:
        _reg_status("servico_carreira", True, sv["lider"], "abaixo do limiar (<3 p.p.)",
                    valor_a=sv.get("valor_a"), valor_b=sv.get("valor_b"))
    else:
        _reg_status("servico_carreira", False)

    svr = feats.get("servico_recente")
    if isinstance(svr, dict) and svr.get("lider") not in (None, "igual") and abs(svr.get("diff") or 0) >= 3:
        _add("servico_recente", svr["lider"])
        _reg_status("servico_recente", True, svr["lider"], valor_a=svr.get("valor_a"), valor_b=svr.get("valor_b"))
    elif isinstance(svr, dict) and svr.get("lider") == "igual":
        _reg_status("servico_recente", True, "igual", valor_a=svr.get("valor_a"), valor_b=svr.get("valor_b"))
    elif isinstance(svr, dict) and svr.get("lider") is not None:
        _reg_status("servico_recente", True, svr["lider"], "abaixo do limiar (<3 p.p.)",
                    valor_a=svr.get("valor_a"), valor_b=svr.get("valor_b"))
    else:
        _reg_status("servico_recente", False)

    # Fadiga (sobe se último jogo foi longo)
    fa = (payload.get("fatigue_signal_a") if isinstance(payload.get("fatigue_signal_a"), dict) else {})
    fb = (payload.get("fatigue_signal_b") if isinstance(payload.get("fatigue_signal_b"), dict) else {})
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
            _reg_status("fadiga", True, lider, valor_a=ja, valor_b=jb)
        else:
            _reg_status("fadiga", True, "igual" if ja == jb else None, "sem diferença nos jogos recentes")
    else:
        _reg_status("fadiga", False, motivo_exclusao="fonte não fiável (histórico, não api_recent)")

    # Lesão (só ativa em regresso claro/longo)
    # CORREÇÃO (11/08/2026): lia layoff_return_stats.days_out, que só existe
    # na variante RapidAPI (compute_layoff_from_past_matches). No fallback
    # histórico (compute_return_from_layoff_stats), esse dict mede outra
    # coisa (taxa de vitória histórica após regressos — win_rate_pct) e
    # NUNCA teve "days_out": o fator ficava sempre a zero nesse caminho,
    # silenciosamente. days_since_last_match do sinal de FADIGA existe de
    # forma consistente nas duas fontes (api_recent e histórico) — é a
    # medida certa e sempre disponível de "quanto tempo parado até agora".
    def _regresso_claro(f):
        return (f.get("days_since_last_match") or 0) >= 60  # 2+ meses parado
    # quem regressa de lesão longa fica em desvantagem
    if _regresso_claro(fa) and not _regresso_claro(fb):
        _add("lesao", b)  # B beneficia (A está a regressar)
        _reg_status("lesao", True, b, valor_a=fa.get("days_since_last_match"), valor_b=fb.get("days_since_last_match"))
    elif _regresso_claro(fb) and not _regresso_claro(fa):
        _add("lesao", a)
        _reg_status("lesao", True, a, valor_a=fa.get("days_since_last_match"), valor_b=fb.get("days_since_last_match"))
    elif fa.get("days_since_last_match") is not None or fb.get("days_since_last_match") is not None:
        _reg_status("lesao", True, "igual", "nenhum em regresso claro (<60 dias parado)",
                   valor_a=fa.get("days_since_last_match"), valor_b=fb.get("days_since_last_match"))
    else:
        _reg_status("lesao", False)

    # Meteorologia (peso mínimo — só entra como desempate simbólico, quase nulo)
    # (não implementado como vantagem direcional; fica como contexto)

    # --- 1.5. CAP POR FAMÍLIA (auditoria P1 — evitar double counting) ---
    # ranking+época+serviço+forma medem em parte a mesma coisa ("qualidade
    # geral"). Somá-los como independentes conta a mesma variável várias vezes.
    # Agrupamos em famílias e limitamos a contribuição de cada família a um
    # teto, para que medir a qualidade de 4 formas não a inflacione 4x.
    def _familia(chave):
        for fam, membros in FAMILIAS_PESOS.items():
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
        cap = CAPS_FAMILIAS_PESOS.get(fam, 10)
        if soma_peso > cap and soma_peso > 0:
            # reduzir proporcionalmente todos os fatores da família
            escala = cap / soma_peso
            items = [(c, s, p * escala) for c, s, p in items]
        contribuicoes_capadas.extend(items)
    contribuicoes = contribuicoes_capadas
    # Guardar no estado de cada fator o impacto efetivo usado pelo motor,
    # depois dos ajustes de forca, confianca da amostra e caps por familia.
    # O relatorio usa estes valores no modo "Impacto no matchup".
    for chave_f, st in status.items():
        st["peso_base_configurado"] = PESOS.get(chave_f, 0)
        if chave_f in componentes_peso:
            st.update(componentes_peso[chave_f])
            st["familia_peso"] = _familia(chave_f)
    for chave_f, sinal, peso in contribuicoes:
        if chave_f in status:
            status[chave_f]["peso_efetivo"] = round(abs(peso), 3)
            status[chave_f]["direcao_impacto"] = "a" if sinal > 0 else "b"

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

    # --- 4. Direção e intensidade (escalas mantidas separadas) ---
    # O índice mede a quota de peso dos sinais; o mercado exprime probabilidade
    # implícita. Como as escalas não são equivalentes, nunca se subtraem nem se
    # usam "p.p." entre ambas. Só existe divergência quando apontam para lados
    # opostos. Quando concordam, registamos também a intensidade interna para
    # não perder alinhamentos fortes — sem a converter em probabilidade, odd
    # justa ou valor de mercado.
    mercado_favorece = a if prob_mercado_a >= 50 else b
    indice_favorece = a if indice_evidencia_a >= 50 else b
    forca_indice = abs(indice_evidencia_a - 50)  # força interna dos sinais, 0-50
    intensidade_nivel = (0 if forca_indice < 5 else
                          1 if forca_indice < 10 else
                          2 if forca_indice < 25 else 3)
    intensidade_chave = ("neutra", "ligeira", "moderada", "forte")[intensidade_nivel]
    tipo = "inconclusivo" if intensidade_nivel == 0 else "alinhamento"
    if indice_favorece != mercado_favorece:
        # A severidade depende apenas da concentração dos sinais. A força do
        # mercado continua visível nas odds, mas não é misturada nesta escala.
        tipo = "direcao"
        if forca_indice < 10:
            nivel = 1
        elif forca_indice < 25:
            nivel = 2
        else:
            nivel = 3
    else:
        # Concordância direcional não prova preço incorreto nem subvalorização.
        nivel = 0

    # SALVAGUARDA DE CONFIANÇA (contra falsos positivos): a divergência só pode
    # ser "forte"/"moderada" se houver massa de evidência e fatores suficientes.
    massa_evidencia = peso_total
    n_fatores = len([c for c in contribuicoes if abs(c[2]) > 0])
    if massa_evidencia < 8 or n_fatores < 2:
        nivel = min(nivel, 1)
        intensidade_nivel = min(intensidade_nivel, 1)
    elif massa_evidencia < 18 or n_fatores < 3:
        nivel = min(nivel, 2)
        intensidade_nivel = min(intensidade_nivel, 2)
    intensidade_chave = ("neutra", "ligeira", "moderada", "forte")[intensidade_nivel]
    if tipo != "direcao":
        tipo = "inconclusivo" if intensidade_nivel == 0 else "alinhamento"
    _mapa = {0: (("inconclusivo", "Indicadores inconclusivos")
                 if tipo == "inconclusivo" else
                 (f"alinhamento_{intensidade_chave}", f"Alinhamento {intensidade_chave}")),
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
        "tipo": tipo,  # "direcao" | "alinhamento" | "inconclusivo"
        "intensidade_indicadores": intensidade_chave,
        "intensidade_nivel": intensidade_nivel,
        "forca_indice": forca_indice,
        "favorecido": favorecido,
        "fatores_chave": fatores_chave,
        "n_fatores": n_fatores,  # nº de sinais que contribuíram (transparência
                                  # quando o índice bate no extremo com poucos)
        "fatores_status": status,  # TODOS os fatores (não só o top-3), para o
                                    # módulo "Fatores Detalhados" — 100% Python
        "gap_pp": None,  # compatibilidade: escalas distintas, não subtrair
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
    ra = (payload.get("rich_stats_a") if isinstance(payload.get("rich_stats_a"), dict) else {}).get("scenarios") if isinstance((payload.get("rich_stats_a") if isinstance(payload.get("rich_stats_a"), dict) else {}).get("scenarios"), dict) else {}
    rb = (payload.get("rich_stats_b") if isinstance(payload.get("rich_stats_b"), dict) else {}).get("scenarios") if isinstance((payload.get("rich_stats_b") if isinstance(payload.get("rich_stats_b"), dict) else {}).get("scenarios"), dict) else {}
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
    fa = (payload.get("fatigue_signal_a") if isinstance(payload.get("fatigue_signal_a"), dict) else {})
    fb = (payload.get("fatigue_signal_b") if isinstance(payload.get("fatigue_signal_b"), dict) else {})
    if (fa.get("matches_last_7d") in (0, None)) and (fb.get("matches_last_7d") in (0, None)):
        pts.append("Sem sinais de fadiga recente.")
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
            ("Fadiga real (jogos recentes)", ((payload.get("fatigue_signal_a") if isinstance(payload.get("fatigue_signal_a"), dict) else {})).get("fatigue_source") == "api_recent"),
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
def _d(v):
    """Garante que o valor é um dict. Blinda os módulos V2 contra campos que
    venham como string, None ou outro tipo (evita 'str has no attribute get').
    Todos os módulos usam _d(payload.get("x")) em vez de _d(payload.get("x")).
    """
    return v if isinstance(v, dict) else {}


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
    "bg": "#071426", "surface": "#0d2038", "surface2": "#122a47",
    "text": "#f4f7fb", "dim": "#91a5bc", "line": "#23415f",
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
      - 'inconclusivo': indicadores sem direção clara
      - 'alinhado': mercado e indicadores concordam
      - 'alinhado_forte': concordância com sinais internos fortes
      - 'acompanhar': divergência ligeira/moderada
      - 'oportunidade': divergência forte
    """
    tem_odds = bool(divergencia and divergencia.get("market"))
    analise_falhou = bool(result.get("analysis_error") or result.get("llm_error"))
    if analise_falhou and not tem_odds:
        return ("erro", COLORS_V2["error"], "Análise parcial", "⚠️")
    if not tem_odds:
        return ("sem_odds", COLORS_V2["neutral"], "Sem odds — comparação indisponível", "⚪")
    nivel = (_d(divergencia.get("classificacao"))).get("nivel", 0)
    tipo = divergencia.get("tipo", "")
    if tipo == "inconclusivo":
        return ("inconclusivo", COLORS_V2["neutral"], "Indicadores inconclusivos", "⚪")
    if tipo != "direcao":
        intensidade = divergencia.get("intensidade_nivel", 1)
        if intensidade >= 3:
            return ("alinhado_forte", COLORS_V2["amber"], "Alinhamento forte", "🔵")
        return ("alinhado", COLORS_V2["neutral"],
                f"Alinhamento {divergencia.get('intensidade_indicadores', 'ligeiro')}", "⚪")
    if nivel >= 3:
        lbl = "Divergência forte"
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
.report-nav {{ max-width:1080px; margin:0 auto 10px; }}
.report-nav a {{ color:var(--dim); text-decoration:none; font-size:14px; }}
.report-nav a:hover, .report-nav a:focus {{ color:var(--text); text-decoration:underline; }}
.sr-only {{ position:absolute; width:1px; height:1px; padding:0; margin:-1px;
  overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }}
.num {{ font-variant-numeric:tabular-nums; }}

/* --- MATCHUP HEADER (ficha de combate) --- */
.mh {{ background:var(--surface); border:1px solid var(--line); border-radius:14px;
  padding:20px; margin-bottom:14px; }}
.mh-top {{ display:grid; grid-template-columns:1fr auto 1fr; gap:12px; align-items:start; }}
.mh-player {{ display:flex; align-items:center; gap:12px; min-width:0; }}
.mh-player.b {{ flex-direction:row-reverse; }}
.mh-player-photo {{ width:76px; height:76px; flex:0 0 76px; border-radius:50%;
  object-fit:cover; object-position:center 22%; border:2px solid var(--a);
  background:var(--surface2); box-shadow:0 5px 18px rgba(0,0,0,.28); }}
.mh-player.b .mh-player-photo {{ border-color:var(--b); }}
.mh-player-avatar {{ display:grid; place-items:center; color:var(--a); font-size:20px;
  font-weight:800; letter-spacing:.5px; }}
.mh-player.b .mh-player-avatar {{ color:var(--b); }}
.mh-player-info {{ min-width:0; flex:1; }}
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
.mh-odds-meta {{ color:var(--dim); font-size:10px; text-align:center; margin-top:7px; }}
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
.odds-range {{ background:var(--surface); border:1px solid var(--line); border-radius:12px;
  padding:16px 18px; margin:-4px 0 14px; }}
.odds-range h3 {{ font-size:12px; text-transform:uppercase; letter-spacing:1px;
  color:var(--dim); margin-bottom:11px; font-weight:600; }}
.odds-range-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:10px; }}
.odds-range-player {{ background:var(--surface2); border-radius:9px; padding:11px 12px; }}
.odds-range-player.b {{ text-align:right; }}
.odds-range-name {{ color:var(--dim); font-size:11px; }}
.odds-range-value {{ font-size:18px; font-weight:750; margin:2px 0; }}
.odds-range-read {{ color:var(--dim); font-size:10px; }}
.odds-range-note {{ color:var(--dim); font-size:10px; margin-top:9px; }}
.data-quality {{ margin:12px 0 16px; padding:12px 14px; border:1px solid rgba(217,164,65,.45);
  border-left:3px solid var(--amber); border-radius:10px; background:rgba(217,164,65,.07); }}
.data-quality-title {{ color:var(--amber); font-size:11px; font-weight:750; text-transform:uppercase;
  letter-spacing:.65px; margin-bottom:5px; }}
.data-quality ul {{ padding-left:17px; color:var(--text); font-size:11px; }}
.data-quality li+li {{ margin-top:3px; }}
.data-quality-note {{ color:var(--dim); font-size:10px; margin-top:6px; }}

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
.expect-intro {{ color:var(--dim); font-size:11px; margin:-5px 0 12px; }}
.expect-player {{ padding:12px; border:1px solid var(--line); border-radius:10px;
  background:var(--surface2); margin-top:9px; }}
.expect-head {{ display:flex; justify-content:space-between; gap:10px; align-items:center; }}
.expect-name {{ font-size:13px; font-weight:700; }}
.expect-badge {{ border-radius:999px; padding:3px 8px; font-size:10px; font-weight:700;
  background:rgba(255,255,255,.05); white-space:nowrap; }}
.expect-main {{ display:flex; justify-content:space-between; gap:10px; margin:8px 0 5px;
  font-size:12px; color:var(--dim); }}
.expect-main b {{ color:var(--text); font-size:14px; }}
.expect-track {{ position:relative; height:12px; border-radius:999px; background:var(--surface);
  overflow:visible; margin:7px 2px 9px; }}
.expect-fill {{ display:block; height:100%; border-radius:999px; }}
.expect-marker {{ position:absolute; top:-4px; width:2px; height:20px; background:#fff;
  box-shadow:0 0 0 2px rgba(0,0,0,.35); border-radius:2px; }}
.expect-detail {{ display:flex; flex-wrap:wrap; gap:6px 12px; color:var(--dim); font-size:10px; }}
.service-intro {{ color:var(--dim); font-size:11px; margin:-5px 0 12px; }}
.service-metric {{ padding:11px 0; border-top:1px solid var(--line); }}
.service-metric:first-of-type {{ border-top:0; padding-top:0; }}
.service-head {{ display:flex; justify-content:space-between; gap:10px; margin-bottom:8px;
  align-items:baseline; }}
.service-title {{ font-size:12px; font-weight:650; }}
.service-edge {{ font-size:10px; font-weight:700; text-align:right; }}
.service-player {{ display:grid; grid-template-columns:minmax(76px,auto) 1fr 44px; gap:8px;
  align-items:center; margin-top:5px; }}
.service-player-name {{ color:var(--dim); font-size:10px; overflow:hidden; text-overflow:ellipsis;
  white-space:nowrap; }}
.service-track {{ height:9px; border-radius:999px; background:var(--surface2); overflow:hidden; }}
.service-fill {{ display:block; height:100%; border-radius:999px; }}
.service-value {{ font-size:11px; font-weight:750; text-align:right; }}
.service-section {{ margin-top:14px; padding-top:12px; border-top:1px solid var(--line); }}
.service-section:first-of-type {{ margin-top:0; padding-top:0; border-top:0; }}
.service-section-title {{ display:flex; justify-content:space-between; gap:10px; color:var(--dim);
  font-size:10px; text-transform:uppercase; letter-spacing:.7px; margin-bottom:8px; }}
.load-intro {{ color:var(--dim); font-size:11px; margin:-5px 0 12px; }}
.load-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:10px; }}
.load-player {{ border:1px solid var(--line); border-radius:10px; background:var(--surface2); padding:12px; }}
.load-player.b {{ text-align:right; }}
.load-head {{ display:flex; justify-content:space-between; gap:8px; align-items:center; margin-bottom:10px; }}
.load-player.b .load-head {{ flex-direction:row-reverse; }}
.load-name {{ font-size:12px; font-weight:700; }}
.load-status {{ font-size:9px; font-weight:750; border-radius:999px; padding:3px 7px;
  background:rgba(255,255,255,.05); white-space:nowrap; }}
.load-stats {{ display:grid; grid-template-columns:1fr 1fr; gap:7px; }}
.load-stat {{ background:var(--surface); border-radius:7px; padding:7px; }}
.load-stat b {{ display:block; font-size:15px; }}
.load-stat span {{ display:block; color:var(--dim); font-size:9px; line-height:1.25; }}
.load-reading {{ margin-top:10px; padding:9px 11px; border-left:3px solid var(--amber);
  background:rgba(217,164,65,.07); border-radius:0 8px 8px 0; font-size:11px; color:var(--dim); }}
@media(max-width:520px) {{ .load-grid {{ grid-template-columns:1fr; }} .load-player.b {{ text-align:left; }}
  .load-player.b .load-head {{ flex-direction:row; }} }}

/* --- transparência dos pesos --- */
.weight-intro {{ color:var(--dim); font-size:11px; line-height:1.5; margin:0 0 12px; }}
.weight-summary {{ display:flex; flex-wrap:wrap; gap:7px; margin-bottom:12px; }}
.weight-chip {{ padding:5px 8px; border:1px solid var(--line); border-radius:999px;
  background:var(--surface2); color:var(--dim); font-size:9px; }}
.weight-chip b {{ color:var(--text); }}
.weight-list {{ display:grid; grid-template-columns:1fr 1fr; gap:8px; }}
.weight-row {{ min-width:0; padding:9px 10px; border:1px solid var(--line); border-radius:9px;
  background:var(--surface2); }}
.weight-row.inactive {{ opacity:.62; }}
.weight-row-head {{ display:flex; justify-content:space-between; gap:8px; align-items:baseline;
  margin-bottom:7px; }}
.weight-name {{ color:var(--text); font-size:10px; font-weight:700; overflow:hidden;
  text-overflow:ellipsis; white-space:nowrap; }}
.weight-state {{ color:var(--dim); font-size:8px; white-space:nowrap; }}
.weight-state.a {{ color:var(--a); }} .weight-state.b {{ color:var(--b); }}
.weight-scale {{ display:grid; grid-template-columns:44px 1fr 38px; gap:6px; align-items:center;
  margin-top:4px; }}
.weight-scale-label {{ color:var(--dim); font-size:8px; text-transform:uppercase; letter-spacing:.35px; }}
.weight-track {{ height:6px; border-radius:999px; background:var(--surface); overflow:hidden; }}
.weight-fill {{ display:block; height:100%; border-radius:999px; }}
.weight-fill.base {{ background:#657586; }} .weight-fill.a {{ background:var(--a); }}
.weight-fill.b {{ background:var(--b); }} .weight-fill.zero {{ background:transparent; }}
.weight-number {{ color:var(--dim); font-size:9px; text-align:right; font-variant-numeric:tabular-nums; }}
.weight-number.used {{ color:var(--text); font-weight:750; }}
.weight-formula {{ margin-top:12px; padding:9px 11px; border-left:3px solid var(--a);
  background:rgba(74,163,223,.06); border-radius:0 8px 8px 0; color:var(--dim);
  font-size:9px; line-height:1.5; }}
@media(max-width:680px) {{ .weight-list {{ grid-template-columns:1fr; }} }}

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
  font-weight:600; color:var(--text); list-style:none; }}
details.more>summary::-webkit-details-marker {{ display:none; }}
details.more>summary::before {{ content:"▸ "; }}
details.more[open]>summary::before {{ content:"▾ "; }}
details.more .more-body {{ padding:0 16px 16px; }}
.more-hint {{ color:var(--dim); font-size:11px; font-weight:400; margin-left:6px; }}

/* Mapa de Forças: destaque visual (feedback de teste, 13/08/2026 —
   "devia ter mais visibilidade, ligeiramente maior e com outra cor, para
   mostrar que é o único elemento carregável com info relevante") */
details.report-map>summary {{ min-height:78px; display:flex; align-items:center;
  flex-wrap:wrap; gap:0; padding:16px 18px; font-size:14px; }}
details.mais-forcas {{ border:1.5px solid var(--amber);
  background:linear-gradient(180deg, rgba(217,164,65,.10), var(--surface) 45%); }}
details.mais-forcas>summary {{ color:var(--amber); }}
details.mais-forcas>summary::before {{ color:var(--amber); }}
details.mais-forcas .more-hint {{ color:var(--amber); opacity:.75; }}
details.weight-transparency-card {{ border:1.5px solid var(--a);
  background:linear-gradient(180deg, rgba(74,163,223,.10), var(--surface) 45%); }}
details.weight-transparency-card>summary {{ min-height:64px; display:flex; align-items:center;
  flex-wrap:wrap; color:var(--a); padding:14px 16px; }}
details.weight-transparency-card>summary::before {{ color:var(--a); }}
details.weight-transparency-card .more-hint {{ color:var(--a); opacity:.72; }}
.market-verdict {{ background:var(--surface); border-radius:12px; padding:16px 18px;
  margin-bottom:14px; }}
.market-verdict-title {{ font-size:11px; color:var(--dim); text-transform:uppercase;
  letter-spacing:.05em; margin-bottom:4px; }}
.market-verdict-player {{ font-size:17px; font-weight:700; margin-bottom:10px; }}
.market-verdict-grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:10px;
  margin-bottom:10px; }}
.mv-label {{ display:block; font-size:11px; color:var(--dim); }}
.mv-value {{ display:block; font-size:15px; font-weight:600; }}
.market-verdict-tag {{ font-size:15px; font-weight:800; letter-spacing:.03em;
  margin-bottom:4px; }}
.market-verdict-note {{ font-size:12px; color:var(--dim); line-height:1.4; }}
.action-map-static {{ border:1.5px solid var(--mint); border-radius:12px; margin-bottom:14px;
  background:linear-gradient(180deg, rgba(63,185,168,.10), var(--surface) 45%); }}
.action-map-head {{ min-height:78px; display:flex; align-items:center; flex-wrap:wrap;
  padding:16px 18px; color:var(--mint); font-size:14px; font-weight:600; }}
.action-map-head .more-hint {{ color:var(--mint); opacity:.78; }}
.action-map-body {{ padding:0 16px 16px; }}
.action-summary {{ color:var(--text); font-size:13px; padding:12px 14px;
  border-left:3px solid var(--mint); background:rgba(63,185,168,.07);
  border-radius:0 9px 9px 0; margin-bottom:12px; }}
.action-list {{ display:grid; grid-template-columns:1fr 1fr; gap:10px; }}
.action-item {{ border:1px solid var(--line); border-radius:10px; padding:12px;
  background:var(--surface2); min-width:0; }}
.action-kind {{ color:var(--dim); font-size:9px; font-weight:750; text-transform:uppercase;
  letter-spacing:.7px; margin-bottom:4px; }}
.action-title {{ font-size:13px; font-weight:750; margin-bottom:5px; }}
.action-text {{ color:var(--dim); font-size:11px; line-height:1.5; }}
.action-source {{ color:var(--dim); opacity:.75; font-size:9px; margin-top:6px; }}
@media(max-width:640px) {{ .action-list {{ grid-template-columns:1fr; }}
  details.report-map>summary, .action-map-head {{ min-height:78px; }} }}

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
.merc-principal {{ border:1px solid var(--line); border-radius:8px; padding:10px 12px;
  margin-bottom:10px; background:var(--surface2); }}
.merc-principal-tag {{ font-size:10px; text-transform:uppercase; letter-spacing:.5px;
  color:var(--dim); font-weight:700; display:block; margin-bottom:4px; }}
.merc-linha-top {{ border-bottom:none; padding:2px 0; font-size:14px; }}
.merc-linha-top .merc-nome {{ font-size:15px; }}
.merc-secundarios {{ opacity:.75; }}
.merc-sec-tag {{ font-size:10px; color:var(--dim); margin-bottom:2px; }}
.h2h-line {{ font-size:14px; line-height:1.6; }}
.fd-linha {{ padding:6px 0; border-bottom:1px solid var(--line); font-size:13px; }}
.fd-linha:last-child {{ border-bottom:none; }}
.fd-linha-top {{ display:flex; justify-content:space-between; align-items:baseline;
  gap:10px; margin-bottom:4px; }}
.fd-nome {{ color:var(--text); font-weight:600; }}
.fd-val {{ font-weight:600; text-align:right; }}
.fd-dim {{ color:var(--dim); font-weight:400; }}
.fd-nota {{ color:var(--dim); font-size:11px; font-weight:400; }}
.fd-bar {{ display:flex; position:relative; height:22px; border-radius:5px;
  overflow:hidden; background:var(--surface2); }}
.fd-bar::after {{ content:""; position:absolute; left:50%; top:0; bottom:0;
  width:1px; background:rgba(255,255,255,.3); z-index:2; }}
.fd-bar-a {{ background:var(--a); opacity:.78; }}
.fd-bar-b {{ background:var(--b); opacity:.78; }}
.fd-bar-val {{ position:absolute; top:50%; transform:translateY(-50%); z-index:3;
  color:#fff; font-size:11px; font-weight:700; text-shadow:0 1px 2px rgba(0,0,0,.65); }}
.fd-bar-val.a {{ left:7px; }} .fd-bar-val.b {{ right:7px; }}
.fd-bar.samp-low {{ opacity:.52; }}
@media(max-width:520px){{ .more-hint {{ display:block; margin:2px 0 0 16px; }}
  .fd-linha-top {{ align-items:flex-start; }} .fd-val {{ font-size:11px; }} }}
.foot {{ text-align:center; font-size:11px; color:var(--dim); margin-top:20px;
  padding-top:14px; border-top:1px solid var(--line); }}
.photo-credits {{ margin-top:18px; color:var(--dim); font-size:10px; line-height:1.6; }}
.photo-credits summary {{ cursor:pointer; width:max-content; max-width:100%; }}
.photo-credits a {{ color:var(--dim); text-decoration:underline; }}
@media(max-width:640px) {{
  .mh-player {{ gap:7px; align-items:flex-start; }}
  .mh-player-photo {{ width:52px; height:52px; flex-basis:52px; }}
  .mh-player-avatar {{ font-size:15px; }}
}}
"""


# ============ MÓDULOS DE RENDERIZAÇÃO ============

def _mod_header(payload, div, estado):
    """Módulo 1: Matchup header (ficha de combate)."""
    a = _esc(payload.get("player_a", "?")); b = _esc(payload.get("player_b", "?"))
    ra = _d(payload.get("ranking_a")); rb = _d(payload.get("ranking_b"))
    rank_a = f"#{_esc(ra.get('rank'))}" if ra.get("rank") else ""
    rank_b = f"#{_esc(rb.get('rank'))}" if rb.get("rank") else ""
    tourn = _esc(payload.get("tournament", "")); tier = _esc(payload.get("tier", ""))
    surf = _esc(payload.get("surface", ""))
    odds = _d(payload.get("market_odds_decimal"))
    oa = _esc(odds.get(payload.get("player_a")) or "—")
    ob = _esc(odds.get(payload.get("player_b")) or "—")
    odds_meta_parts = []
    if payload.get("odds_source"):
        odds_meta_parts.append(f"Fonte: {_esc(payload['odds_source'])}")
    if payload.get("odds_captured_at_utc"):
        odds_meta_parts.append(f"captadas em {_esc(payload['odds_captured_at_utc'])}")
    odds_meta = " · ".join(odds_meta_parts)
    # prob mercado
    pa = pb = None
    if div and div.get("market"):
        pa = div["market"]["a"]; pb = div["market"]["b"]
    # forma resumida
    fa = _d(payload.get("recent_form_a")); fb = _d(payload.get("recent_form_b"))
    forma_a = _esc(f"Forma {fa.get('wins','?')}–{fa.get('losses','?')}") if fa else ""
    forma_b = _esc(f"Forma {fb.get('wins','?')}–{fb.get('losses','?')}") if fb else ""
    def portrait(side, name):
        image = _d(payload.get(f"player_image_{side}"))
        if image.get("path"):
            return (f'<img class="mh-player-photo" src="{_esc(image["path"])}" '
                    f'alt="Fotografia de {_esc(name)}" loading="eager">')
        initials = "".join(part[:1] for part in str(name).split()[:2]).upper() or "?"
        return (f'<div class="mh-player-photo mh-player-avatar" role="img" '
                f'aria-label="Sem fotografia de {_esc(name)}">{_esc(initials)}</div>')
    # meteo à hora do jogo (contextual)
    w = _d(payload.get("weather"))
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
    <div class="mh-player a">
      {portrait("a", payload.get("player_a", "?"))}
      <div class="mh-player-info"><div class="mh-name">{a}</div>
      <div class="mh-sub">{rank_a} · {forma_a}</div></div>
    </div>
    <div>
      <div class="mh-vs">VS</div>
      <div class="mh-tourn">{tourn}<br>{tier} · {surf}</div>
    </div>
    <div class="mh-player b">
      {portrait("b", payload.get("player_b", "?"))}
      <div class="mh-player-info"><div class="mh-name b">{b}</div>
      <div class="mh-sub b">{rank_b} · {forma_b}</div></div>
    </div>
  </div>
  <div class="mh-odds">
    <div class="mh-odd">{oa}<small>{f'{pa}% mercado' if pa is not None else 'sem odds'}</small></div>
    <div class="mh-mid">{_esc(meteo)}</div>
    <div class="mh-odd b">{ob}<small>{f'{pb}% mercado' if pb is not None else ''}</small></div>
  </div>
  {f'<div class="mh-odds-meta">{odds_meta}</div>' if odds_meta else ''}
</div>"""


def _mod_photo_credits(payload):
    credits = []
    for side in ("a", "b"):
        image = _d(payload.get(f"player_image_{side}"))
        if not image.get("path"):
            continue
        name = payload.get(f"player_{side}", "Jogador")
        modified = "; miniatura/enquadramento adaptado" if image.get("modified") else ""
        credits.append(
            f'{_esc(name)}: <a href="{_esc(image.get("source_url", "#"))}">{_esc(image.get("author", "autor desconhecido"))}</a>, '
            f'<a href="{_esc(image.get("license_url", "#"))}">{_esc(image.get("license", "licença na origem"))}</a>{modified}'
        )
    if not credits:
        return ""
    return ('<details class="photo-credits"><summary>Créditos das fotografias</summary>'
            f'<div>{"<br>".join(credits)}</div></details>')


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
    fav = div.get("favorecido") or div.get("indice_favorece")
    idx = _d(div.get("indice_evidencia"))
    idx_fav = idx.get("a") if fav == payload.get("player_a") else idx.get("b")
    merc_fav = div.get("mercado_favorece")
    tipo = div.get("tipo", "")
    n_fatores = div.get("n_fatores")
    nivel = (_d(div.get("classificacao"))).get("nivel", 0)
    # Transparência (11/08/2026): quando o índice bate no extremo (todos os
    # sinais disponíveis concordam, sem nenhum contrapeso) e há poucos sinais
    # a sustentá-lo, isso é matematicamente correto mas FRÁGIL — vale a pena
    # dizê-lo, para não parecer "mais evidência" do que realmente há.
    nota_fragil = ""
    if isinstance(n_fatores, int) and n_fatores <= 3 and idx_fav is not None and (idx_fav >= 95 or idx_fav <= 5):
        nota_fragil = (f" <span style=\"opacity:.7\">(índice construído a partir de só "
                        f"{n_fatores} {'sinal' if n_fatores == 1 else 'sinais'} — todos no mesmo "
                        f"sentido, sem contrapeso.)</span>")
    if chave == "inconclusivo":
        frase = (f"O mercado favorece <b>{_esc(merc_fav)}</b>, mas os indicadores "
                 "estão demasiado equilibrados para indicar uma direção clara.")
    elif chave in ("alinhado", "alinhado_forte", "eficiente"):
        intensidade = div.get("intensidade_indicadores", "ligeira")
        frase = (f"Mercado e indicadores apontam para <b>{_esc(merc_fav)}</b>; "
                 f"a concentração dos indicadores é <b>{_esc(intensidade)}</b>. ")
        if chave == "alinhado_forte":
            frase += ("A odd merece acompanhamento, mas o índice ainda não é uma "
                      f"probabilidade calibrada nem permite calcular uma odd justa.{nota_fragil}")
        else:
            frase += "Este alinhamento, por si só, não demonstra valor."
    else:
        # divergência de direção: contra o mercado
        frase = (f"Os indicadores apontam para <b>{_esc(fav)}</b> (índice {idx_fav}/100), "
                 f"mas o mercado favorece <b>{_esc(merc_fav)}</b>. "
                 f"As duas escalas são distintas e não são subtraídas.{nota_fragil}")
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
    return f'<div class="fatores">{"".join(chips)}</div>'


# Ordem de exibição do "Mapa de Forças" — reorganizada a pedido (feedback
# de teste, 13/08/2026): antes ia por peso puro do motor; agora começa
# pelos fatores mais imediatos de ler (ranking, H2H) antes dos mais
# técnicos. Os PESOS REAIS no motor não mudam — isto é só a ordem de
# exibição, decoupled da lógica de decisão.
_FACTOR_ORDER = [
    "ranking", "ranking_evolucao", "h2h", "h2h_piso", "velocidade_piso", "indoor_outdoor", "forma_recente", "qualidade_vitorias", "sazonal",
    "piso", "recuperacao_sets", "tiebreak", "pressao_ronda", "nivel_adversario", "comeback_set1", "matchup_maos", "servico_recente", "servico_carreira", "fadiga", "lesao",
]


# Fatores onde valor_a/valor_b são percentagens diretamente comparáveis
# (maior = melhor) — mostram "XX% – YY%" e barra proporcional direta.
_FD_FACTORS_PCT = {"piso", "velocidade_piso", "forma_recente", "servico_recente", "servico_carreira", "indoor_outdoor", "tiebreak", "pressao_ronda", "nivel_adversario", "comeback_set1", "sazonal",
                    "recuperacao_sets", "matchup_maos"}
# Fatores onde valor_a/valor_b são contagens de vitórias (maior = melhor)
_FD_FACTORS_COUNT = {"h2h", "h2h_piso", "qualidade_vitorias"}
# Fatores onde valor_a/valor_b são "quanto menor, melhor" para esse jogador
# (nº de jogos recentes, dias desde o regresso) — a barra é DESENHADA
# INVERTIDA (troca-se qual valor alimenta a largura de cada lado) para que
# "barra maior" continue a significar sempre "vantagem", igual aos outros
# fatores — mas o NÚMERO mostrado dentro da barra continua a ser o real de
# cada jogador, não o valor trocado.
_FD_FACTORS_INVERTIDOS = {"fadiga", "lesao"}


def _fd_bar(chave, st):
    """Barra proporcional azul(A)/laranja(B) — mesma linguagem visual do
    resto do relatório (--a/--b). Só desenha quando há valores REAIS
    guardados (feedback de teste, 13/08/2026: 'põe barra em tudo que tenha
    dados; se não houver dados, não ponhas como se fosse empate') — nunca
    inventa um 50/50 para disfarçar a falta de dado."""
    if chave == "ranking_evolucao":
        # CASO ESPECIAL: valores podem ser NEGATIVOS (jogador em queda de
        # pontos) — a fórmula normal (largura_a/(largura_a+largura_b))
        # parte-se com números negativos. Usa antes "50% = empate,
        # desvia-se conforme a diferença", capado a +-50 p.p. de diferença
        # para a barra ficar cheia num extremo.
        va, vb = st.get("valor_a"), st.get("valor_b")
        if va is None or vb is None:
            return ""
        diff = va - vb
        pct_a = max(0, min(100, round(50 + (diff / 100.0) * 50)))
        pct_b = 100 - pct_a
        label_a = f"{va:+.0f}%"
        label_b = f"{vb:+.0f}%"
        return (f'<div class="fd-bar"><span class="fd-bar-a" style="width:{pct_a}%"></span>'
                f'<span class="fd-bar-b" style="width:{pct_b}%"></span>'
                f'<span class="fd-bar-val a">{_esc(label_a)}</span>'
                f'<span class="fd-bar-val b">{_esc(label_b)}</span></div>')
    if (chave not in _FD_FACTORS_PCT and chave not in _FD_FACTORS_COUNT
            and chave not in _FD_FACTORS_INVERTIDOS and chave != "ranking"):
        return ""
    va, vb = st.get("valor_a"), st.get("valor_b")
    if chave == "ranking":
        va, vb = st.get("pontos_a"), st.get("pontos_b")  # pontos (maior=melhor), não posição
    if va is None or vb is None:
        return ""
    # largura: para fatores invertidos, troca-se o que alimenta cada lado
    # (ver _FD_FACTORS_INVERTIDOS) — o rótulo dentro da barra mantém-se real.
    largura_a, largura_b = (vb, va) if chave in _FD_FACTORS_INVERTIDOS else (va, vb)
    if (largura_a + largura_b) <= 0:
        return ""
    pct_a = max(0, min(100, round(100 * largura_a / (largura_a + largura_b))))
    pct_b = 100 - pct_a
    # Os valores ficam dentro da barra para permitir uma leitura vertical
    # compacta do conjunto. A largura continua a codificar a relação entre
    # os jogadores; a opacidade reduzida comunica amostra pequena.
    if chave in _FD_FACTORS_PCT:
        label_a, label_b = f"{va:.0f}%", f"{vb:.0f}%"
    elif chave in _FD_FACTORS_COUNT:
        label_a, label_b = str(int(va)), str(int(vb))
    elif chave in _FD_FACTORS_INVERTIDOS:
        label_a, label_b = str(int(va)), str(int(vb))
    else:  # ranking: a barra usa pontos, mas o rótulo mostra a posição
        pos_a, pos_b = st.get("valor_a"), st.get("valor_b")
        label_a = f"#{int(pos_a)}" if pos_a is not None else "—"
        label_b = f"#{int(pos_b)}" if pos_b is not None else "—"
    samples = [st.get("amostra_a"), st.get("amostra_b")]
    low_sample = any(isinstance(n, (int, float)) and n < 10 for n in samples)
    low_cls = " samp-low" if low_sample else ""
    return (f'<div class="fd-bar{low_cls}"><span class="fd-bar-a" style="width:{pct_a}%"></span>'
            f'<span class="fd-bar-b" style="width:{pct_b}%"></span>'
            f'<span class="fd-bar-val a">{_esc(label_a)}</span>'
            f'<span class="fd-bar-val b">{_esc(label_b)}</span></div>')


def _mod_fatores_detalhados(payload, div, extras_html="", tail_html=""):
    """Módulo: TODOS os fatores do motor (não só o top-3/4), com quem tem
    vantagem em cada um, OS NÚMEROS reais por trás, e uma barra proporcional
    — "sem dados"/"empate"/"abaixo do limiar" quando aplicável. 100% Python,
    a partir de `fatores_status` (ver _calcular_divergencia) — o Claude
    nunca vê nem decide isto.

    extras_html: conteúdo adicional (Serviço/Resposta, Carga, H2H) injetado
    DENTRO do mesmo colapsável, ANTES das linhas por fator — feedback de
    teste (13/08/2026): "acho que esta info devia estar dentro do mapa de
    forças", em vez de cartões à parte antes dele."""
    status = (div or {}).get("fatores_status") or {}
    if not status and not extras_html and not tail_html:
        return ""
    max_impact = max(
        (float(st.get("peso_efetivo") or 0) for st in status.values()),
        default=0,
    )

    def impact_markup(st):
        impact = float(st.get("peso_efetivo") or 0)
        side = st.get("direcao_impacto") if impact > 0 else ""
        pct = round(100 * impact / max_impact) if max_impact else 0
        attrs = f' data-impact="{impact:.3f}" data-impact-pct="{pct}" data-impact-side="{side}"'
        if not side:
            return attrs, ""
        bar = (
            f'<div class="fd-impact-bar"><span class="fd-impact-fill {side}" '
            f'style="width:{pct / 2:.1f}%"></span>'
            f'<span class="fd-impact-value">peso {impact:.1f}</span></div>'
        )
        return attrs, bar

    def dados_insuficientes(st):
        if not st.get("disponivel"):
            return True
        motivo = str(st.get("motivo_exclusao") or "").casefold()
        return "amostra insuficiente" in motivo or "fonte não fiável" in motivo

    # Ordenação estável: preserva a sequência editorial dentro de cada grupo,
    # mas empurra para o fim apenas ausência/insuficiência de dados. Empates e
    # diferenças abaixo do limiar continuam junto dos fatores válidos, pois
    # nesses casos há dados — apenas não há vantagem material.
    chaves_presentes = [chave for chave in _FACTOR_ORDER if status.get(chave) is not None]
    chaves_ordenadas = sorted(chaves_presentes, key=lambda chave: dados_insuficientes(status[chave]))

    linhas = []
    for chave in chaves_ordenadas:
        st = status.get(chave)
        if st is None:
            continue
        nome = _esc(_nome_fator(chave))
        impact_attrs, impact_bar = impact_markup(st)
        if not st.get("disponivel"):
            linhas.append(
                f'<div class="fd-linha"{impact_attrs}><div class="fd-linha-top"><span class="fd-nome">{nome}</span>'
                f'<span class="fd-val fd-dim">sem dados</span></div>{impact_bar}</div>')
            continue
        lider = st.get("lider")
        motivo = st.get("motivo_exclusao")
        bar_html = _fd_bar(chave, st)
        if lider in (None, "igual"):
            txt = "empate" if lider == "igual" else (motivo or "sem vantagem clara")
            linhas.append(
                f'<div class="fd-linha"{impact_attrs}><div class="fd-linha-top"><span class="fd-nome">{nome}</span>'
                f'<span class="fd-val fd-dim">{_esc(txt)}</span></div>{bar_html}{impact_bar}</div>')
            continue
        # contribuiu de facto (sem motivo de exclusão) -> destaque; excluído
        # apesar de haver vantagem (ex: abaixo do limiar) -> tom neutro
        if motivo:
            cor = "var(--dim)"
        elif lider == payload.get("player_a"):
            cor = "var(--a)"
        elif lider == payload.get("player_b"):
            cor = "var(--b)"
        else:
            cor = "var(--mint)"
        seta = "·" if motivo else "▲"
        nota = f' <span class="fd-nota">({_esc(motivo)})</span>' if motivo else ""
        linhas.append(
            f'<div class="fd-linha"{impact_attrs}><div class="fd-linha-top"><span class="fd-nome">{nome}</span>'
            f'<span class="fd-val" style="color:{cor}">{seta} {_esc(lider)}{nota}</span></div>'
            f'{bar_html}{impact_bar}</div>')
    if not linhas and not extras_html and not tail_html:
        return ""
    total_tag = f" ({len(linhas)})" if linhas else ""
    factor_bars = (
        f'<div class="card factor-bars-card"><div class="factor-bars-head"><h3>Raio-X Anal&#237;tico</h3>'
        f'<div class="impact-toggle"><span>Valores reais</span><label class="impact-switch">'
        f'<input type="checkbox" aria-label="Alternar para impacto no matchup">'
        f'<span class="impact-slider"></span></label><span>Impacto no matchup</span></div></div>'
        f'<div class="factor-lines">{"".join(linhas)}'
        f'<svg class="impact-trace" aria-hidden="true"><path></path><g></g></svg></div></div>'
        if linhas else ""
    )
    return (f'<details class="more report-map mais-forcas"><summary>Mapa de Forças{total_tag}'
            f'<span class="more-hint">comparação visual de todos os fatores</span></summary>'
            f'<div class="more-body">{extras_html}{factor_bars}{tail_html}</div></details>')


def _mod_mercado_vs_sinal(payload, div):
    """Módulo 4: mercado e indicadores em duas escalas lado a lado.

    O índice de evidência não é uma pseudo-probabilidade.
    """
    if not div or not div.get("market"):
        return ""
    a = _esc(payload.get("player_a", "?")); b = _esc(payload.get("player_b", "?"))
    mk = div["market"]; idx = _d(div.get("indice_evidencia"))
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
    sinal = barra("Indicadores · peso relativo", idx.get("a", 50), idx.get("b", 50), "/100")
    return f"""
<div class="mvs">
  <h3>Mercado e indicadores</h3>
  {merc}{sinal}
</div>"""


def _mod_market_verdict(payload, div):
    """
    Bloco compacto no topo: quem, probabilidade (faixa), odd justa (faixa),
    odd de mercado, e veredicto direto — ALINHADO / VALOR / DIVERGÊNCIA /
    SEM SINAL. Construído a pedido (18/08/2026, feedback do ChatGPT do
    Hugo — "objetividade, não subjetividade"), reaproveitando
    indicative_odds e divergencia já calculados noutro sítio — não
    inventa nenhum mecanismo novo, só resume de forma mais direta o que
    já lá estava, muitas vezes escondido a meio do relatório.
    """
    if not div:
        return ""
    estimate = _d(payload.get("indicative_odds"))
    players = _d(estimate.get("players"))
    tipo = div.get("tipo")
    fav = div.get("favorecido")
    if not fav or not players:
        return ""
    side = "a" if fav == payload.get("player_a") else ("b" if fav == payload.get("player_b") else None)
    if side is None:
        return ""
    faixa = _d(players.get(side))
    prob_low, prob_high = faixa.get("probability_low_pct"), faixa.get("probability_high_pct")
    odds_low, odds_high = faixa.get("odds_low"), faixa.get("odds_high")
    market = _d(payload.get("market_odds_decimal"))
    odd_mercado = market.get(fav) or market.get(f"player_{side}")

    if tipo == "direcao":
        veredicto, cor, texto = "DIVERGÊNCIA", "var(--red)", (
            f"O mercado favorece o outro lado, enquanto os indicadores apontam para {_esc(fav)}.")
    elif div.get("valor_por_preco"):
        veredicto, cor, texto = "VALOR", "var(--mint)", (
            "O mercado está a oferecer uma odd acima da faixa indicativa estimada.")
    elif tipo == "alinhamento" and div.get("intensidade_nivel", 0) >= 3:
        veredicto, cor, texto = "ALINHADO", "var(--dim)", (
            "O mercado e os indicadores estão alinhados; sem discrepância relevante de preço.")
    else:
        veredicto, cor, texto = "SEM SINAL", "var(--dim)", (
            "Sinal insuficiente para uma leitura de mercado clara.")

    def _fmt(v, casas=2):
        try:
            return f"{float(v):.{casas}f}"
        except (TypeError, ValueError):
            return "—"

    prob_txt = f"{_fmt(prob_low, 0)}–{_fmt(prob_high, 0)}%" if prob_low is not None else "—"
    odd_justa_txt = f"{_fmt(odds_low)}–{_fmt(odds_high)}" if odds_low is not None else "—"
    odd_mercado_txt = _fmt(odd_mercado) if odd_mercado is not None else "—"
    calibrada = bool(estimate.get("calibrated"))
    aviso = "" if calibrada else '<div class="market-verdict-note" style="opacity:.7">Faixa ainda não calibrada — ver nota completa mais abaixo.</div>'

    return (
        f'<div class="market-verdict" style="border-left:4px solid {cor}">'
        f'<div class="market-verdict-title">Veredicto de mercado</div>'
        f'<div class="market-verdict-player">{_esc(fav)}</div>'
        f'<div class="market-verdict-grid">'
        f'<div><span class="mv-label">Probabilidade (faixa)</span><span class="mv-value">{prob_txt}</span></div>'
        f'<div><span class="mv-label">Odd justa (faixa)</span><span class="mv-value">{odd_justa_txt}</span></div>'
        f'<div><span class="mv-label">Mercado</span><span class="mv-value">{odd_mercado_txt}</span></div>'
        f'</div>'
        f'<div class="market-verdict-tag" style="color:{cor}">{veredicto}</div>'
        f'<div class="market-verdict-note">{texto}</div>{aviso}'
        f'</div>'
    )


def _mod_indicative_odds(payload):
    """Faixa calibrada ou, enquanto amadurece, provisória e bem identificada."""
    estimate = _d(payload.get("indicative_odds"))
    players = _d(estimate.get("players"))
    if not estimate.get("available") or not players:
        return ""
    market = _d(payload.get("market_odds_decimal"))

    def market_odd(side, name):
        direct = market.get(name)
        return direct if direct is not None else market.get(f"player_{side}")

    def card(side):
        name = payload.get(f"player_{side}", "?")
        values = _d(players.get(side))
        low, high = values.get("odds_low"), values.get("odds_high")
        if low is None or high is None:
            return ""
        observed = market_odd(side, name)
        reading = ""
        try:
            observed_num = float(observed)
            if observed_num > float(high):
                reading = "mercado acima da faixa"
            elif observed_num < float(low):
                reading = "mercado abaixo da faixa"
            else:
                reading = "mercado dentro da faixa"
        except (TypeError, ValueError):
            pass
        market_text = f" · mercado {_esc(observed)}" if observed is not None else ""
        return (f'<div class="odds-range-player {side}"><div class="odds-range-name">{_esc(name)}</div>'
                f'<div class="odds-range-value">{float(low):.2f}–{float(high):.2f}</div>'
                f'<div class="odds-range-read">{_esc(reading)}{market_text}</div></div>')

    confidence = estimate.get("confidence_level_pct", 95)
    sample = estimate.get("sample_size", 0)
    minimum = estimate.get("minimum_sample", 30)
    bucket = estimate.get("evidence_bucket") or []
    bucket_text = f" · índice {bucket[0]}–{bucket[1]}" if len(bucket) == 2 else ""
    calibrated = bool(estimate.get("calibrated", sample >= minimum))
    basis = estimate.get("basis", "historical")
    if not calibrated:
        # O comparativo continua útil, mas o próprio texto nunca o apresenta
        # como uma fronteira de valor já estabelecida.
        range_word = "faixa experimental" if basis == "heuristic" else "faixa em calibração"
        original_card = card

        def card(side):
            return original_card(side).replace("da faixa", f"da {range_word}").replace(
                "dentro da faixa", f"dentro da {range_word}"
            )
    if calibrated:
        title = "Faixa indicativa calibrada"
        note = (f"Intervalo de {confidence}% · n={sample}{bucket_text}. "
                "Estimativa histórica, não garantia nem odd justa exata.")
    elif basis == "historical":
        title = "Faixa indicativa em calibração"
        note = (f"Intervalo experimental de {confidence}% · n={sample}/{minimum}{bucket_text}. "
                "Amostra ainda reduzida; a faixa pode mudar materialmente com novos resultados.")
    else:
        title = "Faixa indicativa experimental"
        note = (f"Sem resultados liquidados neste intervalo{bucket_text}. Heurística provisória, "
                "deliberadamente larga e não calibrada; não representa uma odd justa.")
    return (f'<div class="odds-range"><h3>{title}</h3>'
            f'<div class="odds-range-grid">{card("a")}{card("b")}</div>'
            f'<div class="odds-range-note">{note}</div></div>')


def _mod_data_quality_notice(payload):
    """Um único aviso de causa-raiz, evitando vários rodapés 'sem dados'."""
    issues = _d(payload.get("data_quality")).get("issues") or []
    if not issues:
        return ""
    lines = []
    for issue in issues:
        if issue.get("type") == "name_resolution":
            names = [item.get("player") for item in issue.get("players", []) if item.get("player")]
            if names:
                lines.append(
                    f"Não foi possível associar {_esc(', '.join(names))} com segurança à base histórica; "
                    "os fatores que dependem desse histórico podem aparecer sem dados."
                )
        elif issue.get("type") == "set1_comeback":
            lines.append(
                "A recuperação após perder o 1.º set não pôde ser calculada com os dados históricos disponíveis."
            )
    if not lines:
        return ""
    rendered = "".join(f"<li>{line}</li>" for line in dict.fromkeys(lines))
    return (f'<div class="data-quality"><div class="data-quality-title">Cobertura histórica limitada</div>'
            f'<ul>{rendered}</ul><div class="data-quality-note">As odds e os restantes dados independentes '
            'continuam visíveis; este aviso identifica apenas as áreas afetadas.</div></div>')


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
    fa = _d(payload.get("recent_form_a")); fb = _d(payload.get("recent_form_b"))
    sa = _d(payload.get("season_a")); sb = _d(payload.get("season_b"))
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


def _mod_forma_ajustada(payload):
    """Forma face às expectativas históricas e nível dos adversários."""
    a = _esc(payload.get("player_a", "A")); b = _esc(payload.get("player_b", "B"))
    ma = _d(payload.get("market_adjusted_form_a"))
    mb = _d(payload.get("market_adjusted_form_b"))
    qa = _d(payload.get("opposition_quality_a"))
    qb = _d(payload.get("opposition_quality_b"))
    sa = _d(payload.get("surface_momentum_a"))
    sb = _d(payload.get("surface_momentum_b"))
    if not (ma or mb or qa or qb or sa or sb):
        return ""

    def linha(nome, side, market, quality, momentum):
        if not market or not market.get("matches"):
            return ""
        matches = max(1, int(market["matches"]))
        actual = float(market.get("actual_wins") or 0)
        expected = float(market.get("expected_wins") or 0)
        delta = actual - expected
        if delta >= .5:
            status, status_color = "Acima do esperado", f"var(--{side})"
        elif delta <= -.5:
            status, status_color = "Abaixo do esperado", "var(--error)"
        else:
            status, status_color = "Dentro do esperado", "var(--dim)"
        details = []
        if quality and quality.get("avg_opponent_rank") is not None:
            details.append(
                f'Adversários: ranking médio #{quality["avg_opponent_rank"]} '
                f'({quality.get("matches", "?")} jogos)'
            )
        if momentum and momentum.get("recent_win_pct") is not None:
            change = momentum.get("delta_pp")
            trend = "melhorou" if isinstance(change, (int, float)) and change > 0 else "piorou" if isinstance(change, (int, float)) and change < 0 else "estável"
            change_text = f" {abs(change):.0f} p.p." if isinstance(change, (int, float)) else ""
            details.append(
                f'Neste piso: {momentum["recent_win_pct"]:.0f}% recente vs '
                f'{momentum.get("career_win_pct", 0):.0f}% carreira ({trend}{change_text})'
            )
        actual_pct = min(100, 100 * actual / matches)
        expected_pct = min(100, 100 * expected / matches)
        delta_text = f"+{delta:.1f}" if delta > 0 else f"{delta:.1f}"
        return (
            f'<div class="expect-player"><div class="expect-head"><span class="expect-name">{nome}</span>'
            f'<span class="expect-badge" style="color:{status_color}">{status}</span></div>'
            f'<div class="expect-main"><span><b>{actual:g}</b> vitórias em {matches}</span>'
            f'<span>esperado: <b>{expected:.1f}</b> · diferença {delta_text}</span></div>'
            f'<div class="expect-track"><span class="expect-fill" style="width:{actual_pct:.1f}%;background:var(--{side})"></span>'
            f'<span class="expect-marker" style="left:{expected_pct:.1f}%" title="Vitórias esperadas"></span></div>'
            f'<div class="expect-detail">{"".join(f"<span>{_esc(detail)}</span>" for detail in details)}</div></div>'
        )

    return (
        '<div class="card"><h3>Desempenho face ao esperado</h3>'
        '<div class="expect-intro">A barra mostra as vitórias reais; o traço branco marca quantas eram esperadas pelas odds.</div>'
        f'{linha(a, "a", ma, qa, sa)}{linha(b, "b", mb, qb, sb)}</div>'
    )


def _mod_pressao(payload):
    """Perfil recente de serviço e resposta com métricas observáveis."""
    pa = _d(payload.get("pressure_profile_a")); pb = _d(payload.get("pressure_profile_b"))
    if not (pa or pb):
        return ""
    a = _esc(payload.get("player_a", "A")); b = _esc(payload.get("player_b", "B"))
    metrics = (
        ("1.º serviço ganho", "first_serve_won_pct", False),
        ("2.º serviço ganho", "second_serve_won_pct", False),
        ("BP salvos", "break_points_saved_pct", False),
        ("BP convertidos", "break_points_converted_pct", False),
        ("1.º serviço permitido ao adversário", "opponent_first_serve_won_pct", True),
        ("2.º serviço permitido ao adversário", "opponent_second_serve_won_pct", True),
    )
    rows = []
    for label, key, lower_is_better in metrics:
        va, vb = pa.get(key), pb.get(key)
        if va is None or vb is None:
            continue
        diff = va - vb
        if abs(diff) < 0.5:
            edge = "="
        else:
            a_leads = diff < 0 if lower_is_better else diff > 0
            edge = a if a_leads else b
        rows.append(
            f'<div class="cmp-row" style="grid-template-columns:1fr 60px 110px 60px">'
            f'<div class="cmp-name">{_esc(label)}</div><div class="cmp-num">{va}%</div>'
            f'<div class="cmp-delta">{edge}</div><div class="cmp-num">{vb}%</div></div>'
        )
    if not rows:
        return ""
    return (
        '<div class="card"><h3>Pressão de serviço e resposta</h3>'
        f'<div class="cmp-lbl">{a} · n={pa.get("matches", "?")} &nbsp;|&nbsp; '
        f'{b} · n={pb.get("matches", "?")}</div>{"".join(rows)}</div>'
    )


def _mod_servico(payload):
    """Base histórica e momento recente numa única leitura, sem duplicação."""
    sa = _d(payload.get("serve_return_stats_a"))
    sb = _d(payload.get("serve_return_stats_b"))
    pa = _d(payload.get("pressure_profile_a"))
    pb = _d(payload.get("pressure_profile_b"))
    if not ((sa and sb) or (pa and pb)):
        return ""
    a = payload.get("player_a", "A"); b = payload.get("player_b", "B")
    career_metrics = [
        ("Pontos ganhos no 1.º serviço", "avg_first_serve_won_pct"),
        ("Break points salvos sob pressão", "avg_break_points_saved_pct"),
        ("Pontos ganhos na resposta", "avg_return_points_won_pct"),
        ("Break points convertidos na resposta", "avg_break_points_converted_pct"),
    ]
    recent_metrics = [
        ("Pontos ganhos no 1.º serviço", "first_serve_won_pct"),
        ("Pontos ganhos no 2.º serviço", "second_serve_won_pct"),
        ("Break points salvos sob pressão", "break_points_saved_pct"),
        ("Break points convertidos na resposta", "break_points_converted_pct"),
    ]

    def section(title, left, right, metrics, sample_text=""):
        rows = []
        for label, key in metrics:
            va, vb = _pct(left.get(key)), _pct(right.get(key))
            if va is None or vb is None:
                continue
            delta = va - vb
            if abs(delta) < 0.5:
                advantage, colour = "Equilíbrio", COLORS_V2["dim"]
            elif delta > 0:
                advantage = f"Vantagem {_esc(a.split()[-1])} · +{delta:.1f} p.p."
                colour = COLORS_V2["a"]
            else:
                advantage = f"Vantagem {_esc(b.split()[-1])} · +{abs(delta):.1f} p.p."
                colour = COLORS_V2["b"]
            rows.append(f"""
<div class="service-metric">
  <div class="service-head"><span class="service-title">{_esc(label)}</span><span class="service-edge" style="color:{colour}">{advantage}</span></div>
  <div class="service-player"><span class="service-player-name">{_esc(a)}</span><span class="service-track"><span class="service-fill" style="width:{va:.1f}%;background:var(--a)"></span></span><span class="service-value">{va:.1f}%</span></div>
  <div class="service-player"><span class="service-player-name">{_esc(b)}</span><span class="service-track"><span class="service-fill" style="width:{vb:.1f}%;background:var(--b)"></span></span><span class="service-value">{vb:.1f}%</span></div>
</div>""")
        if not rows:
            return ""
        return (f'<div class="service-section"><div class="service-section-title"><span>{_esc(title)}</span>'
                f'<span>{_esc(sample_text)}</span></div>{"".join(rows)}</div>')

    career = section("Base histórica", sa, sb, career_metrics) if sa and sb else ""
    recent_sample = f"{a}: n={pa.get('matches', '?')} · {b}: n={pb.get('matches', '?')}" if pa and pb else ""
    recent = section("Momento recente sob pressão", pa, pb, recent_metrics, recent_sample) if pa and pb else ""
    if not (career or recent):
        return ""
    return f"""
<div class="card"><h3>Serviço e resposta · quem leva vantagem</h3>
  <div class="service-intro">A base histórica mostra o nível estrutural; o momento recente revela como cada jogador tem respondido sob pressão.</div>
  {career}{recent}
</div>"""


def _mod_fadiga(payload):
    """Carga multidimensional: descanso, densidade, volume e torneio atual."""
    fa = _d(payload.get("fatigue_signal_a"))
    fb = _d(payload.get("fatigue_signal_b"))
    if not (fa.get("matches_last_7d") is not None and fb.get("matches_last_7d") is not None):
        return ""
    a = _esc(payload.get("player_a", "A")); b = _esc(payload.get("player_b", "B"))
    def status(data):
        rest = data.get("days_since_last_match")
        sets = data.get("sets_last_7d", 0) or 0
        dense = data.get("matches_last_3d", 0) or 0
        if sets >= 9 or (rest is not None and rest <= 1 and (sets >= 7 or dense >= 2)):
            return "Carga elevada", "var(--error)"
        if sets >= 5 or dense >= 1 or (rest is not None and rest <= 2):
            return "Carga moderada", "var(--amber)"
        return "Carga leve", "var(--mint)"

    def player_card(name, side, data):
        label, colour = status(data)
        rest = data.get("days_since_last_match")
        rest_text = "?" if rest is None else str(rest)
        stats = (
            (rest_text, "dias de descanso"),
            (data.get("matches_last_3d", "?"), "jogos em 3 dias"),
            (data.get("sets_last_7d", "?"), "sets em 7 dias"),
            (data.get("matches_this_tournament", "?"), "jogos no torneio"),
            (data.get("last_match_sets", "?"), "sets no último jogo"),
            (data.get("matches_last_14d", "?"), "jogos em 14 dias"),
        )
        cells = "".join(f'<div class="load-stat"><b>{_esc(value)}</b><span>{_esc(label_)}</span></div>' for value, label_ in stats)
        return (f'<div class="load-player {side}"><div class="load-head"><span class="load-name">{name}</span>'
                f'<span class="load-status" style="color:{colour}">{label}</span></div>'
                f'<div class="load-stats">{cells}</div></div>')

    observations = []
    comparisons = (
        ("sets_last_7d", "sets nos últimos 7 dias"),
        ("matches_last_3d", "jogos nos últimos 3 dias"),
        ("matches_this_tournament", "jogos neste torneio"),
        ("last_match_sets", "sets no último jogo"),
    )
    for key, label in comparisons:
        va, vb = fa.get(key), fb.get(key)
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)) and va != vb:
            heavier = a if va > vb else b
            observations.append(f"{heavier} tem +{abs(va-vb):g} {label}")
    ra, rb = fa.get("days_since_last_match"), fb.get("days_since_last_match")
    if isinstance(ra, (int, float)) and isinstance(rb, (int, float)) and ra != rb:
        less_rested = a if ra < rb else b
        observations.append(f"{less_rested} tem {abs(ra-rb):g} dia(s) menos de recuperação")
    reading = "; ".join(observations[:3]) if observations else "Perfis de carga semelhantes nos dados disponíveis"
    return f"""
<div class="card"><h3>Carga e recuperação</h3>
  <div class="load-intro">Leitura combinada do descanso, densidade competitiva e volume acumulado — não apenas do número de jogos.</div>
  <div class="load-grid">{player_card(a, "a", fa)}{player_card(b, "b", fb)}</div>
  <div class="load-reading"><b>Leitura combinada:</b> {_esc(reading)}.</div>
</div>"""


def _mod_transparencia_pesos(payload, div):
    """Expõe, sem LLM, a passagem do peso configurado ao peso efetivo.

    É uma bubble autónoma do Mapa de Forças: não pertence à análise de carga
    e não altera o cálculo. A escala é comum a todas as barras, permitindo
    comparar pesos-base e contribuições reais entre fatores.
    """
    status = _d((div or {}).get("fatores_status"))
    a = str(payload.get("player_a") or "A")
    b = str(payload.get("player_b") or "B")
    ordem = list(dict.fromkeys([*_FACTOR_ORDER, *PESOS.keys()]))
    max_peso = max(
        [float(v) for v in PESOS.values()]
        + [float(_d(st).get("peso_efetivo") or 0) for st in status.values()],
        default=1,
    ) or 1
    ativos = sum(1 for st in status.values() if float(_d(st).get("peso_efetivo") or 0) > 0)
    total_aplicado = sum(float(_d(st).get("peso_efetivo") or 0) for st in status.values())
    linhas = []
    for chave in ordem:
        st = _d(status.get(chave))
        base = float(st.get("peso_base_configurado", PESOS.get(chave, 0)) or 0)
        usado = float(st.get("peso_efetivo") or 0)
        side = st.get("direcao_impacto") if usado > 0 else ""
        lider = a if side == "a" else b if side == "b" else ""
        if usado > 0:
            estado = f"→ {lider}"
        elif not st or not st.get("disponivel"):
            estado = "sem dados"
        elif st.get("lider") == "igual":
            estado = "equilíbrio"
        else:
            estado = st.get("motivo_exclusao") or "não ativado"
        base_pct = min(100, 100 * base / max_peso)
        usado_pct = min(100, 100 * usado / max_peso)
        inactive = " inactive" if usado <= 0 else ""
        state_cls = f" {side}" if side else ""
        used_cls = side if side else "zero"
        linhas.append(
            f'<div class="weight-row{inactive}" data-weight-factor="{_esc(chave)}"><div class="weight-row-head">'
            f'<span class="weight-name">{_esc(_nome_fator(chave))}</span>'
            f'<span class="weight-state{state_cls}">{_esc(estado)}</span></div>'
            f'<div class="weight-scale"><span class="weight-scale-label">base</span>'
            f'<span class="weight-track"><span class="weight-fill base" style="width:{base_pct:.1f}%"></span></span>'
            f'<span class="weight-number">{base:g}</span></div>'
            f'<div class="weight-scale"><span class="weight-scale-label">aplicado</span>'
            f'<span class="weight-track"><span class="weight-fill {used_cls}" style="width:{usado_pct:.1f}%"></span></span>'
            f'<span class="weight-number used">{usado:.1f}</span></div></div>'
        )
    caps_labels = {
        "forca_base": "força base", "matchup": "matchup", "superficie": "superfície",
        "resiliencia": "resiliência", "ranking_fam": "ranking", "contexto": "contexto",
    }
    caps = " · ".join(
        f'{caps_labels.get(fam, fam)} ≤ {cap:g}' for fam, cap in CAPS_FAMILIAS_PESOS.items()
    )
    return (
        f'<details class="more weight-transparency-card"><summary>Transparência dos Pesos ({len(PESOS)})'
        '<span class="more-hint">peso-base e contributo aplicado</span></summary>'
        '<div class="more-body"><div class="weight-intro">Cada fator começa com um peso-base. O peso aplicado mostra '
        'quanto entrou realmente na avaliação deste confronto e para que jogador apontou.</div>'
        f'<div class="weight-summary"><span class="weight-chip"><b>{ativos}</b> fatores ativos</span>'
        f'<span class="weight-chip"><b>{total_aplicado:.1f}</b> peso total aplicado</span>'
        f'<span class="weight-chip"><b>{len(PESOS)}</b> fatores auditados</span></div>'
        f'<div class="weight-list">{"".join(linhas)}</div>'
        '<div class="weight-formula"><b>Como é calculado:</b> peso aplicado = peso-base × intensidade '
        'da diferença × confiança da amostra; no fim, fatores relacionados partilham limites para '
        f'evitar contar duas vezes a mesma vantagem. Limites por família: {_esc(caps)}.</div></div></details>'
    )


def _mod_cenarios(payload):
    """Módulo 9: cenários — só os DIFERENCIADORES (auditoria)."""
    ra = _d(_d(payload.get("rich_stats_a")).get("scenarios"))
    rb = _d(_d(payload.get("rich_stats_b")).get("scenarios"))
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
    h = h if isinstance(h, dict) else None
    a = _esc(payload.get("player_a", "A")); b = _esc(payload.get("player_b", "B"))
    if not h:
        overall = None
    else:
        overall = h.get("overall") if isinstance(h.get("overall"), dict) else h
    if not overall or overall.get("total_matches", overall.get("total", 0)) in (0, None):
        texto = "Sem confrontos diretos entre os dois jogadores."
        return f'<div class="card"><h3>Confronto direto (H2H)</h3><div class="h2h-line">{texto}</div></div>'
    aw = overall.get("a_wins", 0); bw = overall.get("b_wins", 0)
    total = overall.get("total_matches", overall.get("total", aw + bw))
    # piso, se houver
    surf = (_d(h.get("surface"))) if isinstance(h, dict) else {}
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
    """Mostra Moneyline em divergência ou alinhamento interno forte.

    Total/Handicap não são apresentados: não existem odds nem modelo próprio
    para esses mercados, logo qualquer indicação seria especulativa."""
    if not div or not div.get("market"):
        return ""
    fav = div.get("favorecido")
    nivel = (_d(div.get("classificacao"))).get("nivel", 0)
    tipo = div.get("tipo", "")
    alinhamento_forte = tipo == "alinhamento" and div.get("intensidade_nivel", 0) >= 3
    if alinhamento_forte:
        fav = div.get("indice_favorece")
        bola = "🔵"
        nota = ("mercado e indicadores concordam com intensidade forte; acompanhar o preço, "
                "sem inferir odd justa")
    elif tipo == "direcao" and nivel >= 1 and fav:
        bola = "🟢" if nivel >= 2 else "🟡"
        nota = "indicadores apontam na direção oposta ao mercado"
    else:
        return ""
    return (
        '<div class="card"><h3>Mercado observado</h3>'
        '<div class="merc-principal">'
        '<div class="merc-linha merc-linha-top">'
        f'<span class="merc-bola">{bola}</span>'
        f'<span class="merc-nome">Moneyline {_esc(fav)}</span>'
        f'<span class="merc-nota">{nota}</span></div></div></div>'
    )


def _mod_action_map(payload, div, result):
    """Plano condicional determinístico, sem inventar linhas ou odds."""
    a = payload.get("player_a", "A")
    b = payload.get("player_b", "B")
    names = {"a": a, "b": b}
    actions = []

    def add(kind, title, text, source=""):
        actions.append({"kind": kind, "title": title, "text": text, "source": source})

    div = _d(div)
    level = _d(div.get("classificacao")).get("nivel", 0) or 0
    signal_type = div.get("tipo", "")
    fav = div.get("favorecido") if signal_type == "direcao" else div.get("indice_favorece")
    fav_side = "a" if fav == a else "b" if fav == b else None
    market = _d(payload.get("market_odds_decimal"))

    def observed_odd(side):
        name = names.get(side)
        return market.get(name, market.get(f"player_{side}"))

    # Só Moneyline dispõe simultaneamente de odds e modelo próprios.
    # NOVO (18/08/2026): verifica ANTES se a faixa indicativa existe mesmo
    # para este jogador, para não escrever "dentro da faixa indicada"
    # quando não há faixa nenhuma para mostrar (texto ficava a apontar
    # para algo que não existia no relatório).
    _estimate_alinhamento = _d(payload.get("indicative_odds"))
    _ranges_alinhamento = _d(_estimate_alinhamento.get("players"))
    _tem_faixa_alinhamento = bool(fav_side and _d(_ranges_alinhamento.get(fav_side)))

    if not div.get("market"):
        add("Pré-jogo", "Esperar por odds",
            "Sem preço de mercado não existe decisão pré-jogo comparável. Manter apenas os cenários ao vivo em observação.")
    elif signal_type == "direcao" and fav_side and level >= 1:
        strength = "forte" if level >= 3 else "moderada" if level >= 2 else "ligeira"
        add("Mercado principal", f"Moneyline {fav}",
            f"Divergência {strength}: os indicadores apontam para {fav}, contra a direção do mercado. Confirmar o preço; a divergência isolada não é uma entrada.",
            "Motor de divergência")
    elif signal_type == "alinhamento" and fav_side and div.get("intensidade_nivel", 0) >= 3:
        _nota_alinhamento = (
            "Mercado e indicadores estão fortemente alinhados. Acompanhar apenas se o preço oferecer margem dentro da faixa indicada."
            if _tem_faixa_alinhamento else
            "Mercado e indicadores estão fortemente alinhados. Ainda sem faixa indicativa calculada para comparar o preço."
        )
        add("Mercado principal", f"Moneyline {fav}", _nota_alinhamento,
            "Mercado + índice de sinais")
    else:
        add("Pré-jogo", "Sem ação clara",
            "O mercado e os indicadores não criam uma discrepância suficientemente clara. Esperar por informação ao vivo em vez de forçar uma leitura pré-jogo.")

    # Usa a faixa já mostrada no relatório como gatilho, não como garantia.
    estimate = _d(payload.get("indicative_odds"))
    ranges = _d(estimate.get("players"))
    price_side = fav_side
    if price_side is None and div.get("indice_favorece") in (a, b):
        price_side = "a" if div.get("indice_favorece") == a else "b"
    if price_side and _d(ranges.get(price_side)):
        values = _d(ranges.get(price_side))
        low, high = values.get("odds_low"), values.get("odds_high")
        current = observed_odd(price_side)
        try:
            low_f, high_f = float(low), float(high)
            current_f = float(current) if current is not None else None
        except (TypeError, ValueError):
            low_f = high_f = current_f = None
        if low_f is not None and high_f is not None:
            status = "calibrada" if estimate.get("calibrated") else "em calibração"
            current_text = f"A odd atual é {current_f:.2f}. " if current_f is not None else ""
            add("Gatilho de preço", f"Faixa {status} · {names[price_side]}",
                f"{current_text}Se descer abaixo de {low_f:.2f}, a margem indicada enfraquece; se subir acima de {high_f:.2f}, revalidar notícias e dados antes de considerar o preço — não é uma entrada automática.",
                f"Faixa {low_f:.2f}–{high_f:.2f} · n={estimate.get('sample_size', 0)}")

    def scenario(side, rate_key, count_key):
        rich = _d(_d(payload.get(f"rich_stats_{side}")).get("scenarios"))
        return rich.get(rate_key), rich.get(count_key)

    # Recuperação depois do primeiro set: gatilho condicional live.
    comeback = {}
    for side in ("a", "b"):
        rate, count = scenario(side, "first_set_lose_then_win_pct", "first_set_lose_count")
        if rate is None:
            is_bo5 = payload.get("tour") == "atp" and "grand slam" in str(payload.get("tier", "")).lower()
            fallback = _d(_d(payload.get(f"set1_comeback_stats_{side}")).get("bo5" if is_bo5 else "bo3"))
            rate, count = fallback.get("comeback_rate_pct"), fallback.get("matches_lost_set1")
        if isinstance(rate, (int, float)) and isinstance(count, (int, float)) and count >= 5:
            comeback[side] = (float(rate), int(count))
    if comeback:
        side = max(comeback, key=lambda key: comeback[key][0])
        rate, count = comeback[side]
        if rate >= 30:
            add("Cenário ao vivo", f"Se {names[side]} perder o 1.º set",
                f"Acompanhar a Moneyline ao vivo apenas se o serviço e a mobilidade se mantiverem estáveis: recuperou {rate:.0f}% destes jogos. Uma quebra física invalida o cenário.",
                f"Histórico de recuperações · n={count}")

    # Set decisivo: só quando a diferença é material e tem amostra.
    deciding = {}
    for side in ("a", "b"):
        rate, count = scenario(side, "deciding_set_win_pct", "deciding_set_count")
        if rate is None:
            is_bo5 = payload.get("tour") == "atp" and "grand slam" in str(payload.get("tier", "")).lower()
            fallback = _d(_d(payload.get(f"deciding_set_stats_{side}")).get("bo5" if is_bo5 else "bo3"))
            rate, count = fallback.get("win_rate_pct"), fallback.get("matches_went_the_distance")
        if isinstance(rate, (int, float)) and isinstance(count, (int, float)) and count >= 8:
            deciding[side] = (float(rate), int(count))
    if len(deciding) == 2:
        sa, sb = deciding["a"], deciding["b"]
        if abs(sa[0] - sb[0]) >= 8:
            side = "a" if sa[0] > sb[0] else "b"
            rate, count = deciding[side]
            add("Cenário ao vivo", "Se o jogo chegar ao set decisivo",
                f"O histórico favorece {names[side]} ({rate:.0f}%). Observar o preço live e confirmar que não há quebra de serviço ou carga antes de agir.",
                f"Sets decisivos · n={count}")

    # Carga abre hipóteses live, explicitamente sem modelo de linha/odd.
    fa, fb = _d(payload.get("fatigue_signal_a")), _d(payload.get("fatigue_signal_b"))
    sets_a, sets_b = fa.get("sets_last_7d"), fb.get("sets_last_7d")
    if isinstance(sets_a, (int, float)) and isinstance(sets_b, (int, float)) and abs(sets_a - sets_b) >= 4:
        heavy = "a" if sets_a > sets_b else "b"
        fresh = "b" if heavy == "a" else "a"
        add("Mercados ao vivo", "Handicap ou total de jogos · observar",
            f"{names[heavy]} traz +{abs(sets_a-sets_b):g} sets em 7 dias. Se aparecer quebra clara de deslocação ou serviço, acompanhar handicap a favor de {names[fresh]} e total de jogos; o sistema ainda não calcula linha nem odd justa para estes mercados.",
            "Carga acumulada")

    # Serviços fortes e equilibrados sugerem observação, não previsão certa.
    pa, pb = _d(payload.get("pressure_profile_a")), _d(payload.get("pressure_profile_b"))
    serve_a, serve_b = pa.get("first_serve_won_pct"), pb.get("first_serve_won_pct")
    if (isinstance(serve_a, (int, float)) and isinstance(serve_b, (int, float))
            and min(serve_a, serve_b) >= 65 and abs(serve_a - serve_b) <= 5):
        add("Mercados ao vivo", "Tie-break / total acima · observar",
            "Se ambos confirmarem elevada proteção do serviço nos primeiros jogos, acompanhar linhas de tie-break e total acima. Sem confirmação ao vivo, o equilíbrio histórico não basta.",
            "Pressão de serviço")

    summary = result.get("verdict") or result.get("executive_summary")
    summary_html = f'<div class="action-summary">{_esc(summary)}</div>' if summary else ""
    rendered = "".join(
        f'<div class="action-item"><div class="action-kind">{_esc(item["kind"])}</div>'
        f'<div class="action-title">{_esc(item["title"])}</div>'
        f'<div class="action-text">{_esc(item["text"])}</div>'
        + (f'<div class="action-source">{_esc(item["source"])}</div>' if item["source"] else "")
        + '</div>'
        for item in actions[:6]
    )
    count = min(len(actions), 6)
    return (f'<section class="action-map-static"><div class="action-map-head">Mapa de Ações ({count})'
            '<span class="more-hint">mercados, gatilhos e cenários a acompanhar</span></div>'
            f'<div class="action-map-body">{summary_html}<div class="action-list">{rendered}</div></div></section>')


def _normalizar_div(raw):
    """Converte o output do _calcular_divergencia (chaves prob_mercado_a etc.)
    no formato que o V2 usa (market/indice_evidencia estruturados)."""
    if not raw:
        return None
    if raw.get("prob_mercado_a") is None:
        return {"market": None, "indice_evidencia": None,
                "classificacao": raw.get("classificacao"), "favorecido": raw.get("favorecido"),
                # CORREÇÃO (12/08/2026): estas duas chaves foram acrescentadas
                # ao _calcular_divergencia mas esquecidas aqui — o módulo
                # "Fatores Detalhados" e a nota de "índice frágil" nunca
                # apareciam no relatório real por causa disto (confirmado:
                # CSS presente, secção ausente — a normalização matava os dados).
                "n_fatores": raw.get("n_fatores"),
                "fatores_status": raw.get("fatores_status"),
                "gap_pp": raw.get("gap_pp")}
    return {
        "market": {"a": raw["prob_mercado_a"], "b": raw["prob_mercado_b"]},
        "indice_evidencia": {"a": raw["indice_evidencia_a"], "b": raw["indice_evidencia_b"]},
        "classificacao": raw.get("classificacao"),
        "favorecido": raw.get("favorecido"),
        "tipo": raw.get("tipo"),
        "intensidade_indicadores": raw.get("intensidade_indicadores"),
        "intensidade_nivel": raw.get("intensidade_nivel"),
        "forca_indice": raw.get("forca_indice"),
        "mercado_favorece": raw.get("mercado_favorece"),
        "indice_favorece": raw.get("indice_favorece"),
        "fatores_chave": raw.get("fatores_chave"),
        "n_fatores": raw.get("n_fatores"),
        "fatores_status": raw.get("fatores_status"),
        "gap_pp": raw.get("gap_pp"),
    }


def _css_editorial():
    return """
.mh{position:relative;overflow:hidden;border-radius:18px;padding:24px}.mh::after{content:"";position:absolute;inset:0;pointer-events:none;opacity:.08;background:linear-gradient(90deg,transparent 49.8%,var(--b) 50%,transparent 50.2%)}
.mh-kicker{text-align:center;color:var(--b);text-transform:uppercase;letter-spacing:1.8px;font-size:10px;font-weight:700;margin-bottom:18px}.mh-name{font-size:28px;letter-spacing:-.7px}.mh-vs{font-size:18px;color:var(--text);font-weight:800;letter-spacing:2px}
.mh-context{display:grid;grid-template-columns:1fr auto 1fr;gap:12px;margin-top:18px;padding-top:14px;border-top:1px solid var(--line);align-items:center;font-size:12px;color:var(--dim)}.mh-context .b{text-align:right}.mh-h2h{color:var(--text);font-weight:700;text-align:center;white-space:nowrap}
.section-title{font-size:11px;color:var(--b);text-transform:uppercase;letter-spacing:1.5px;margin:22px 2px 9px}.match-intro{border-left:3px solid var(--b);padding:12px 15px;background:rgba(52,200,255,.06);border-radius:0 10px 10px 0;margin-bottom:14px;color:var(--text);font-size:15px}
.glance{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin-bottom:14px}.glance-head,.glance-row{display:grid;grid-template-columns:1fr minmax(120px,.8fr) 1fr;gap:10px;align-items:center}.glance-head{padding-bottom:9px;color:var(--dim);font-size:11px}.glance-head span:last-child,.glance-b{text-align:right}.glance-row{padding:9px 0;border-top:1px solid var(--line)}.glance-label{text-align:center;color:var(--dim);font-size:11px;text-transform:uppercase;letter-spacing:.5px}.glance-a,.glance-b{font-size:15px;font-weight:700}.glance-win{color:var(--mint)}
.keys{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-bottom:14px}.key{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px;display:grid;grid-template-columns:auto 1fr;gap:10px}.key-num{color:var(--b);font-size:11px;font-weight:800;letter-spacing:1px}.key-text{font-size:13px}.market-section{margin-top:24px;padding-top:1px;border-top:1px solid var(--line)}
.history-row{padding:10px 0;border-top:1px solid var(--line)}.history-row:first-of-type{border-top:0}.history-meta{color:var(--dim);font-size:11px}.history-result{display:flex;justify-content:space-between;gap:12px;margin-top:3px;font-size:13px}.history-result span{color:var(--dim)}.history-winner.a{color:var(--a)}.history-winner.b{color:var(--b)}
.pulse-player{display:grid;grid-template-columns:minmax(120px,.7fr) minmax(0,1fr);gap:14px;align-items:center;padding:9px 0;border-top:1px solid var(--line);font-size:13px}.pulse-player:first-of-type{border-top:0}.pulse-seq{display:flex;justify-content:flex-end;gap:5px;flex-wrap:nowrap;min-width:0;overflow-x:auto;overscroll-behavior-x:contain;scrollbar-width:none}.pulse-seq::-webkit-scrollbar{display:none}.pulse-seq span{display:inline-grid;place-items:center;width:25px;height:25px;flex:0 0 25px;border-radius:6px;font-size:11px;font-weight:800}.pulse-win{background:rgba(199,255,61,.13);color:var(--mint);border:1px solid rgba(199,255,61,.35)}.pulse-loss{background:rgba(224,108,91,.12);color:#f29b8d;border:1px solid rgba(224,108,91,.3)}.pulse-empty{width:auto!important;flex-basis:auto!important;padding:0 8px;color:var(--dim)}.analytics-title{margin:18px 0 10px;padding:10px 12px;border:1px solid var(--b);border-radius:10px;background:rgba(52,200,255,.06);color:var(--b);font-size:12px;text-transform:uppercase;letter-spacing:1px}
.pulse-form-bars{margin-top:10px;padding-top:12px;border-top:1px solid var(--line)}
.factor-bars-card{border-color:var(--line);background:linear-gradient(180deg,rgba(74,163,223,.08),var(--surface) 30%)}
.factor-bars-card .fd-linha{padding:9px 11px;background:rgba(74,163,223,.055);border-bottom-color:rgba(120,207,255,.14)}.factor-bars-card .fd-linha:first-of-type{border-radius:8px 8px 0 0}.factor-bars-card .fd-linha:last-child{border-radius:0 0 8px 8px}
.factor-bars-head{display:flex;justify-content:space-between;gap:16px;align-items:center;margin-bottom:12px}.factor-bars-head h3{color:var(--a);margin:0}.impact-toggle{display:flex;align-items:center;gap:7px;color:var(--dim);font-size:10px}.impact-switch{position:relative;width:42px;height:24px;flex:0 0 auto}.impact-switch input{position:absolute;opacity:0;pointer-events:none}.impact-slider{position:absolute;inset:0;border-radius:999px;background:var(--surface2);border:1px solid var(--line);cursor:pointer;transition:.2s}.impact-slider::before{content:"";position:absolute;width:18px;height:18px;left:2px;top:2px;border-radius:50%;background:#fff;box-shadow:0 2px 5px rgba(0,0,0,.35);transition:.2s}.impact-switch input:checked+.impact-slider{background:rgba(74,163,223,.55);border-color:var(--a)}.impact-switch input:checked+.impact-slider::before{transform:translateX(18px)}.impact-switch input:focus-visible+.impact-slider{outline:2px solid var(--a);outline-offset:2px}
.factor-lines{position:relative}.fd-impact-bar,.impact-trace{display:none}.factor-bars-card.impact-mode{background:#090e13;border-color:#213445}.factor-bars-card.impact-mode .factor-lines{background:#070b0f;border-radius:9px}.factor-bars-card.impact-mode .fd-linha{background:rgba(8,16,23,.82);border-bottom-color:rgba(110,145,168,.12)}.factor-bars-card.impact-mode .fd-nome,.factor-bars-card.impact-mode .fd-val{color:#748493!important}.factor-bars-card.impact-mode .fd-nota{color:#586875}.factor-bars-card.impact-mode .fd-bar{display:none}.factor-bars-card.impact-mode .fd-impact-bar{display:block;position:relative;height:22px;border-radius:5px;overflow:hidden;background:#111a22}.fd-impact-bar::after{content:"";position:absolute;left:50%;top:0;bottom:0;width:1px;background:rgba(255,255,255,.32);z-index:2}.fd-impact-fill{position:absolute;top:0;bottom:0;z-index:1}.fd-impact-fill.a{right:50%;background:var(--a)}.fd-impact-fill.b{left:50%;background:var(--b)}.fd-impact-value{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);z-index:4;color:#dce8f0;font-size:10px;font-weight:700;background:rgba(5,9,12,.68);padding:1px 5px;border-radius:4px}.factor-bars-card.impact-mode .impact-trace{display:block;position:absolute;inset:0;width:100%;height:100%;overflow:visible;pointer-events:none;z-index:5}.impact-trace path{fill:none;stroke:#d5f4ff;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;filter:drop-shadow(0 0 4px rgba(120,207,255,.8))}.impact-trace circle{fill:#f3fbff;stroke:#20394a;stroke-width:1.5}.factor-bars-card.impact-mode .fd-linha[data-impact-side=""]{opacity:.42}
.factor-bars-card.impact-mode .fd-linha[data-impact-side="a"] .fd-val{color:#78cfff!important}.factor-bars-card.impact-mode .fd-linha[data-impact-side="b"] .fd-val{color:#ffb47f!important}.factor-bars-card.impact-mode .fd-nota{color:#586875!important}
@media(max-width:640px){.factor-bars-head{align-items:flex-start;flex-direction:column}.impact-toggle{width:100%;justify-content:flex-end}}
.history-score{padding:0 0 12px;margin-bottom:2px}.history-score-names{display:flex;justify-content:space-between;gap:12px;color:var(--dim);font-size:11px;margin-bottom:5px}
@media(max-width:640px){.mh{padding:18px 14px}.mh-top{grid-template-columns:minmax(0,1fr) 18px minmax(0,1fr);grid-template-areas:"center center center" "player-a . player-b";gap:12px 5px}.mh-top>.mh-player.a{grid-area:player-a}.mh-top>.mh-player.b{grid-area:player-b}.mh-top>div:nth-child(2){grid-area:center}.mh-player,.mh-player.b{flex-direction:column;gap:8px}.mh-player{align-items:flex-start}.mh-player.b{align-items:flex-end}.mh-player-photo{width:60px;height:60px;flex-basis:60px}.mh-player-info{width:100%}.mh-name{font-size:17px;line-height:1.18;overflow-wrap:anywhere}.mh-sub{font-size:11px}.mh-tourn{font-size:9px}.mh-odds{grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);gap:7px}.mh-odd{font-size:18px}.mh-context{font-size:10px}.keys{grid-template-columns:1fr}.glance-head,.glance-row{grid-template-columns:1fr 100px 1fr}.pulse-player{grid-template-columns:1fr;gap:7px}.pulse-seq{justify-content:flex-start;width:100%}}
"""


def _plain_fact(value):
    return re.sub(r"\*\*", "", str(value or "")).strip()


def _mod_header_editorial(payload):
    a = _esc(payload.get("player_a", "?")); b = _esc(payload.get("player_b", "?"))
    ra = _d(payload.get("ranking_a")); rb = _d(payload.get("ranking_b"))
    rank_a = f"#{ra.get('rank')}" if ra.get("rank") else ""; rank_b = f"#{rb.get('rank')}" if rb.get("rank") else ""
    fa = _d(payload.get("recent_form_a")); fb = _d(payload.get("recent_form_b"))
    form_a = f"Forma {fa.get('wins')}â€“{fa.get('losses')}" if fa else ""; form_b = f"Forma {fb.get('wins')}â€“{fb.get('losses')}" if fb else ""
    tourn = _esc(payload.get("tournament", "")); tier = _esc(payload.get("tier", "")); surf = _esc(payload.get("surface", ""))
    h = _d(payload.get("h2h")); overall = _d(h.get("overall")) or h
    h2h = f"H2H {overall.get('a_wins',0)}â€“{overall.get('b_wins',0)}" if overall.get("total_matches") else "H2H â€”"
    when = ""
    try:
        when = datetime.fromisoformat(str(payload.get("commence_time_utc", "")).replace("Z", "+00:00")).strftime("%d/%m Â· %H:%M UTC")
    except (TypeError, ValueError):
        pass
    w = _d(payload.get("weather")); weather = []
    if w.get("temp_c") is not None: weather.append(f"{w['temp_c']:.0f}Â°C")
    if w.get("humidity") is not None: weather.append(f"{w['humidity']:.0f}% HR")
    if w.get("wind_kmh") is not None: weather.append(f"vento {w['wind_kmh']:.0f} km/h")
    meta_a = " Â· ".join(str(x) for x in (payload.get("player_a_country"), rank_a, form_a) if x); meta_b = " Â· ".join(str(x) for x in (payload.get("player_b_country"), rank_b, form_b) if x)
    return f'<div class="mh"><div class="mh-kicker">Match Preview Â· {_esc(when)}</div><div class="mh-top"><div><div class="mh-name">{a}</div><div class="mh-sub">{_esc(meta_a)}</div></div><div><div class="mh-vs">VS</div><div class="mh-tourn">{tourn}<br>{tier} Â· {surf}</div></div><div><div class="mh-name b">{b}</div><div class="mh-sub b">{_esc(meta_b)}</div></div></div><div class="mh-context"><div>{_esc(" Â· ".join(weather))}</div><div class="mh-h2h">{h2h}</div><div class="b">{tier} Â· {surf}</div></div></div>'


def _mod_match_intro(result):
    points = [_plain_fact(point) for point in (result.get("key_points") or []) if point]
    return f'<div class="match-intro">{_esc(" ".join(points[:2]))}</div>' if points else ""


def _mod_at_glance(payload):
    a = _esc(payload.get("player_a", "A")); b = _esc(payload.get("player_b", "B")); rows = []
    def add(label, va, vb, higher=True, fmt=str):
        if va is None or vb is None: return
        winner = "a" if (va > vb if higher else va < vb) else "b" if va != vb else None; rows.append((label,fmt(va),fmt(vb),winner))
    ra,rb=_d(payload.get("ranking_a")),_d(payload.get("ranking_b")); add("Ranking",ra.get("rank"),rb.get("rank"),False,lambda v:f"#{v}")
    fa,fb=_d(payload.get("recent_form_a")),_d(payload.get("recent_form_b")); add("Forma recente",100*fa.get("wins",0)/fa.get("matches") if fa.get("matches") else None,100*fb.get("wins",0)/fb.get("matches") if fb.get("matches") else None,True,lambda v:f"{v:.0f}%")
    surface=payload.get("surface"); sa=_d(_d(payload.get("surface_stats_a")).get(surface)); sb=_d(_d(payload.get("surface_stats_b")).get(surface)); add(f"Em {surface}" if surface else "SuperfÃ­cie",100*sa.get("wins",0)/sa.get("matches") if sa.get("matches") else None,100*sb.get("wins",0)/sb.get("matches") if sb.get("matches") else None,True,lambda v:f"{v:.0f}%")
    fta,ftb=_d(payload.get("fatigue_signal_a")),_d(payload.get("fatigue_signal_b")); add("Carga Â· sets 7d",fta.get("sets_last_7d"),ftb.get("sets_last_7d"),False)
    pa,pb=_d(payload.get("pressure_profile_a")),_d(payload.get("pressure_profile_b")); add("1.Âº serviÃ§o ganho",pa.get("first_serve_won_pct"),pb.get("first_serve_won_pct"),True,lambda v:f"{v:.0f}%")
    da,db=_d(payload.get("deciding_set_stats_a")),_d(payload.get("deciding_set_stats_b")); add("Sets decisivos",da.get("deciding_set_win_pct"),db.get("deciding_set_win_pct"),True,lambda v:f"{v:.0f}%")
    if not rows: return ""
    rendered="".join(f'<div class="glance-row"><div class="glance-a {"glance-win" if w=="a" else ""}">{_esc(va)}</div><div class="glance-label">{_esc(label)}</div><div class="glance-b {"glance-win" if w=="b" else ""}">{_esc(vb)}</div></div>' for label,va,vb,w in rows[:7])
    return f'<div class="section-title">O jogo num relance</div><div class="glance"><div class="glance-head"><span>{a}</span><span></span><span>{b}</span></div>{rendered}</div>'


def _mod_match_keys(payload, div):
    """Fatores-chave sintéticos: dimensão + jogador com ascendente."""
    fatores = (div or {}).get("fatores_chave") or []
    if not fatores:
        # Fallback factual para relatórios sem mercado/divergência calculada.
        nomes = {
            "ranking": "Ranking", "forma_recente": "Forma recente",
            "piso": "Superfície", "h2h": "Confronto direto",
            "h2h_piso": "H2H no piso", "frescura": "Frescura",
            "servico_carreira": "Serviço", "servico_recente": "Serviço recente",
        }
        for key, feature in (payload.get("features") or {}).items():
            if key not in nomes or not isinstance(feature, dict):
                continue
            leader = feature.get("lider") or feature.get("mais_fresco")
            if leader not in (None, "igual"):
                fatores.append((nomes[key], leader))
    if not fatores:
        return ""
    player_a = str(payload.get("player_a") or "").strip().casefold()
    player_b = str(payload.get("player_b") or "").strip().casefold()
    cards = []
    for name, leader in fatores[:4]:
        leader_key = str(leader or "").strip().casefold()
        side = "a" if leader_key == player_a else "b" if leader_key == player_b else ""
        colour = f' style="color:var(--{side})"' if side else ""
        cards.append(
            f'<div class="fator"><div class="fator-lbl">{_esc(name)}</div>'
            f'<div class="fator-fav"{colour}>▲ {_esc(leader)}</div></div>'
        )
    return f'<div class="section-title">Chaves do confronto</div><div class="fatores">{"".join(cards)}</div>'


def _mod_market_provenance(payload):
    parts = []
    if payload.get("odds_source"):
        parts.append(f"Fonte: {_esc(payload['odds_source'])}")
    if payload.get("odds_captured_at_utc"):
        parts.append(f"captadas em {_esc(payload['odds_captured_at_utc'])}")
    return f'<div class="mh-odds-meta">{" Â· ".join(parts)}</div>' if parts else ""


def _mod_h2h_timeline(payload):
    matches = payload.get("h2h_history") or []
    if not matches:
        return _mod_h2h(payload)
    rows = []
    player_a = str(payload.get("player_a") or "").strip()
    player_b = str(payload.get("player_b") or "").strip()
    for match in matches:
        year = str(match.get("date") or "")[:4] or "-"
        tournament = match.get("tournament") or "Torneio nao identificado"
        result = match.get("result") or "resultado indisponivel"
        winner = match.get("winner_name") or "Vencedor nao identificado"
        winner_key = str(winner).strip().casefold()
        winner_cls = "a" if winner_key == player_a.casefold() else "b" if winner_key == player_b.casefold() else ""
        surface = f" | {match['surface']}" if match.get("surface") else ""
        rows.append(
            f'<div class="history-row"><div class="history-meta">{_esc(year)} | {_esc(tournament)}{_esc(surface)}</div>'
            f'<div class="history-result"><b class="history-winner {winner_cls}">{_esc(winner)}</b>'
            f'<span>{_esc(result)}</span></div></div>'
        )
    h2h = _d(payload.get("h2h")); overall = _d(h2h.get("overall")) or h2h
    aw = overall.get("a_wins", 0); bw = overall.get("b_wins", 0)
    total = overall.get("total_matches", aw + bw)
    if not total:
        player_a = player_a.casefold()
        player_b = player_b.casefold()
        winners = [str(match.get("winner_name") or "").strip().casefold() for match in matches]
        aw = sum(winner == player_a for winner in winners)
        bw = sum(winner == player_b for winner in winners)
        total = aw + bw
    score_bar = _fd_bar("h2h", {
        # Não esbater a cor por amostra pequena: a contagem e a lista de
        # encontros já tornam o tamanho da amostra explícito.
        "valor_a": aw, "valor_b": bw,
    })
    score = ""
    if score_bar:
        score = (
            f'<div class="history-score"><div class="history-score-names">'
            f'<span>{_esc(payload.get("player_a", "A"))}</span>'
            f'<span>{_esc(payload.get("player_b", "B"))}</span></div>{score_bar}</div>'
        )
    return (f'<div class="card history-card"><h3>Confronto Direto</h3>'
            f'{score}{"".join(rows)}</div>')


def _mod_recent_pulse(payload):
    def sequence(items):
        letters = []
        for match in items or []:
            won = match.get("won")
            if won is None:
                continue
            letter = "W" if won else "L"
            cls = "win" if won else "loss"
            letters.append(f'<span class="pulse-{cls}">{letter}</span>')
        return "".join(letters) or '<span class="pulse-empty">Sem dados</span>'
    a = _esc(payload.get("player_a", "A")); b = _esc(payload.get("player_b", "B"))
    seq_a = sequence(payload.get("recent_history_a")); seq_b = sequence(payload.get("recent_history_b"))
    if "pulse-empty" in seq_a and "pulse-empty" in seq_b:
        return ""
    return (f'<div class="card pulse-card"><h3>Pulso Recente | &#218;ltimos 10</h3>'
            f'<div class="pulse-player"><span>{a}</span><div class="pulse-seq">{seq_a}</div></div>'
            f'<div class="pulse-player"><span>{b}</span><div class="pulse-seq">{seq_b}</div></div></div>')


def _mod_recent_form_merged(payload):
    """Sequencia W/L e resumo percentual numa unica bubble de forma."""
    a = _esc(payload.get("player_a", "A")); b = _esc(payload.get("player_b", "B"))

    def sequence(items):
        letters = []
        for match in items or []:
            won = match.get("won")
            if won is None:
                continue
            letter = "W" if won else "L"
            cls = "win" if won else "loss"
            letters.append(f'<span class="pulse-{cls}">{letter}</span>')
        return "".join(letters)

    seq_a = sequence(payload.get("recent_history_a"))
    seq_b = sequence(payload.get("recent_history_b"))
    sequence_html = ""
    if seq_a or seq_b:
        sequence_html = (
            f'<div class="pulse-player"><span>{a}</span><div class="pulse-seq">{seq_a}</div></div>'
            f'<div class="pulse-player"><span>{b}</span><div class="pulse-seq">{seq_b}</div></div>'
        )

    fa = _d(payload.get("recent_form_a")); fb = _d(payload.get("recent_form_b"))
    bars = ""
    if fa.get("matches") and fb.get("matches"):
        pca = round(100 * fa.get("wins", 0) / fa["matches"])
        pcb = round(100 * fb.get("wins", 0) / fb["matches"])
        label_a = f"{fa.get('wins')}-{fa.get('losses')} | {pca}"
        label_b = f"{fb.get('wins')}-{fb.get('losses')} | {pcb}"
        bars = (
            '<div class="pulse-form-bars">'
            f'{_barra_cmp(a, label_a, COLORS_V2["a"], pca, "%")}'
            f'{_barra_cmp(b, label_b, COLORS_V2["b"], pcb, "%")}'
            '</div>'
        )
    if not sequence_html and not bars:
        return ""
    return (f'<div class="card pulse-card merged-form-card">'
            f'<h3>Forma Recente | &#218;ltimos 10</h3>{sequence_html}{bars}</div>')


def _mod_header_editorial_clean(payload):
    a = _esc(payload.get("player_a", "?")); b = _esc(payload.get("player_b", "?"))
    ra = _d(payload.get("ranking_a")); rb = _d(payload.get("ranking_b"))
    rank_a = f"#{ra.get('rank')}" if ra.get("rank") else ""; rank_b = f"#{rb.get('rank')}" if rb.get("rank") else ""
    fa = _d(payload.get("recent_form_a")); fb = _d(payload.get("recent_form_b"))
    form_a = f"Forma {fa.get('wins')}-{fa.get('losses')}" if fa else ""; form_b = f"Forma {fb.get('wins')}-{fb.get('losses')}" if fb else ""
    tourn = _esc(payload.get("tournament", "")); tier = _esc(payload.get("tier", "")); surf = _esc(payload.get("surface", ""))
    h = _d(payload.get("h2h")); overall = _d(h.get("overall")) or h
    h2h = f"H2H {overall.get('a_wins',0)}-{overall.get('b_wins',0)}" if overall.get("total_matches") else "H2H -"
    when = ""
    try:
        when = datetime.fromisoformat(str(payload.get("commence_time_utc", "")).replace("Z", "+00:00")).strftime("%d/%m | %H:%M UTC")
    except (TypeError, ValueError):
        pass
    w = _d(payload.get("weather")); weather = []
    if w.get("temp_c") is not None: weather.append(f"{w['temp_c']:.0f} C")
    if w.get("humidity") is not None: weather.append(f"{w['humidity']:.0f}% HR")
    if w.get("wind_kmh") is not None: weather.append(f"vento {w['wind_kmh']:.0f} km/h")
    meta_a = " | ".join(str(x) for x in (payload.get("player_a_country"), rank_a, form_a) if x); meta_b = " | ".join(str(x) for x in (payload.get("player_b_country"), rank_b, form_b) if x)
    return f'<div class="mh"><div class="mh-kicker">Match Preview | {_esc(when)}</div><div class="mh-top"><div><div class="mh-name">{a}</div><div class="mh-sub">{_esc(meta_a)}</div></div><div><div class="mh-vs">VS</div><div class="mh-tourn">{tourn}<br>{tier} | {surf}</div></div><div><div class="mh-name b">{b}</div><div class="mh-sub b">{_esc(meta_b)}</div></div></div><div class="mh-context"><div>{_esc(" | ".join(weather))}</div><div class="mh-h2h">{h2h}</div><div class="b">{tier} | {surf}</div></div></div>'


def _mod_at_glance_clean(payload):
    a = _esc(payload.get("player_a", "A")); b = _esc(payload.get("player_b", "B")); rows = []
    def add(label, va, vb, higher=True, fmt=str):
        if va is None or vb is None: return
        winner = "a" if (va > vb if higher else va < vb) else "b" if va != vb else None; rows.append((label,fmt(va),fmt(vb),winner))
    ra,rb=_d(payload.get("ranking_a")),_d(payload.get("ranking_b")); add("Ranking",ra.get("rank"),rb.get("rank"),False,lambda v:f"#{v}")
    fa,fb=_d(payload.get("recent_form_a")),_d(payload.get("recent_form_b")); add("Forma recente",100*fa.get("wins",0)/fa.get("matches") if fa.get("matches") else None,100*fb.get("wins",0)/fb.get("matches") if fb.get("matches") else None,True,lambda v:f"{v:.0f}%")
    surface=payload.get("surface"); sa=_d(_d(payload.get("surface_stats_a")).get(surface)); sb=_d(_d(payload.get("surface_stats_b")).get(surface)); add(f"Em {surface}" if surface else "Superficie",100*sa.get("wins",0)/sa.get("matches") if sa.get("matches") else None,100*sb.get("wins",0)/sb.get("matches") if sb.get("matches") else None,True,lambda v:f"{v:.0f}%")
    fta,ftb=_d(payload.get("fatigue_signal_a")),_d(payload.get("fatigue_signal_b")); add("Carga | sets 7d",fta.get("sets_last_7d"),ftb.get("sets_last_7d"),False)
    pa,pb=_d(payload.get("pressure_profile_a")),_d(payload.get("pressure_profile_b")); add("1st servico ganho",pa.get("first_serve_won_pct"),pb.get("first_serve_won_pct"),True,lambda v:f"{v:.0f}%")
    da,db=_d(payload.get("deciding_set_stats_a")),_d(payload.get("deciding_set_stats_b")); add("Sets decisivos",da.get("deciding_set_win_pct"),db.get("deciding_set_win_pct"),True,lambda v:f"{v:.0f}%")
    if not rows: return ""
    rendered="".join(f'<div class="glance-row"><div class="glance-a {"glance-win" if w=="a" else ""}">{_esc(va)}</div><div class="glance-label">{_esc(label)}</div><div class="glance-b {"glance-win" if w=="b" else ""}">{_esc(vb)}</div></div>' for label,va,vb,w in rows[:7])
    return f'<div class="section-title">O jogo num relance</div><div class="glance"><div class="glance-head"><span>{a}</span><span></span><span>{b}</span></div>{rendered}</div>'


def build_report_html_v2(payload, result, calcular_divergencia_fn, mvm_fn=None):
    """Monta a página V2 completa. Recebe a função do motor (índice de
    evidência) de fora, para reaproveitar o report_html original.
    Arquitetura: Decisão -> explicação -> evidência -> detalhe."""
    a = payload.get("player_a", "?"); b = payload.get("player_b", "?")
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
    partes.append(_mod_leitura(payload, div, estado, result))
    # NOVO (18/08/2026, a pedido): Veredicto de mercado — bloco compacto e
    # objetivo, logo a seguir à Leitura, antes de tudo o resto.
    partes.append(_mod_market_verdict(payload, div))
    # NOVO (18/08/2026, a pedido): Mapa de Ações movido para logo a seguir
    # à Leitura (onde aparece "Alinhamento Forte") — é o que deve chamar a
    # atenção primeiro; o resto do relatório (mercado, fatores detalhados)
    # fica disponível a seguir para quem quiser aprofundar. Antes vinha
    # muito mais abaixo, depois de toda a análise detalhada.
    partes.append(_mod_action_map(payload, div, result))
    if chave not in ("sem_odds", "erro"):
        partes.append('<div class="market-section"><div class="section-title">Leitura do mercado</div>')
        partes.append(_mod_mercado_vs_sinal(payload, div))
        partes.append(_mod_indicative_odds(payload))
        partes.append(_mod_market_provenance(payload))
        partes.append(_mod_mercados(payload, div))
        partes.append('</div>')
    # 2. Leitura do jogo (sempre — muda conforme estado)
    partes.append(_mod_match_intro(result))
    partes.append(_mod_at_glance_clean(payload))
    partes.append(_mod_match_keys(payload, div))
    partes.append(_mod_data_quality_notice(payload))

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
        partes.append(_mod_photo_credits(payload))
        partes.append('</div>')
        return _pagina(a, b, "".join(partes))

    # Os cenários vivem no Mapa de Ações como gatilhos condicionais.
    # 4. Mercado e indicadores (só com odds)
    # 5-9. Evidência. Forma, Serviço, Carga e H2H vivem dentro do Mapa de
    # Forças, evitando duplicar na página principal fatores já resumidos nos
    # chips do topo. Cenários decisivos mantém-se visível quando diferencia.
    # Fatores detalhados (TODOS, não só o top-3/4) — colapsável, sempre que
    # houver motor calculado, independente do estado (mesmo "eficiente"
    # beneficia de mostrar porque é eficiente: tudo empatado/sem dados).
    _extras_mapa = (
        f'{_mod_h2h_timeline(payload)}{_mod_recent_form_merged(payload)}'
        f'{_mod_forma_ajustada(payload)}'
        f'{_mod_servico(payload)}'
    )
    _tail_mapa = (
        '<div class="force-map-tail"><div class="load-tail">'
        f'{_mod_fadiga(payload)}{_mod_transparencia_pesos(payload, div)}'
        '</div></div>'
    )
    partes.append(_mod_fatores_detalhados(
        payload, div, extras_html=_extras_mapa, tail_html=_tail_mapa
    ))
    partes.append(_mod_photo_credits(payload))
    partes.append('</div>')
    return _pagina(a, b, "".join(partes))


def _impact_toggle_script():
    return """
<script>
(() => {
  const NS = "http://www.w3.org/2000/svg";
  function drawTrace(card) {
    const box = card.querySelector(".factor-lines");
    const svg = card.querySelector(".impact-trace");
    if (!box || !svg || !card.classList.contains("impact-mode")) return;
    const rect = box.getBoundingClientRect();
    const rows = [...box.querySelectorAll(".fd-linha[data-impact-side]")]
      .filter(row => row.dataset.impactSide && Number(row.dataset.impactPct) > 0);
    const points = rows.map(row => {
      const rr = row.getBoundingClientRect();
      const direction = row.dataset.impactSide === "a" ? -1 : 1;
      return {
        x: rect.width * (.5 + direction * .42 * Number(row.dataset.impactPct) / 100),
        y: rr.top - rect.top + rr.height / 2
      };
    });
    svg.setAttribute("viewBox", `0 0 ${rect.width} ${rect.height}`);
    const path = svg.querySelector("path");
    const dots = svg.querySelector("g");
    if (!points.length) { path.setAttribute("d", ""); dots.replaceChildren(); return; }
    let d = `M ${points[0].x} ${points[0].y}`;
    for (let i = 1; i < points.length; i++) {
      const prev = points[i - 1], cur = points[i], midY = (prev.y + cur.y) / 2;
      d += ` C ${prev.x} ${midY}, ${cur.x} ${midY}, ${cur.x} ${cur.y}`;
    }
    path.setAttribute("d", d);
    dots.replaceChildren(...points.map(point => {
      const dot = document.createElementNS(NS, "circle");
      dot.setAttribute("cx", point.x); dot.setAttribute("cy", point.y); dot.setAttribute("r", 3.5);
      return dot;
    }));
  }
  document.querySelectorAll(".factor-bars-card").forEach(card => {
    const toggle = card.querySelector(".impact-switch input");
    if (!toggle) return;
    toggle.addEventListener("change", () => {
      card.classList.toggle("impact-mode", toggle.checked);
      requestAnimationFrame(() => drawTrace(card));
    });
  });
  window.addEventListener("resize", () => {
    document.querySelectorAll(".factor-bars-card.impact-mode").forEach(drawTrace);
  });
})();
</script>"""


def _pagina(a, b, corpo):
    hoje = datetime.now(timezone.utc).strftime("%d/%m/%Y")
    return f"""<!DOCTYPE html>
<html lang="pt"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(a)} vs {_esc(b)}</title>
<style>{_css()}{_css_editorial()}</style></head>
<body>
<nav class="report-nav" aria-label="Navegação do relatório">
  <a href="{_esc(SITE_BASE_URL)}/">← Todos os relatórios</a>
</nav>
<main>
<h1 class="sr-only">{_esc(a)} vs {_esc(b)}</h1>
{corpo}
<div class="wrap"><div class="foot">Gerado em {hoje} · Análise informativa, não recomendação de aposta.</div></div>
</main>
{_impact_toggle_script()}
</body></html>"""
