# Tennis Pre-Live Bot

Bot de análise pré-live de ténis, gratuito, a correr em GitHub Actions.
Réplica do espírito do bot de futebol: recolhe dados reais de fontes
gratuitas/documentadas, pede ao Claude uma análise que nunca inventa
informação, e envia um resumo curto no Telegram com link para o relatório
completo no Telegra.ph.

## Como correr (setup)

1. Faz fork/push deste repositório para o teu GitHub.
2. Em **Settings → Secrets and variables → Actions**, cria estes secrets:

   | Secret | Onde obter | Grátis? |
   |---|---|---|
   | `ANTHROPIC_API_KEY` | console.anthropic.com | Tens créditos pagos, mas o volume aqui é baixo (poucas chamadas/dia) |
   | `RAPIDAPI_KEY` | rapidapi.com → subscreve "Tennis API - ATP WTA ITF" (matchstat), plano Basic/free | Sim, tier free (confirmado: 50 pedidos/dia) |
   | `ODDS_API_KEY` | the-odds-api.com | Sim, tier free |
   | `TELEGRAM_BOT_TOKEN` | @BotFather no Telegram | Sim |
   | `TELEGRAM_CHAT_ID` | @userinfobot ou API do teu bot | Sim |
   | `TELEGRAPH_ACCESS_TOKEN` | opcional — ver abaixo | Sim |

3. `TELEGRAPH_ACCESS_TOKEN` é opcional: se não o definires, o bot cria uma
   conta anónima nova a cada execução (funciona à mesma). Se quiseres que
   todos os relatórios fiquem agrupados sob a mesma "conta" Telegra.ph,
   corre o bot uma vez localmente, apanha o token que ele imprime no log,
   e guarda-o como secret.

4. O workflow (`.github/workflows/tennis-bot.yml`) já está agendado para
   correr 2x/dia. Podes também disparar manualmente em **Actions → Tennis
   Pre-Live Bot → Run workflow**.

## Arquitetura das fontes de dados (importante — leia isto)

**Fixtures (que jogos existem) vêm da RapidAPI/matchstat, não da Odds API.**
Descobrimos na prática que usar uma API de odds como fonte de "que jogos
existem" sub-representa torneios menores — a The Odds API simplesmente não
lista alguns ATP 250 (ex: Umag, Båstad, Gstaad), porque só cobre torneios
com interesse suficiente de bookmakers. A RapidAPI/matchstat
(`getDateFixtures`) devolve tudo, incluindo Challenger e ITF, por isso o
bot filtra pelo campo `tier` do torneio (`ALLOWED_TOURNAMENT_TIERS` em
`config.py`) para manter só os níveis que decidiste seguir.

**A The Odds API passou a um papel secundário/opcional**: só tenta
enriquecer cada jogo com odds de mercado, casando por nome de jogador. Se
não encontrar (torneio que ela não cobre), o campo de odds fica `None` —
tratado como qualquer outro dado em falta, nunca bloqueia o jogo de entrar
na análise.

**Cache local de torneios** (`data/tournament_cache.json`): o plano
gratuito da RapidAPI/matchstat só dá 50 pedidos/dia, e cada torneio novo
custa 1 pedido para saber o `tier`/piso. Por isso o bot guarda essa info
num ficheiro no próprio repositório e o workflow faz commit automático
quando há torneios novos — nas execuções seguintes, torneios já vistos não
gastam pedido nenhum.

## Fontes de dados usadas (todas gratuitas)

- **RapidAPI "Tennis API - ATP WTA ITF" (matchstat)** — fixtures (todos os
  tours e níveis) + info de torneio (tier, piso). Fonte primária. Tier
  free confirmado em 50 pedidos/dia.
- **The Odds API** — odds de mercado, quando disponíveis (Slams, Masters
  1000/500, e parte dos 250). Fonte secundária/opcional.
- **TennisMyLife** (stats.tennismylife.org) — histórico de resultados e
  rankings, licença MIT, dataset atualizado incluindo o torneio da semana
  corrente. Fonte primária para H2H/forma/piso histórico.
- **Jeff Sackmann — tennis_atp / tennis_wta** (GitHub) — fallback caso a
  TennisMyLife esteja indisponível. Licença CC BY-NC-SA (uso não comercial,
  com atribuição — ok para este projeto pessoal).
- **tennis-data.co.uk** — segunda fonte de fallback / cruzamento, CSV
  semanal com resultados, odds e piso.

Todas são APIs/downloads documentados — nenhuma é scraping de um site que
bloqueia pedidos não-oficiais (o problema que já tiveste com o Sofascore).

## Limitações conhecidas (aceites por design, tal como no bot de futebol)

- **Tiers de Grand Slam/Masters ainda por confirmar**: só testámos
  manualmente que `"ATP 250"` é o valor exato devolvido pelo campo `tier`.
  Os valores para Grand Slam, Masters 1000 e WTA em `ALLOWED_TOURNAMENT_TIERS`
  (`config.py`) são a melhor estimativa, não confirmação. Assim que houver
  um Slam ou Masters a decorrer, testa `getTournamentInfo` nesse torneio e
  corrige a lista se o valor real for diferente — caso contrário esses
  jogos vão ficar silenciosamente de fora do bot.
- **Filtro de ranking para nível 250 não está implementado**: existe
  `MIN_RANK_TO_INCLUDE_IF_TIER_250` em `config.py` mas `main.py` ainda não
  o usa — falta uma fonte de ranking por jogador. Sem isto, jogos de R1
  entre jogadores fora do top 100 num 250 vão gerar linha no resumo na
  mesma. Se o volume incomodar na prática, é o próximo a implementar.
- **Lesões**: não há nenhuma fonte gratuita fiável e estruturada para
  estado físico/lesões de tenistas. O campo `injury_data` vai sempre a
  `None`, e o prompt instrui o Claude a dizer explicitamente que não há
  esse dado — nunca a especular.
- **Fadiga**: é uma aproximação (nº de jogos nos últimos N dias a partir do
  histórico), não o calendário exato dia-a-dia do torneio em curso.
- **Dados desatualizados de terceiros**: tal como o caso do treinador
  errado no futebol, isto pode acontecer aqui também (ex: ranking
  desatualizado numa fonte). Não vale a pena complicar com correções
  manuais — se acontecer com frequência lidamos nessa altura.
- **Correspondência de nomes entre fontes**: o matchstat e o
  TennisMyLife/Sackmann podem grafar o mesmo jogador de forma ligeiramente
  diferente (acentos, ordem do nome). Quando isso acontece, H2H/forma/piso
  ficam a `None` em vez de errados — mas vale a pena vigiar os logs
  (`[aviso] sem info do torneio...`) nas primeiras execuções.

## Extensibilidade

- Fase 2 (ATP/WTA 500): adiciona os `sport_key` correspondentes em
  `config.py` e ajusta `MIN_RANK_TO_INCLUDE_IF_LOWER_TIER` se quiseres
  filtrar por ranking nesses torneios menores.
- Mais fontes gratuitas: qualquer fonte nova só precisa de uma função
  `_load_<fonte>()` em `fetch_data.py` que devolva um DataFrame com pelo
  menos as colunas `winner_name`, `loser_name`, `surface`, `tourney_date`
  — as funções `compute_*` já funcionam em cima desse formato comum.
