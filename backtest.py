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


def _fetch_tennisdata_year(year: int):
    url = f"http://www.tennis-data.co.uk/{year}/atp.csv"
    try:
        resp = requests.get(url, headers=_BROWSER_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text), encoding="latin1")
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
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value).strip(), fmt).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
    return None


def _combined_edge(history_before: pd.DataFrame, player_a: str, player_b: str, surface: str):
    """
    Soma simples (não um modelo treinado) de três edges de win-rate
    (H2H de carreira, forma recente, piso), em pontos percentuais,
    positivo = favorece player_a. None se não houver dados suficientes
    para calcular nenhum dos três.
    """
    edges = []

    h2h = fetch_data.compute_h2h(history_before, player_a, player_b, surface)
    if h2h and h2h["overall"]["total_matches"] >= 3:
        total = h2h["overall"]["total_matches"]
        edges.append(100 * (h2h["overall"]["a_wins"] - h2h["overall"]["b_wins"]) / total)

    form_a = fetch_data.compute_recent_form(history_before, player_a, 10)
    form_b = fetch_data.compute_recent_form(history_before, player_b, 10)
    if form_a and form_b and form_a["matches"] >= 5 and form_b["matches"] >= 5:
        rate_a = 100 * form_a["wins"] / form_a["matches"]
        rate_b = 100 * form_b["wins"] / form_b["matches"]
        edges.append(rate_a - rate_b)

    surf_a = fetch_data.compute_surface_stats(history_before, player_a)
    surf_b = fetch_data.compute_surface_stats(history_before, player_b)
    if surf_a and surf_b and surface in SURFACES:
        stat_a, stat_b = surf_a.get(surface), surf_b.get(surface)
        if stat_a and stat_b and stat_a["matches"] >= 5 and stat_b["matches"] >= 5:
            rate_a = 100 * stat_a["wins"] / stat_a["matches"]
            rate_b = 100 * stat_b["wins"] / stat_b["matches"]
            edges.append(rate_a - rate_b)

    if not edges:
        return None
    return sum(edges) / len(edges)


def run() -> None:
    print("=== BACKTEST: sinais do bot vs mercado histórico ===\n")

    print("--- A carregar histórico completo (TennisMyLife) ---")
    full_history = fetch_data.get_history("atp")
    if full_history.empty:
        print("[erro] sem histórico disponível — impossível continuar o backtest.")
        return
    full_history["tourney_date"] = pd.to_datetime(full_history["tourney_date"], format="%Y%m%d", errors="coerce")

    print("\n--- A carregar odds históricas (tennis-data.co.uk) ---")
    odds_data = _load_all_backtest_years()
    if odds_data.empty:
        print("[erro] sem dados de odds — impossível continuar o backtest.")
        return

    total_rows = len(odds_data)
    usable = 0
    skipped_no_odds = 0
    skipped_no_date = 0
    skipped_no_edge = 0

    market_correct = 0
    market_total = 0
    agrees_total = 0
    our_signal_correct_when_disagrees = 0
    market_correct_when_disagrees = 0
    disagrees_total = 0

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

        # Ponto central do método: só jogos ANTERIORES a esta data.
        history_before = full_history[full_history["tourney_date"] < pd.Timestamp(match_date).tz_localize(None)]
        if history_before.empty:
            continue

        odd_winner, odd_loser = odds
        implied_prob_winner = _implied_prob_winner(odd_winner, odd_loser)

        # Convenção: player_a = "winner" da fonte histórica, só para
        # calcular o edge com sinal consistente — não sabemos o
        # resultado à partida no mundo real, isto é só para comparar
        # depois quem tinha razão.
        edge = _combined_edge(history_before, winner, loser, surface)
        if edge is None or abs(edge) < MIN_EDGE_TO_COUNT:
            skipped_no_edge += 1
            continue

        usable += 1

        market_favors_winner = implied_prob_winner > 0.5
        market_total += 1
        if market_favors_winner:
            market_correct += 1  # o "winner" da fonte ganhou mesmo; se o mercado o favorecia, acertou

        our_signal_favors_winner = edge > 0

        if our_signal_favors_winner == market_favors_winner:
            agrees_total += 1
        else:
            disagrees_total += 1
            if our_signal_favors_winner:
                our_signal_correct_when_disagrees += 1
            else:
                market_correct_when_disagrees += 1

    print("\n=== RESULTADOS ===")
    print(f"Jogos totais na fonte de odds: {total_rows}")
    print(f"  Sem odds utilizáveis: {skipped_no_odds}")
    print(f"  Sem data válida: {skipped_no_date}")
    print(f"  Sem edge suficiente (< {MIN_EDGE_TO_COUNT} p.p.) para contar: {skipped_no_edge}")
    print(f"  Jogos usados na análise: {usable}")

    if market_total > 0:
        print(f"\nMercado (favorito por odds) acertou o vencedor em {market_correct}/{market_total} "
              f"({100 * market_correct / market_total:.1f}%)")

    print(f"\nJogos em que o nosso sinal CONCORDA com o mercado: {agrees_total}")
    print(f"Jogos em que o nosso sinal DISCORDA do mercado: {disagrees_total}")

    if disagrees_total > 0:
        print("\n--- Nos casos de DIVERGÊNCIA (é aqui que está a pergunta real) ---")
        print(f"  O nosso sinal teve razão: {our_signal_correct_when_disagrees}/{disagrees_total} "
              f"({100 * our_signal_correct_when_disagrees / disagrees_total:.1f}%)")
        print(f"  O mercado teve razão:      {market_correct_when_disagrees}/{disagrees_total} "
              f"({100 * market_correct_when_disagrees / disagrees_total:.1f}%)")
        print(
            "\nInterpretação: se o nosso sinal acertasse por acaso, esperaríamos ~50% nestes casos "
            "de divergência (por definição, são os jogos onde discordamos do mercado). Um valor "
            "consistentemente acima de 50%, em amostra suficientemente grande, seria o primeiro "
            "indício real de vantagem — mas não prova lucro (isso exigiria também simular custos, "
            "margem das casas, e validar fora desta amostra)."
        )
    else:
        print("\n[aviso] Sem casos de divergência suficientes para conclusão nenhuma.")

    print("\nTeste concluído.")


if __name__ == "__main__":
    run()
