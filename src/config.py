"""
Configuração central do bot. Ajusta aqui os parâmetros de negócio
sem mexer na lógica dos outros módulos.
"""

# --- Fixtures: fonte primária (RapidAPI / matchstat) --------------------
# Confirmado manualmente (15/07/2026) que este endpoint cobre torneios
# que a The Odds API não lista (ex: Umag, ATP 250), incluindo Challenger
# e ITF — daí precisarmos do filtro por `tier` abaixo.
RAPIDAPI_HOST = "tennis-api-atp-wta-itf.p.rapidapi.com"
RAPIDAPI_BASE = f"https://{RAPIDAPI_HOST}/tennis/v2"

# Tiers a incluir no bot. Confirmado manualmente: "ATP 250" é o valor exato
# devolvido pelo campo "tier" do endpoint getTournamentInfo.
# TODO: os valores de Grand Slam / Masters 1000 / WTA ainda não foram
# confirmados manualmente — testa getTournamentInfo com o tournamentId de
# um Slam ou Masters assim que houver um a decorrer, e ajusta esta lista
# se o valor real não bater certo (ex: pode ser "Grand Slam" ou "GS", pode
# ser "Masters 1000" em vez de "ATP 1000" — não adivinhes, confirma).
ALLOWED_TOURNAMENT_TIERS = {
    "Grand Slam",
    "ATP 1000",
    "ATP 500",
    "ATP 250",
    "WTA 1000",
    "WTA 500",
    "WTA 250",
}
# Tiers conhecidos que ficam sempre de fora (ITF/Challenger — dados mais
# esparsos, conforme decidido na fase de planeamento).
EXCLUDED_TOURNAMENT_TIERS = {"Future", "Challenger"}

# Quantos dias (incluindo hoje) pedir ao getDateFixtures. 2 = hoje + amanhã.
FIXTURES_LOOKAHEAD_DAYS = 2

# Cache local de info de torneio (tier, piso, nome), para não gastar
# pedidos repetidos ao mesmo torneio em execuções sucessivas. É um
# ficheiro no próprio repositório, escrito de volta pelo workflow.
TOURNAMENT_CACHE_PATH = "data/tournament_cache.json"

# --- Odds de mercado: fonte secundária/opcional (The Odds API) ----------
# Já não decide "que jogos existem" — só tenta enriquecer com odds quando
# o jogo (por nomes dos jogadores) também aparecer aqui. Se não aparecer,
# o campo de odds fica None, tal como qualquer outro dado em falta.
ODDS_API_TENNIS_SPORT_KEYS = [
    "tennis_atp_aus_open_singles", "tennis_atp_french_open",
    "tennis_atp_wimbledon", "tennis_atp_us_open",
    "tennis_wta_aus_open_singles", "tennis_wta_french_open",
    "tennis_wta_wimbledon", "tennis_wta_us_open",
    "tennis_atp_indian_wells", "tennis_atp_miami_open",
    "tennis_atp_monte_carlo_masters", "tennis_atp_madrid_open",
    "tennis_atp_italian_open", "tennis_atp_canadian_open",
    "tennis_atp_cincinnati_open", "tennis_atp_shanghai_masters",
    "tennis_atp_paris_masters",
    "tennis_wta_indian_wells", "tennis_wta_miami_open",
    "tennis_wta_madrid_open", "tennis_wta_italian_open",
    "tennis_wta_canadian_open", "tennis_wta_cincinnati_open",
    "tennis_wta_china_open", "tennis_wta_wuhan_open",
    "tennis_atp_barcelona_open", "tennis_atp_dubai",
    "tennis_atp_qatar_open", "tennis_atp_queens_club_champ",
    "tennis_atp_halle_open", "tennis_atp_hamburg_open",
    "tennis_atp_munich", "tennis_atp_china_open",
    "tennis_wta_dubai", "tennis_wta_qatar_open",
    "tennis_wta_queens_club_champ", "tennis_wta_stuttgart_open",
    "tennis_wta_charleston_open", "tennis_wta_german_open",
    "tennis_wta_bad_homburg_open", "tennis_wta_strasbourg",
]

# Ranking mínimo (de qualquer um dos dois jogadores) para um jogo de
# nível 250 ainda assim entrar no resumo. Em Slams/Masters/500 entra
# sempre. Ainda por implementar em main.py — precisa de fonte de ranking.
MIN_RANK_TO_INCLUDE_IF_TIER_250 = 120

# Janela de antecedência: só considera jogos que arrancam dentro
# destas horas a partir do momento em que o workflow corre.
LOOKAHEAD_HOURS_MIN = 3
LOOKAHEAD_HOURS_MAX = 30

SURFACES = ["Hard", "Clay", "Grass"]

RECENT_FORM_MATCHES = 10
FATIGUE_LOOKBACK_DAYS = 4

FLAG_HIGH_SIGNAL = "🔴"
FLAG_UNCERTAIN = "🟡"
FLAG_ROUTINE = "🟢"

CLAUDE_MODEL = "claude-sonnet-5"
