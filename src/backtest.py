"""
Backtest honesto dos sinais do bot (H2H/forma/piso) contra odds
históricas reais — para responder a uma pergunta concreta: "quando o
nosso sinal discorda do mercado, quem tem mais razão?"

O QUE ISTO NÃO FAZ (de propósito):
- Não estima uma "probabilidade calibrada" — isso exigiria um modelo
  estatístico a sério (regressão logística, Elo, etc.), treinado e
  validado como deve ser. Fingir uma probabilidade sem esse trabalho
  seria dar uma falsa sensação de rigor.
- Não simula apostas nem calcula ROI/banca/Kelly — isso pressupõe que já
  sabemos que há vantagem, que é exatamente o que este script existe
  para verificar primeiro.
- Não decide "apostar ou não" — só mede, de forma honesta, se os sinais
  que já calculamos todos os dias (H2H, forma, piso) tendem a acertar
  mais ou menos do que o mercado, nos casos em que divergem dele.

METODOLOGIA (para evitar look-ahead bias, o erro mais comum em backtests):
Para cada jogo histórico com odds, o H2H/forma/piso são calculados
usando SÓ jogos anteriores à data desse jogo — nunca informação que só
existiria depois. Isto reutiliza as mesmas funções (compute_h2h,
compute_recent_form, compute_surface_stats) que o bot usa em produção,
só que aplicadas sobre uma fatia do histórico cortada no tempo certo.

FONTE DE ODDS HISTÓRICAS: tennis-data.co.uk (grátis, documentada, a
mesma que já usávamos como fonte de cruzamento). Formato real confirmado:
colunas Winner, Loser, WRank, LRank, Surface, Date, e várias colunas de
odds por bookmaker (B365W/B365L, PSW/PSL, AvgW/AvgL, MaxW/MaxL — varia
por ano, por isso o código deteta o que existir).

Corre via: python -m src.backtest
(script de análise pontual — não faz parte da execução diária do bot)
"""

from __future__ import annotations

import io
import math
import os
from datetime import datetime, timezone

import pandas as pd
import requests

from . import fetch_data
from .config import SURFACES

REQUEST_TIMEOUT = 20
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

# Anos a incluir no backtest. Evita o ano corrente (dados incompletos a
# meio da época) — ajusta se quiseres incluir mais/menos anos.
BACKTEST_YEARS = list(range(2015, 2026))

# Ordem de preferência das colunas de odds — a primeira que existir e
# tiver valor numérico válido é usada. Pinnacle (PS) é considerada a
# "sharp book" de referência na literatura de apostas; Avg é a média do
# mercado; B365 é o fallback mais comum em anos mais antigos.
ODDS_COLUMN_PREFERENCE = [("PSW", "PSL"), ("AvgW", "AvgL"), ("B365W", "B365L"), ("MaxW", "MaxL")]

# Edge mínimo (em pontos percentuais de win-rate) para contar como
# "o nosso sinal favorece claramente um jogador" — abaixo disto,
# consideramos o sinal demasiado fraco/ruído para contar na análise de
# divergência com o mercado.
MIN_EDGE_TO_COUNT = 5.0

# IMPORTANTE: a TennisMyLife regista 'tourney_date' como a data de INÍCIO
# do torneio, não a data exata de cada jogo. Para rondas avançadas (semis,
# final), um filtro simples de "< match_date" pode deixar passar jogos do
# MESMO torneio — incluindo, no limite, informação próxima ou sobreposta
# ao próprio jogo que estamos a tentar prever. Esta margem de segurança
# (dias) garante que só usamos histórico de torneios claramente anteriores,
# nunca o próprio torneio em avaliação. 21 dias cobre com folga a duração
# de qualquer torneio ATP (a maioria dura 1-2 semanas).
LEAKAGE_SAFETY_BUFFER_DAYS = 21


