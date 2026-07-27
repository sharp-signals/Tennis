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
    "ATP Masters 1000",
    "ATP 500",
}
# Nível 250 (ATP/WTA) ficou de fora por decisão explícita: a Odds API não
# tem cobertura fiável de mercado para este nível (confirmado na prática
# com Umag, Gstaad, Bastad, Athens, Iasi — nenhum apareceu em 3 fornecedores
# de odds diferentes testados). Como as odds de mercado são o propósito
# central do bot, preferimos garantir odds em todos os jogos analisados a
# cobrir mais torneios sem essa peça. Se no futuro aparecer uma fonte de
# odds fiável para o nível 250, é só acrescentar "ATP 250"/"WTA 250" aqui.
# Tiers conhecidos que ficam sempre de fora (ITF/Challenger — dados mais
# esparsos, conforme decidido na fase de planeamento).
EXCLUDED_TOURNAMENT_TIERS = {"Future", "Challenger"}

# Quantos dias (incluindo hoje) pedir ao getDateFixtures. 2 = hoje + amanhã.
FIXTURES_LOOKAHEAD_DAYS = 2

# Cache local de info de torneio (tier, piso, nome), para não gastar
# pedidos repetidos ao mesmo torneio em execuções sucessivas. É um
# ficheiro no próprio repositório, escrito de volta pelo workflow.
TOURNAMENT_CACHE_PATH = "data/tournament_cache.json"

# Cache local de fixtures por dia (data/fixtures_cache.json), para não
# repetir o mesmo pedido de fixtures nas duas execuções diárias quando a
# data já foi consultada há poucas horas. Poupa quota (plano free = 50/dia).
FIXTURES_CACHE_PATH = "data/fixtures_cache.json"
FIXTURES_CACHE_MAX_AGE_HOURS = 8

# O getDateFixtures do matchstat é paginado (confirmado: resposta real já
# trouxe "hasNextPage": true). Limite de páginas por dia/tour, para não
# esgotar a quota diária (50 pedidos) num único dia com muitos jogos.
MAX_FIXTURE_PAGES = 5

# Tours a seguir. Reduzido a ATP apenas (16/07/2026): os repositórios
# tennis_atp/tennis_wta do Jeff Sackmann desapareceram do GitHub, e não
# há outra fonte gratuita fiável de histórico WTA (a TennisMyLife nunca
# cobriu WTA). Em vez de teres um bot inconsistente que às vezes fala de
# WTA sem H2H/forma/piso nenhum, reduzimos o âmbito. Se aparecer uma fonte
# WTA fiável no futuro, é só voltar a acrescentar "wta" aqui.
TOURS_TO_FOLLOW = ("atp",)

# --- Odds de mercado: fonte secundária/opcional (The Odds API) ----------
# Já não decide "que jogos existem" — só tenta enriquecer com odds quando
# o jogo (por nomes dos jogadores) também aparecer aqui. Se não aparecer,
# o campo de odds fica None, tal como qualquer outro dado em falta.
# Só chaves ATP, dado TOURS_TO_FOLLOW acima.
ODDS_API_TENNIS_SPORT_KEYS = [
    "tennis_atp_aus_open_singles", "tennis_atp_french_open",
    "tennis_atp_wimbledon", "tennis_atp_us_open",
    "tennis_atp_indian_wells", "tennis_atp_miami_open",
    "tennis_atp_monte_carlo_masters", "tennis_atp_madrid_open",
    "tennis_atp_italian_open", "tennis_atp_canadian_open",
    "tennis_atp_cincinnati_open", "tennis_atp_shanghai_masters",
    "tennis_atp_paris_masters",
    "tennis_atp_barcelona_open", "tennis_atp_dubai",
    "tennis_atp_qatar_open", "tennis_atp_queens_club_champ",
    "tennis_atp_halle_open", "tennis_atp_hamburg_open",
    "tennis_atp_munich", "tennis_atp_china_open",
]


# Janela de antecedência: só considera jogos que arrancam dentro
# destas horas a partir do momento em que o workflow corre.
LOOKAHEAD_HOURS_MIN = 3
LOOKAHEAD_HOURS_MAX = 30

SURFACES = ["Hard", "Clay", "Grass"]

RECENT_FORM_MATCHES = 10
SERVE_RETURN_STATS_MATCHES = 10
INJURY_SIGNAL_LOOKBACK_MATCHES = 5

# Quantos anos de histórico carregar da TennisMyLife, para o H2H cobrir a
# carreira inteira de um jogador ativo, não só o ano corrente. 20 anos
# cobre com folga a carreira mais longa de qualquer jogador ainda ativo
# no circuito (16/07/2026: corrigido depois de notar que só carregávamos
# o ano corrente, o que dava H2H incompletos).
HISTORY_YEARS_TO_LOAD = 20

# Pedir meteorologia só para jogos ao ar livre. O matchstat usa prefixo
# "I." no nome do piso para indoor (ex: "I.hard") — qualquer piso que
# comece por "I." é tratado como indoor e não pede meteorologia.
INDOOR_SURFACE_PREFIX = "I."

FLAG_HIGH_SIGNAL = "🔴"
FLAG_UNCERTAIN = "🟡"
FLAG_ROUTINE = "🟢"

CLAUDE_MODEL = "claude-sonnet-5"
