"""
Script de teste isolado para validar as 4 funções novas SEM depender da
RapidAPI/matchstat (que está com a quota esgotada hoje). Usa só Sackmann
(histórico + rankings) e Open-Meteo (meteorologia) — nenhuma das duas tem
limite prático de pedidos.

Corre via: python -m src.test_new_features
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import fetch_data

ATP_TEST_PLAYERS = ["Jannik Sinner", "Carlos Alcaraz"]
WTA_TEST_PLAYERS = ["Aryna Sabalenka", "Iga Swiatek"]


def _print_section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def test_tour(tour: str, players: list[str]) -> None:
    _print_section(f"HISTÓRICO — {tour.upper()}")
    history = fetch_data.get_history(tour)
    print(f"Linhas carregadas: {len(history)}")
    if history.empty:
        print("[aviso] histórico vazio — as funções abaixo vão dar tudo None, como esperado.")

    for player in players:
        _print_section(f"{player} ({tour.upper()})")

        ranking = fetch_data.get_player_ranking(history, player)
        print(f"Ranking: {ranking}")

        injury = fetch_data.compute_injury_signal(history, player)
        print(f"Sinal de lesão/retirement: {injury}")

        serve = fetch_data.compute_serve_return_stats(history, player, n_matches=10)
        print(f"Stats de serviço/resposta: {serve}")

        form = fetch_data.compute_recent_form(history, player, n_matches=10)
        print(f"Forma recente (já existia, para comparação): {form}")


def test_weather() -> None:
    _print_section("METEOROLOGIA (Open-Meteo)")
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)

    for place in ["Paris, France", "Umag, Croatia", "Cidade Inventada Que Não Existe XYZ"]:
        coords = fetch_data.geocode_location(place)
        print(f"\nGeocodificação de '{place}': {coords}")
        if coords:
            weather = fetch_data.get_weather_forecast(coords["lat"], coords["lon"], tomorrow)
            print(f"Previsão para amanhã: {weather}")
        else:
            print("Sem coordenadas — previsão fica None (comportamento esperado para o teste da cidade inventada).")


if __name__ == "__main__":
    test_tour("atp", ATP_TEST_PLAYERS)
    test_tour("wta", WTA_TEST_PLAYERS)
    test_weather()
    print("\n\nTeste concluído.")