def _max_drawdown(returns: list[float]) -> float:
    equity = peak = drawdown = 0.0
    for result in returns:
        equity += result
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def _wilson_interval(wins: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total <= 0:
        return (0.0, 0.0)
    p = wins / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denominator
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def _return_summary(returns: list[float]) -> dict:
    total = len(returns)
    profit = sum(returns)
    return {"bets": total, "profit_units": profit,
            "roi_pct": 100 * profit / total if total else 0.0,
            "max_drawdown_units": _max_drawdown(returns)}


def _build_surname_index(history: pd.DataFrame) -> dict:
    """
    Índice (inicial_do_primeiro_nome, apelido_normalizado) -> lista de
    nomes completos que correspondem, a partir do histórico da
    TennisMyLife ('Primeiro [Nomes do meio] Apelido'). Usado para ligar
    ao formato do tennis-data.co.uk ('Apelido Inicial.').
    """
    names = set()
    if "winner_name" in history.columns:
        names.update(history["winner_name"].dropna().unique())
    if "loser_name" in history.columns:
        names.update(history["loser_name"].dropna().unique())

    index: dict = {}
    for full_name in names:
        tokens = str(full_name).split()
        if len(tokens) < 2:
            continue
        first_initial = fetch_data._normalize_name(tokens[0])[:1]
        surname_norm = fetch_data._normalize_name(" ".join(tokens[1:]))
        key = (first_initial, surname_norm)
        index.setdefault(key, []).append(full_name)
    return index


def _resolve_tennisdata_name(name: str, surname_index: dict):
    """
    Converte um nome no formato 'Apelido Inicial.' (tennis-data.co.uk)
    para o nome completo tal como aparece na TennisMyLife, usando o
    índice de apelido+inicial. None se não encontrar exatamente UMA
    correspondência (ambiguidade == preferimos não arriscar).
    """
    name = str(name).strip()
    parts = name.rsplit(" ", 1)
    if len(parts) != 2:
        return None
    surname_part, initial_part = parts
    initial = initial_part.rstrip(".").strip().lower()[:1]
    if not initial:
        return None
    surname_norm = fetch_data._normalize_name(surname_part)
    candidates = surname_index.get((initial, surname_norm))
    if candidates and len(candidates) == 1:
        return candidates[0]
    return None


def _fetch_tennisdata_year(year: int):
    """
    Formato real confirmado (27/07/2026): ficheiro Excel, não CSV —
    "{year}/{year}.xlsx" para o ATP.
    """
    url = f"http://www.tennis-data.co.uk/{year}/{year}.xlsx"
    try:
        resp = requests.get(url, headers=_BROWSER_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        df = pd.read_excel(io.BytesIO(resp.content))
        return df
    except Exception as exc:
        print(f"[aviso] tennis-data.co.uk indisponível para {year}: {exc}")
        return None


def _load_all_backtest_years() -> pd.DataFrame:
    frames = []
    for year in BACKTEST_YEARS:
        df = _fetch_tennisdata_year(year)
        if df is not None and not df.empty:
            df["_year"] = year
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    print(f"[info] tennis-data.co.uk: {len(frames)}/{len(BACKTEST_YEARS)} anos carregados, {len(combined)} jogos no total.")
    print(f"[info] colunas disponíveis: {list(combined.columns)}")
    return combined


def _get_odds(row: pd.Series):
    """Devolve (odd_vencedor, odd_perdedor) da primeira fonte de odds disponível e válida, ou None."""
    for winner_col, loser_col in ODDS_COLUMN_PREFERENCE:
        if winner_col in row and loser_col in row:
            try:
                ow, ol = float(row[winner_col]), float(row[loser_col])
                if ow > 1 and ol > 1:  # odds válidas são sempre > 1.0
                    return ow, ol
            except (ValueError, TypeError):
                continue
    return None


def _implied_prob_winner(odd_winner: float, odd_loser: float) -> float:
    """Probabilidade implícita do vencedor, retirando a margem da casa (de-vig)."""
    raw_winner = 1 / odd_winner
    raw_loser = 1 / odd_loser
    return raw_winner / (raw_winner + raw_loser)


def _parse_date(value):
    if isinstance(value, (pd.Timestamp, datetime)):
        dt = value if isinstance(value, datetime) else value.to_pydatetime()
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value).strip(), fmt).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
    return None


