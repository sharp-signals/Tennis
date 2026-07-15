"""
Configuração central do bot. Ajusta aqui os parâmetros de negócio
sem mexer na lógica dos outros módulos.
"""

# --- Torneios a seguir (Fase 1: qualidade > cobertura) -----------------
# Chaves conforme usadas pela The Odds API (sport_key) — uma por torneio,
# não há chave genérica "masters_1000". Lista confirmada em
# https://the-odds-api.com/sports/tennis-odds.html (verifica periodicamente,
# a API vai adicionando torneios e os nomes podem mudar).
#
# IMPORTANTE: um sport_key só aparece em /v4/sports e devolve dados em
# /v4/sports/{key}/odds quando esse torneio está "in season" (a decorrer
# ou mesmo prestes a começar). Fora disso é normal e esperado não vir
# nada — o bot já trata isso como "sem jogos elegíveis", não como erro.
ODDS_API_TENNIS_SPORT_KEYS = [
    # Grand Slams
    "tennis_atp_aus_open_singles",
    "tennis_atp_french_open",
    "tennis_atp_wimbledon",
    "tennis_atp_us_open",
    "tennis_wta_aus_open_singles",
    "tennis_wta_french_open",
    "tennis_wta_wimbledon",
    "tennis_wta_us_open",
    # ATP Masters 1000 (chave por torneio)
    "tennis_atp_indian_wells",
    "tennis_atp_miami_open",
    "tennis_atp_monte_carlo_masters",
    "tennis_atp_madrid_open",
    "tennis_atp_italian_open",
    "tennis_atp_canadian_open",
    "tennis_atp_cincinnati_open",
    "tennis_atp_shanghai_masters",
    "tennis_atp_paris_masters",
    # WTA 1000
    "tennis_wta_indian_wells",
    "tennis_wta_miami_open",
    "tennis_wta_madrid_open",
    "tennis_wta_italian_open",
    "tennis_wta_canadian_open",
    "tennis_wta_cincinnati_open",
    "tennis_wta_china_open",
    "tennis_wta_wuhan_open",
    # ATP/WTA 500 e 250 cobertos pela The Odds API (a doc deles fala só em
    # "500 e acima", mas a tabela real inclui alguns 250 como Doha, Munique,
    # Bad Homburg e Strasbourg — mantidos aqui de propósito, já que a fonte
    # é gratuita e não há custo extra em incluir mais torneios elegíveis).
    "tennis_atp_barcelona_open",
    "tennis_atp_dubai",
    "tennis_atp_qatar_open",
    "tennis_atp_queens_club_champ",
    "tennis_atp_halle_open",
    "tennis_atp_hamburg_open",
    "tennis_atp_munich",
    "tennis_atp_china_open",
    "tennis_wta_dubai",
    "tennis_wta_qatar_open",
    "tennis_wta_queens_club_champ",
    "tennis_wta_stuttgart_open",
    "tennis_wta_charleston_open",
    "tennis_wta_german_open",
    "tennis_wta_bad_homburg_open",
    "tennis_wta_strasbourg",
]

# Ranking mínimo (de qualquer um dos dois jogadores) para um jogo fora
# de Grand Slam / Masters 1000 ainda assim entrar no resumo.
# Em Slams/Masters entram sempre; isto só filtra torneios menores se
# decidires ativar a Fase 2 (ATP/WTA 500).
MIN_RANK_TO_INCLUDE_IF_LOWER_TIER = 50

# Janela de antecedência: só considera jogos que arrancam dentro
# destas horas a partir do momento em que o workflow corre.
LOOKAHEAD_HOURS_MIN = 3
LOOKAHEAD_HOURS_MAX = 30

# Piso -> impacto reconhecido nas features (usado no prompt para o LLM)
SURFACES = ["Hard", "Clay", "Grass"]

# Quantos jogos anteriores olhar para "forma recente"
RECENT_FORM_MATCHES = 10

# Quantos dias contam como "sem descanso" para efeitos de fadiga
FATIGUE_LOOKBACK_DAYS = 4

# Emojis de sinalização usados no resumo curto do Telegram
FLAG_HIGH_SIGNAL = "🔴"     # algo digno de nota (ex: divergência forte vs mercado, fadiga clara)
FLAG_UNCERTAIN = "🟡"       # incerteza / dados incompletos / jogo equilibrado
FLAG_ROUTINE = "🟢"         # sem sinais especiais

CLAUDE_MODEL = "claude-sonnet-5"
