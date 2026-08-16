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
    "comeback_set1": 7,        # MÉDIO-ALTO — recuperação após perder o 1º set, relevante para observação em live (14/08/2026, a pedido)
    "fadiga": 4,               # MÉDIO-BAIXO — sobe se último jogo foi longo
    "servico_recente": 5,      # MÉDIO — últimos 2 jogos (14/08/2026, a pedido)
    "servico_carreira": 3,     # MÉDIO-BAIXO — desceu (4->3), agora coexiste com a versão recente
    "meteo": 1,                # BAIXO — raramente decisiva
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
        "servico_recente": "serviço (2 jogos)", "servico_carreira": "serviço (carreira)", "velocidade_piso": "velocidade do piso", "indoor_outdoor": "indoor/outdoor", "tiebreak": "tie-break", "comeback_set1": "recuperação pós-1º set", "sazonal": "padrão sazonal", "meteo": "meteorologia",
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
    FAMILIAS = {
        "forca_base": {"servico_recente", "servico_carreira", "forma_recente"},
        "matchup": {"matchup_maos", "h2h", "h2h_piso"},
        "superficie": {"piso", "velocidade_piso", "indoor_outdoor"},
        "resiliencia": {"recuperacao_sets", "tiebreak", "comeback_set1"},
        "ranking_fam": {"ranking", "ranking_evolucao"},
        "contexto": {"fadiga", "lesao", "meteo"},
    }
    # teto de peso efetivo por família (a família "força base", muito
    # correlacionada, é a mais limitada; matchup/resiliência são sinais mais
    # distintos e específicos do confronto, logo teto mais alto).
    CAP_FAMILIA = {"forca_base": 10, "matchup": 18, "superficie": 16, "resiliencia": 17, "ranking_fam": 9, "contexto": 6}

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
    # Guardar no estado de cada fator o impacto efetivo usado pelo motor,
    # depois dos ajustes de forca, confianca da amostra e caps por familia.
    # O relatorio usa estes valores no modo "Impacto no matchup".
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
  font-weight:600; color:var(--text); list-style:none; }}
details.more>summary::-webkit-details-marker {{ display:none; }}
details.more>summary::before {{ content:"▸ "; }}
details.more[open]>summary::before {{ content:"▾ "; }}
details.more .more-body {{ padding:0 16px 16px; }}
.more-hint {{ color:var(--dim); font-size:11px; font-weight:400; margin-left:6px; }}

/* Mapa de Forças: destaque visual (feedback de teste, 13/08/2026 —
   "devia ter mais visibilidade, ligeiramente maior e com outra cor, para
   mostrar que é o único elemento carregável com info relevante") */
details.mais-forcas {{ border:1.5px solid var(--amber);
  background:linear-gradient(180deg, rgba(217,164,65,.10), var(--surface) 45%); }}
details.mais-forcas>summary {{ padding:16px 18px; font-size:14px; color:var(--amber); }}
details.mais-forcas>summary::before {{ color:var(--amber); }}
details.mais-forcas .more-hint {{ color:var(--amber); opacity:.75; }}

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
  {f'<div class="mh-odds-meta">{odds_meta}</div>' if odds_meta else ''}
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
    "piso", "recuperacao_sets", "tiebreak", "comeback_set1", "matchup_maos", "servico_recente", "servico_carreira", "fadiga", "lesao",
]