def _all_edges(history_before: pd.DataFrame, player_a: str, player_b: str, surface: str) -> dict:
    """
    Devolve um dict com cada edge de win-rate calculado SEPARADAMENTE
    (h2h, form, surface), em pontos percentuais, positivo = favorece
    player_a, mais o 'combined' (média simples dos disponíveis, igual ao
    que já tínhamos). Cada campo é None se não houver dados suficientes
    para esse sinal em concreto — permite testar cada sinal sozinho,
    não só a combinação.
    """
    result: dict = {"h2h": None, "form": None, "surface": None}

    h2h = fetch_data.compute_h2h(history_before, player_a, player_b, surface)
    if h2h and h2h["overall"]["total_matches"] >= 3:
        total = h2h["overall"]["total_matches"]
        result["h2h"] = 100 * (h2h["overall"]["a_wins"] - h2h["overall"]["b_wins"]) / total

    form_a = fetch_data.compute_recent_form(history_before, player_a, 10)
    form_b = fetch_data.compute_recent_form(history_before, player_b, 10)
    if form_a and form_b and form_a["matches"] >= 5 and form_b["matches"] >= 5:
        rate_a = 100 * form_a["wins"] / form_a["matches"]
        rate_b = 100 * form_b["wins"] / form_b["matches"]
        result["form"] = rate_a - rate_b

    surf_a = fetch_data.compute_surface_stats(history_before, player_a)
    surf_b = fetch_data.compute_surface_stats(history_before, player_b)
    if surf_a and surf_b and surface in SURFACES:
        stat_a, stat_b = surf_a.get(surface), surf_b.get(surface)
        if stat_a and stat_b and stat_a["matches"] >= 5 and stat_b["matches"] >= 5:
            rate_a = 100 * stat_a["wins"] / stat_a["matches"]
            rate_b = 100 * stat_b["wins"] / stat_b["matches"]
            result["surface"] = rate_a - rate_b

    available = [v for v in result.values() if v is not None]
    result["combined"] = sum(available) / len(available) if available else None
    return result


