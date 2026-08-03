"""
Teste de ponta a ponta com um jogo FICTÍCIO, claramente identificado como
teste em todas as mensagens — para validar o pipeline completo (histórico
real + análise configurada + publicação) sem esperar por um torneio a sério.

Usa dois jogadores ATP reais (para o histórico ter alguma coisa para
analisar), mas o "jogo" em si — torneio, data, ronda — é inventado.

Corre via: python -m src.test_dry_run
"""

from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone

from . import fetch_data
from .analyze import analyze_match
from .config import ODDS_API_TENNIS_SPORT_KEYS
from .telegram_bot import send_message

# Dois jogadores ATP conhecidos, para testar H2H/forma/piso com dados reais
# (se estiverem no dataset da TennisMyLife). Muda estes nomes se quiseres
# testar outro par.
TEST_PLAYER_A = "Jannik Sinner"
TEST_PLAYER_B = "Carlos Alcaraz"
TEST_SURFACE = "Hard"


def build_fake_match_payload() -> dict:
    tour = "atp"
    history = fetch_data.get_history(tour)
    start = datetime.now(timezone.utc) + timedelta(days=1)

    return {
        "player_a": TEST_PLAYER_A,
        "player_b": TEST_PLAYER_B,
        "tournament": "🧪 TORNEIO FICTÍCIO DE TESTE",
        "tier": "ATP Masters 1000",
        "surface": TEST_SURFACE,
        "commence_time_utc": start.isoformat(),
        "market_odds_decimal": fetch_data.find_market_odds(
            ODDS_API_TENNIS_SPORT_KEYS, TEST_PLAYER_A, TEST_PLAYER_B
        ),
        "h2h": fetch_data.compute_h2h(history, TEST_PLAYER_A, TEST_PLAYER_B, TEST_SURFACE),
        "h2h_rich_stats": None,  # só disponível para WTA — este teste é ATP
        "recent_form_a": fetch_data.compute_recent_form(history, TEST_PLAYER_A, 10),
        "current_season_a": fetch_data.compute_current_season_record(history, TEST_PLAYER_A),
        "current_season_b": fetch_data.compute_current_season_record(history, TEST_PLAYER_B),
        "recent_form_b": fetch_data.compute_recent_form(history, TEST_PLAYER_B, 10),
        "surface_stats_a": fetch_data.compute_surface_stats(history, TEST_PLAYER_A),
        "surface_stats_b": fetch_data.compute_surface_stats(history, TEST_PLAYER_B),
        "fatigue_signal_a": fetch_data.compute_fatigue(history, TEST_PLAYER_A, start),
        "fatigue_signal_b": fetch_data.compute_fatigue(history, TEST_PLAYER_B, start),
        "injury_signal_a": fetch_data.compute_injury_signal(history, TEST_PLAYER_A),
        "injury_signal_b": fetch_data.compute_injury_signal(history, TEST_PLAYER_B),
        "serve_return_stats_a": fetch_data.compute_serve_return_stats(history, TEST_PLAYER_A, 10),
        "serve_return_stats_b": fetch_data.compute_serve_return_stats(history, TEST_PLAYER_B, 10),
        "ranking_a": fetch_data.get_player_ranking(history, TEST_PLAYER_A),
        "ranking_b": fetch_data.get_player_ranking(history, TEST_PLAYER_B),
        "set1_comeback_stats_a": fetch_data.compute_set1_comeback_stats(history, TEST_PLAYER_A),
        "set1_comeback_stats_b": fetch_data.compute_set1_comeback_stats(history, TEST_PLAYER_B),
        "handedness_matchup_a": fetch_data.compute_handedness_matchup_stats(history, TEST_PLAYER_A),
        "handedness_matchup_b": fetch_data.compute_handedness_matchup_stats(history, TEST_PLAYER_B),
        "layoff_return_stats_a": fetch_data.compute_return_from_layoff_stats(history, TEST_PLAYER_A),
        "layoff_return_stats_b": fetch_data.compute_return_from_layoff_stats(history, TEST_PLAYER_B),
        "deciding_set_stats_a": fetch_data.compute_deciding_set_stats(history, TEST_PLAYER_A),
        "deciding_set_stats_b": fetch_data.compute_deciding_set_stats(history, TEST_PLAYER_B),
        "round_stage_stats_a": fetch_data.compute_round_stage_stats(history, TEST_PLAYER_A),
        "round_stage_stats_b": fetch_data.compute_round_stage_stats(history, TEST_PLAYER_B),
        "weather": None,  # não aplicável a um torneio fictício
    }


def run() -> None:
    print("=== TESTE DE PONTA A PONTA (jogo fictício) ===")
    payload = build_fake_match_payload()
    print("\nPayload construído:")
    for key, value in payload.items():
        print(f"  {key}: {value}")

    # O provider é escolhido pela configuração central. O valor por omissão é
    # LLM_MODE=mock e o workflow de teste reforça ALLOW_PAID_LLM=0.
    print("\n--- A gerar análise através do provider configurado ---")
    result = analyze_match(payload)
    print(f"Flag: {result['flag']}")
    print(f"Summary line: {result['summary_line']}")
    print(f"Pontos-chave: {len(result.get('key_points', []))} | "
          f"Discrepâncias: {len(result.get('discrepancies', []))} | "
          f"Veredicto: {'sim' if result.get('verdict') else 'não'}")
    print("\n[teste concluído — a publicação foi omitida nesta versão de teste]")
    return

    print("\n--- A enviar para o Telegram ---")
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    message = (
        f"<b>🧪 TESTE — Resumo Pré-Live — {today_str}</b>\n"
        "<i>(mensagem de teste, não é um jogo real)</i>\n\n"
        f"{html.escape(result['flag'])} {html.escape(result['summary_line'])}\n"
        f"\n📄 Relatório completo: {html.escape(telegraph_url)}"
    )
    send_message(message)
    print("\nTeste concluído com sucesso — verifica o Telegram.")


if __name__ == "__main__":
    run()