# Fatores onde valor_a/valor_b são percentagens diretamente comparáveis
# (maior = melhor) — mostram "XX% – YY%" e barra proporcional direta.
_FD_FACTORS_PCT = {"piso", "velocidade_piso", "forma_recente", "servico_recente", "servico_carreira", "indoor_outdoor", "tiebreak", "comeback_set1", "sazonal",
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

    linhas = []
    for chave in _FACTOR_ORDER:
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
    return (f'<details class="more mais-forcas"><summary>Mapa de Forças{total_tag}'
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

    def linha(nome, market, quality, momentum):
        bits = []
        if market:
            delta = market.get("performance_vs_market")
            sinal = "+" if isinstance(delta, (int, float)) and delta > 0 else ""
            bits.append(
                f"{market.get('actual_wins')} vitórias reais vs "
                f"{market.get('expected_wins')} esperadas ({sinal}{delta}) · "
                f"n={market.get('matches')}"
            )
        if quality:
            bits.append(
                f"ranking médio dos adversários #{quality.get('avg_opponent_rank')} · "
                f"n={quality.get('matches')}"
            )
        if momentum:
            delta = momentum.get("delta_pp")
            sinal = "+" if isinstance(delta, (int, float)) and delta > 0 else ""
            bits.append(
                f"piso: {momentum.get('recent_win_pct')}% recente "
                f"vs {momentum.get('career_win_pct')}% carreira "
                f"({sinal}{delta} p.p.; n={momentum.get('recent_matches')})"
            )
        return (f'<div class="cmp-row"><div class="cmp-name">{nome}</div>'
                f'<div style="grid-column:2 / -1;color:var(--dim);font-size:12px">'
                f'{_esc(" · ".join(bits))}</div></div>') if bits else ""

    return (
        '<div class="card"><h3>Forma ajustada ao mercado</h3>'
        '<div class="cmp-lbl">Resultados históricos comparados com as odds disponíveis</div>'
        f'{linha(a, ma, qa, sa)}{linha(b, mb, qb, sb)}</div>'
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
    """Módulo 6: Serviço/resposta com DELTAS explícitos (auditoria #7)."""
    sa = _d(payload.get("serve_return_stats_a"))
    sb = _d(payload.get("serve_return_stats_b"))
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
    fa = _d(payload.get("fatigue_signal_a"))
    fb = _d(payload.get("fatigue_signal_b"))
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
.pulse-player{display:grid;grid-template-columns:minmax(120px,.7fr) 1fr;gap:14px;align-items:center;padding:9px 0;border-top:1px solid var(--line);font-size:13px}.pulse-player:first-of-type{border-top:0}.pulse-seq{display:flex;justify-content:flex-end;gap:5px;flex-wrap:wrap}.pulse-seq span{display:inline-grid;place-items:center;width:25px;height:25px;border-radius:6px;font-size:11px;font-weight:800}.pulse-win{background:rgba(199,255,61,.13);color:var(--mint);border:1px solid rgba(199,255,61,.35)}.pulse-loss{background:rgba(224,108,91,.12);color:#f29b8d;border:1px solid rgba(224,108,91,.3)}.pulse-empty{width:auto!important;padding:0 8px;color:var(--dim)}.analytics-title{margin:18px 0 10px;padding:10px 12px;border:1px solid var(--b);border-radius:10px;background:rgba(52,200,255,.06);color:var(--b);font-size:12px;text-transform:uppercase;letter-spacing:1px}
.pulse-form-bars{margin-top:10px;padding-top:12px;border-top:1px solid var(--line)}
.factor-bars-card{border-color:var(--line);background:linear-gradient(180deg,rgba(74,163,223,.08),var(--surface) 30%)}
.factor-bars-card .fd-linha{padding:9px 11px;background:rgba(74,163,223,.055);border-bottom-color:rgba(120,207,255,.14)}.factor-bars-card .fd-linha:first-of-type{border-radius:8px 8px 0 0}.factor-bars-card .fd-linha:last-child{border-radius:0 0 8px 8px}
.factor-bars-head{display:flex;justify-content:space-between;gap:16px;align-items:center;margin-bottom:12px}.factor-bars-head h3{color:var(--a);margin:0}.impact-toggle{display:flex;align-items:center;gap:7px;color:var(--dim);font-size:10px}.impact-switch{position:relative;width:42px;height:24px;flex:0 0 auto}.impact-switch input{position:absolute;opacity:0;pointer-events:none}.impact-slider{position:absolute;inset:0;border-radius:999px;background:var(--surface2);border:1px solid var(--line);cursor:pointer;transition:.2s}.impact-slider::before{content:"";position:absolute;width:18px;height:18px;left:2px;top:2px;border-radius:50%;background:#fff;box-shadow:0 2px 5px rgba(0,0,0,.35);transition:.2s}.impact-switch input:checked+.impact-slider{background:rgba(74,163,223,.55);border-color:var(--a)}.impact-switch input:checked+.impact-slider::before{transform:translateX(18px)}.impact-switch input:focus-visible+.impact-slider{outline:2px solid var(--a);outline-offset:2px}
.factor-lines{position:relative}.fd-impact-bar,.impact-trace{display:none}.factor-bars-card.impact-mode{background:#090e13;border-color:#213445}.factor-bars-card.impact-mode .factor-lines{background:#070b0f;border-radius:9px}.factor-bars-card.impact-mode .fd-linha{background:rgba(8,16,23,.82);border-bottom-color:rgba(110,145,168,.12)}.factor-bars-card.impact-mode .fd-nome,.factor-bars-card.impact-mode .fd-val{color:#748493!important}.factor-bars-card.impact-mode .fd-nota{color:#586875}.factor-bars-card.impact-mode .fd-bar{display:none}.factor-bars-card.impact-mode .fd-impact-bar{display:block;position:relative;height:22px;border-radius:5px;overflow:hidden;background:#111a22}.fd-impact-bar::after{content:"";position:absolute;left:50%;top:0;bottom:0;width:1px;background:rgba(255,255,255,.32);z-index:2}.fd-impact-fill{position:absolute;top:0;bottom:0;z-index:1}.fd-impact-fill.a{right:50%;background:var(--a)}.fd-impact-fill.b{left:50%;background:var(--b)}.fd-impact-value{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);z-index:4;color:#dce8f0;font-size:10px;font-weight:700;background:rgba(5,9,12,.68);padding:1px 5px;border-radius:4px}.factor-bars-card.impact-mode .impact-trace{display:block;position:absolute;inset:0;width:100%;height:100%;overflow:visible;pointer-events:none;z-index:5}.impact-trace path{fill:none;stroke:#d5f4ff;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;filter:drop-shadow(0 0 4px rgba(120,207,255,.8))}.impact-trace circle{fill:#f3fbff;stroke:#20394a;stroke-width:1.5}.factor-bars-card.impact-mode .fd-linha[data-impact-side=""]{opacity:.42}
.factor-bars-card.impact-mode .fd-linha[data-impact-side="a"] .fd-val{color:#78cfff!important}.factor-bars-card.impact-mode .fd-linha[data-impact-side="b"] .fd-val{color:#ffb47f!important}.factor-bars-card.impact-mode .fd-nota{color:#586875!important}
@media(max-width:640px){.factor-bars-head{align-items:flex-start;flex-direction:column}.impact-toggle{width:100%;justify-content:flex-end}}
.history-score{padding:0 0 12px;margin-bottom:2px}.history-score-names{display:flex;justify-content:space-between;gap:12px;color:var(--dim);font-size:11px;margin-bottom:5px}
@media(max-width:640px){.mh{padding:18px 14px}.mh-name{font-size:20px}.mh-top{gap:7px}.mh-tourn{font-size:9px}.mh-context{font-size:10px}.keys{grid-template-columns:1fr}.glance-head,.glance-row{grid-template-columns:1fr 100px 1fr}}
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
    if chave not in ("sem_odds", "erro"):
        partes.append('<div class="market-section"><div class="section-title">Leitura do mercado</div>')
        partes.append(_mod_mercado_vs_sinal(payload, div))
        partes.append(_mod_market_provenance(payload))
        partes.append(_mod_mercados(payload, div))
        partes.append('</div>')
    # 2. Leitura do jogo (sempre — muda conforme estado)
    partes.append(_mod_match_intro(result))
    partes.append(_mod_at_glance_clean(payload))
    partes.append(_mod_match_keys(payload, div))

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

    # 3. Fatores principais (se há divergência)
    partes.append(_mod_cenarios(payload))
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
        f'<div class="force-map-tail"><div class="pressure-tail">{_mod_pressao(payload)}</div>'
        f'<div class="load-tail">{_mod_fadiga(payload)}</div></div>'
    )
    partes.append(_mod_fatores_detalhados(
        payload, div, extras_html=_extras_mapa, tail_html=_tail_mapa
    ))
    # Veredicto (se há)
    partes.append(_mod_veredicto(result))
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