def run() -> None:
    output_lines: list[str] = []

    def log(text: str = "") -> None:
        print(text)
        output_lines.append(text)

    log("=== BACKTEST: sinais do bot vs mercado histórico ===\n")

    log("--- A carregar histórico completo (TennisMyLife) ---")
    full_history = fetch_data.get_history("atp")
    if full_history.empty:
        log("[erro] sem histórico disponível — impossível continuar o backtest.")
        return
    full_history["tourney_date"] = pd.to_datetime(full_history["tourney_date"], format="%Y%m%d", errors="coerce")

    log("\n--- A carregar odds históricas (tennis-data.co.uk) ---")
    odds_data = _load_all_backtest_years()
    if odds_data.empty:
        log("[erro] sem dados de odds — impossível continuar o backtest.")
        return

    log("\n--- A construir índice de nomes (apelido + inicial) ---")
    surname_index = _build_surname_index(full_history)
    log(f"[info] índice construído com {len(surname_index)} combinações apelido+inicial.")

    total_rows = len(odds_data)
    usable = 0
    skipped_no_odds = 0
    skipped_no_date = 0
    skipped_no_name_match = 0
    skipped_no_edge = 0

    signal_names = ["h2h", "form", "surface", "combined"]
    stats = {
        name: {
            "market_correct": 0, "market_total": 0,
            "agrees": 0, "disagrees": 0,
            "signal_correct_disagree": 0, "market_correct_disagree": 0,
            "sum_implied_prob_our_pick_disagree": 0.0,
            "returns": [], "year_returns": {},
        }
        for name in signal_names
    }
    baseline_returns = {"market_favorite": [], "ranking": []}

    for _, row in odds_data.iterrows():
        odds = _get_odds(row)
        if odds is None:
            skipped_no_odds += 1
            continue

        match_date = _parse_date(row.get("Date"))
        if match_date is None:
            skipped_no_date += 1
            continue

        winner = str(row.get("Winner", "")).strip()
        loser = str(row.get("Loser", "")).strip()
        surface = str(row.get("Surface", "")).strip()
        if not winner or not loser:
            continue

        resolved_winner = _resolve_tennisdata_name(winner, surname_index)
        resolved_loser = _resolve_tennisdata_name(loser, surname_index)
        if resolved_winner is None or resolved_loser is None:
            skipped_no_name_match += 1
            continue
        winner, loser = resolved_winner, resolved_loser

        # Ponto central do método: só jogos de torneios claramente
        # anteriores — com margem de segurança, para nunca deixar passar
        # informação do próprio torneio em avaliação (ver nota sobre
        # LEAKAGE_SAFETY_BUFFER_DAYS acima).
        cutoff = pd.Timestamp(match_date).tz_localize(None) - pd.Timedelta(days=LEAKAGE_SAFETY_BUFFER_DAYS)
        history_before = full_history[full_history["tourney_date"] < cutoff]
        if history_before.empty:
            continue

        odd_winner, odd_loser = odds
        implied_prob_winner = _implied_prob_winner(odd_winner, odd_loser)
        market_favors_winner = implied_prob_winner > 0.5
        favorite_won = market_favors_winner
        favorite_odd = odd_winner if market_favors_winner else odd_loser
        baseline_returns["market_favorite"].append(favorite_odd - 1 if favorite_won else -1.0)
        try:
            winner_rank, loser_rank = float(row.get("WRank")), float(row.get("LRank"))
            ranking_picked_winner = winner_rank < loser_rank
            ranking_odd = odd_winner if ranking_picked_winner else odd_loser
            baseline_returns["ranking"].append(ranking_odd - 1 if ranking_picked_winner else -1.0)
        except (TypeError, ValueError):
            pass

        # Convenção: player_a = "winner" da fonte histórica, só para
        # calcular os edges com sinal consistente — isto é só para
        # comparar depois quem tinha razão, não implica conhecimento
        # do resultado no cálculo em si (esse usa só history_before).
        edges = _all_edges(history_before, winner, loser, surface)

        any_signal_used = False
        for name in signal_names:
            edge = edges[name]
            if edge is None or abs(edge) < MIN_EDGE_TO_COUNT:
                continue
            any_signal_used = True
            s = stats[name]
            s["market_total"] += 1
            if market_favors_winner:
                s["market_correct"] += 1

            our_signal_favors_winner = edge > 0
            if our_signal_favors_winner == market_favors_winner:
                s["agrees"] += 1
            else:
                s["disagrees"] += 1
                # Probabilidade implícita do NOSSO pick (não do mercado) —
                # é o número certo para comparar, não um "50%" genérico.
                our_pick_implied_prob = implied_prob_winner if our_signal_favors_winner else (1 - implied_prob_winner)
                s["sum_implied_prob_our_pick_disagree"] += our_pick_implied_prob
                picked_odd = odd_winner if our_signal_favors_winner else odd_loser
                bet_return = picked_odd - 1 if our_signal_favors_winner else -1.0
                s["returns"].append(bet_return)
                s["year_returns"].setdefault(match_date.year, []).append(bet_return)
                if our_signal_favors_winner:
                    s["signal_correct_disagree"] += 1
                else:
                    s["market_correct_disagree"] += 1

        if any_signal_used:
            usable += 1
        else:
            skipped_no_edge += 1

    log("\n=== RESULTADOS ===")
    log(f"Jogos totais na fonte de odds: {total_rows}")
    log(f"  Sem odds utilizáveis: {skipped_no_odds}")
    log(f"  Sem data válida: {skipped_no_date}")
    log(f"  Sem correspondência de nome entre as duas fontes: {skipped_no_name_match}")
    log(f"  Sem NENHUM dos 4 sinais com edge suficiente (< {MIN_EDGE_TO_COUNT} p.p.): {skipped_no_edge}")
    log(f"  Jogos usados em pelo menos um sinal: {usable}")
    log("\n--- BASELINES FLAT-STAKE (referência, não estratégia) ---")
    for baseline, returns in baseline_returns.items():
        summary = _return_summary(returns)
        log(f"  {baseline}: n={summary['bets']} ROI={summary['roi_pct']:+.2f}% "
            f"lucro={summary['profit_units']:+.1f}u drawdown={summary['max_drawdown_units']:.1f}u")
    log("  no_bet: n=0 ROI=+0.00% lucro=+0.0u drawdown=0.0u")

    signal_labels = {
        "h2h": "H2H de carreira (sozinho)",
        "form": "Forma recente (sozinho)",
        "surface": "Stats de piso (sozinho)",
        "combined": "Combinado (média dos 3, como antes)",
    }

    for name in signal_names:
        s = stats[name]
        log(f"\n{'=' * 60}")
        log(f"SINAL: {signal_labels[name]}")
        log(f"{'=' * 60}")
        log(f"Jogos com este sinal disponível (edge >= {MIN_EDGE_TO_COUNT} p.p.): {s['market_total']}")
        if s["market_total"] == 0:
            log("  Sem jogos suficientes para este sinal.")
            continue

        log(f"Mercado acertou o vencedor: {s['market_correct']}/{s['market_total']} "
            f"({100 * s['market_correct'] / s['market_total']:.1f}%)")
        log(f"Concorda com o mercado: {s['agrees']}  |  Discorda: {s['disagrees']}")

        if s["disagrees"] > 0:
            pct_signal = 100 * s["signal_correct_disagree"] / s["disagrees"]
            pct_market = 100 * s["market_correct_disagree"] / s["disagrees"]
            avg_implied_prob_our_pick = 100 * s["sum_implied_prob_our_pick_disagree"] / s["disagrees"]
            log(f"  Nos casos de DIVERGÊNCIA — o nosso sinal teve razão: "
                f"{s['signal_correct_disagree']}/{s['disagrees']} ({pct_signal:.1f}%)")
            log(f"  Nos casos de DIVERGÊNCIA — o mercado teve razão:      "
                f"{s['market_correct_disagree']}/{s['disagrees']} ({pct_market:.1f}%)")
            log(f"  Probabilidade IMPLÍCITA média do nosso pick (segundo as odds): {avg_implied_prob_our_pick:.1f}%")
            edge_vs_market = pct_signal - avg_implied_prob_our_pick
            low, high = _wilson_interval(s["signal_correct_disagree"], s["disagrees"])
            performance = _return_summary(s["returns"])
            log(f"  Intervalo de confiança 95% da taxa de acerto: {100*low:.1f}%–{100*high:.1f}%")
            log(f"  Retorno flat-stake: {performance['profit_units']:+.1f} unidades | "
                f"ROI {performance['roi_pct']:+.2f}% | drawdown máximo "
                f"{performance['max_drawdown_units']:.1f} unidades")
            log("  Walk-forward por ano (cada jogo usa apenas história anterior):")
            for year, year_returns in sorted(s["year_returns"].items()):
                yearly = _return_summary(year_returns)
                log(f"    {year}: n={yearly['bets']} ROI={yearly['roi_pct']:+.2f}% "
                    f"lucro={yearly['profit_units']:+.1f}u")
            if edge_vs_market > 0:
                log(f"  >>> O nosso pick ganhou MAIS vezes ({pct_signal:.1f}%) do que a odd implicava "
                    f"({avg_implied_prob_our_pick:.1f}%) — diferença de +{edge_vs_market:.1f} p.p. "
                    "Isto É o teste certo de vantagem, não a comparação com 50%.")
            else:
                log(f"  >>> O nosso pick ganhou MENOS vezes ({pct_signal:.1f}%) do que a odd implicava "
                    f"({avg_implied_prob_our_pick:.1f}%) — diferença de {edge_vs_market:.1f} p.p. Sem vantagem.")
        else:
            log("  Sem casos de divergência suficientes para este sinal.")

    log(f"\n{'=' * 60}")
    log(
        "\nInterpretação CORRIGIDA: o teste certo não é 'acima de 50%?' — os casos de "
        "divergência tendem a ser jogos mais equilibrados (repara que a % de acerto do "
        "mercado cai face à média geral), por isso o 'azarão' já tem probabilidade implícita "
        "abaixo de 50% à partida. O teste correto é comparar a taxa de acerto real do nosso "
        "pick com a PRÓPRIA probabilidade implícita das odds para esse pick — ver linha "
        "'>>> ' em cada sinal acima. Vantagem real = ganhar mais vezes do que a odd do nosso "
        "próprio pick implicava, não ultrapassar 50%. Mesmo assim, isto continua a não provar "
        "lucro (falta simular custos/margem e validar fora desta amostra), e testar 4 sinais "
        "em vez de 1 aumenta o risco de um deles parecer positivo por acaso."
    )

    log("\nTeste concluído.")

    _save_results_file(output_lines)


def _save_results_file(output_lines: list[str]) -> None:
    os.makedirs("data/backtest_results", exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
    path = f"data/backtest_results/{timestamp}.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# Backtest — {timestamp} UTC\n\n```\n")
        f.write("\n".join(output_lines))
        f.write("\n```\n")
    print(f"\n[info] Resultado gravado em {path}")


if __name__ == "__main__":
    run()
