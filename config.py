"""
Configuração central do bot. Ajusta aqui os parâmetros de negócio
sem mexer na lógica dos outros módulos.
"""

# --- Torneios a seguir (Fase 1: qualidade > cobertura) -----------------
# Chaves conforme usadas pela The Odds API (sport_key).
# Ver lista completa e atualizada em:
# https://api.the-odds-api.com/v4/sports?apiKey=YOUR_KEY
ODDS_API_TENNIS_SPORT_KEYS = [
    "tennis_atp_aus_open_singles",
    "tennis_atp_french_open",
    "tennis_atp_wimbledon",
    "tennis_atp_us_open",
    "tennis_atp_masters_1000",   # nome genérico: a API separa por torneio real quando "in season"
    "tennis_wta_aus_open_singles",
    "tennis_wta_french_open",
    "tennis_wta_wimbledon",
    "tennis_wta_us_open",
    "tennis_wta_1000",
]
# Nota: a The Odds API só devolve um sport_key quando o torneio está
# "in season" (a decorrer/próximo). Confirma a lista exata via /v4/sports
# antes de fixar isto — os nomes têm mudado ao longo do tempo.

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
