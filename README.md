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

## Capacidades adicionais (27/07/2026)

- **Recuperação após perder o 1º set** — para aplicares em live, sem o
  bot correr ao vivo: `compute_set1_comeback_stats` calcula, a partir do
  histórico, em quantos jogos (de entre os que o jogador perdeu o 1º
  set) ele ainda assim ganhou — separado por melhor-de-3 e melhor-de-5
  (a taxa é estruturalmente diferente). É um dado histórico real, não
  uma previsão — o Claude é instruído a nunca o transformar numa
  recomendação de aposta, só contexto para decidires tu, no momento,
  o que souberes do jogador por cima disso.

## Capacidades adicionais (16/07/2026)

Depois de resolvida a arquitetura base, acrescentámos quatro peças, todas
com fontes gratuitas/documentadas:

- **Sinal de lesão/retirement** — a partir da coluna `score` dos ficheiros
  Sackmann (`RET`, `W/O`, `DEF`). É um facto verificável ("desistiu do
  último jogo"), não um relatório médico — trata-se como tal no prompt.
- **Stats de serviço/resposta** — % de aces, duplas faltas, 1º serviço
  dentro, 1º serviço ganho, break points salvos, agregados nos últimos N
  jogos. Só disponível quando a fonte tem essas colunas (Sackmann tem;
  tennis-data.co.uk não) — fica `None` quando não há.
- **Rankings reais** — derivado diretamente do histórico de jogos já
  carregado (as colunas `winner_rank`/`loser_rank`/`..._rank_points` já
  vêm em cada jogo da TennisMyLife). Usa o ranking do jogo mais recente
  do jogador no nosso histórico — não depende de nenhum ficheiro extra
  do Sackmann (corrigido em 27/07/2026, depois de o repositório dele ter
  desaparecido do GitHub).
- **Meteorologia** — via Open-Meteo (grátis, documentada, sem key). Só é
  pedida para jogos ao ar livre (o matchstat usa prefixo `"I."` no piso
  para indoor, ex: `"I.hard"` — esses ficam sempre `None` por não se
  aplicar, não por falta de dados). A localização é geocodificada a partir
  do nome do torneio + país; se a geocodificação falhar (nome de cidade
  ambíguo ou não reconhecido), fica `None`.

## Âmbito: ATP apenas (decisão explícita, 16/07/2026)

O bot cobre **só ATP** — Grand Slam, ATP Masters 1000, ATP 500. O WTA foi
retirado por completo.

Motivo: os repositórios `tennis_atp`/`tennis_wta` de Jeff Sackmann no
GitHub desapareceram durante o desenvolvimento deste projeto (confirmado
com 404 real, ao vivo, tanto via `raw.githubusercontent.com` como via
jsDelivr, e o perfil dele no GitHub passou a mostrar só 1 repositório).
A TennisMyLife (fonte primária de histórico) nunca cobriu WTA — é uma
base de dados só de ATP. Sem nenhuma fonte gratuita fiável de histórico
WTA, ficaríamos com um bot inconsistente (às vezes fala de jogos WTA sem
H2H/forma/piso nenhum). Preferiu-se reduzir o âmbito a manter essa
inconsistência.

`TOURS_TO_FOLLOW = ("atp",)` em `config.py` controla isto — se aparecer
uma fonte WTA fiável no futuro, basta acrescentar `"wta"` aí (o resto do
pipeline já lida com qualquer tour sem alterações).

Nota histórica anterior (já não se aplica, mantida para contexto): a
decisão original de tiers (mais abaixo) também excluía ATP/WTA 250 por
falta de cobertura de odds — essa parte continua válida para o ATP.

## Âmbito de torneios (decisão explícita, 15/07/2026)

O bot cobre **Grand Slam, ATP Masters 1000, ATP 500, WTA 1000, WTA 500** —
já não cobre ATP/WTA 250.

Isto foi decidido depois de testar 3 fornecedores de odds diferentes (The
Odds API, RapidAPI/matchstat, odds-api.io) e nenhum ter cobertura fiável
de mercado para o nível 250 (testado com Umag, Gstaad, Bastad, Athens,
Iasi — todos a decorrer no momento do teste, nenhum encontrado). Como as
odds de mercado são o propósito central do bot (comparar o contexto
estatístico com o preço do mercado), preferiu-se reduzir o âmbito de
torneios a garantir odds fiáveis em todos os jogos analisados, em vez de
cobrir mais torneios sem essa peça central.

Se no futuro aparecer uma fonte de odds fiável para o nível 250, basta
acrescentar `"ATP 250"` / `"WTA 250"` a `ALLOWED_TOURNAMENT_TIERS` em
`config.py` — o resto do pipeline (fixtures, histórico, cache de torneio)
já lida com qualquer tier sem alterações.

## Arquitetura de fixtures (revista, 28/07/2026)

**Já não usamos o feed global "todos os jogos ATP do mundo, por dia".**
Esse feed (`getDateFixtures`) devolvia todos os Challengers/Futures do
mundo inteiro junto com os torneios que seguimos, obrigando a gastar
várias páginas de quota só a filtrar ruído — confirmado na prática
(28/07/2026): um único dia esgotou a quota inteira antes de cobrir todos
os jogos do Washington Open.

**Agora seguimos torneios diretamente por `tournamentId`**
(`getTournamentFixtures`), configurados em `TRACKED_TOURNAMENT_IDS` no
`config.py`. Muito mais eficiente (sem ruído global), mas exige um passo
manual: **quando um novo Slam/Masters 1000/500 começar, tens de
adicionar o `tournamentId` a essa lista**. Para descobrir o ID:

1. Na Playground do RapidAPI, endpoint `getTournamentInfo` ou
   `getTournamentFixtures`, tenta um ID próximo dos que já conheces
   (os IDs sobem ao longo do tempo/época) ou pesquisa pelo nome do
   torneio no `data/tournament_cache.json` já acumulado.
2. Confirma o `tier` (deve ser um dos permitidos em
   `ALLOWED_TOURNAMENT_TIERS`).
3. Acrescenta `{tournamentId}: "atp"` ao dicionário
   `TRACKED_TOURNAMENT_IDS`.

Filtragem automática incluída: jogos de pares (nomes com "/") e jogos
ainda sem data marcada são descartados antes de chegarem ao resto do
pipeline.

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
- **TennisMyLife** (stats.tennismylife.org) — histórico ATP (confirmado:
  não tem WTA). Licença não confirmada com certeza — a documentação
  refere-se como inspirada no `tennis_atp` do Sackmann (CC BY-NC-SA, não
  comercial); antes de qualquer uso comercial, ler os termos deles
  diretamente. Dataset atualizado incluindo o torneio da
  semana corrente. Fonte primária de histórico.
- **Jeff Sackmann — tennis_atp** (GitHub) — fallback para ATP caso a
  TennisMyLife esteja indisponível. Licença CC BY-NC-SA. **Nota
  (16/07/2026): este repositório (e o `tennis_wta` equivalente)
  desapareceu do GitHub durante o desenvolvimento — o código já trata
  isto com resiliência (tenta, falha, cai para a próxima fonte), mas não
  é mais uma fonte garantida.
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
- **Filtro de ranking para nível 250 não é aplicável**: o bot já não cobre
  ATP/WTA 250 (ver "Âmbito de torneios" acima), por isso essa questão ficou
  resolvida por decisão de âmbito, não por um filtro de ranking.
- **Lesões**: não há nenhuma fonte gratuita fiável e estruturada para
  estado físico/lesões de tenistas. O campo `injury_data` vai sempre a
  `None`, e o prompt instrui o Claude a dizer explicitamente que não há
  esse dado — nunca a especular.
- **Fadiga**: é uma aproximação (nº de jogos nos últimos N dias a partir do
  histórico), não o calendário exato dia-a-dia do torneio em curso.
- **Fadiga/hiato pode ser enganador para jogadores de Challenger/ITF**
  (confirmado na prática, 28/07/2026: Andres Martin apareceu com "736
  dias sem jogar", quando na realidade joga regularmente a nível
  Challenger/ITF — só não aparece na TennisMyLife, que só cobre o
  circuito principal). O prompt já instrui o Claude a assinalar esta
  possibilidade quando o ranking for baixo e o hiato longo, mas não há
  forma de confirmar a atividade real nesses níveis sem uma fonte de
  dados de Challenger/ITF, que não temos.
- **Dados desatualizados de terceiros**: tal como o caso do treinador
  errado no futebol, isto pode acontecer aqui também (ex: ranking
  desatualizado numa fonte). Não vale a pena complicar com correções
  manuais — se acontecer com frequência lidamos nessa altura.
- **Cobertura pode perder jogos em dias de muitos torneios simultâneos**
  (27/07/2026, observado na prática): o `getDateFixtures` devolve TODOS
  os jogos ATP do mundo nesse dia (Challengers/Futures incluídos), não só
  os torneios que seguimos. Com a quota limitada (`MAX_FIXTURE_PAGES=5`,
  50 pedidos/dia no plano free), em dias com muito ruído global o limite
  de páginas pode ser atingido antes de cobrir todos os jogos do torneio
  que realmente importa (ex: só 1 de vários jogos do Washington Open
  chegou a ser elegível numa execução). Decisão aceite por agora: não
  vale a pena a complexidade de pedir fixtures por torneio específico
  (`getTournamentFixtures`) só para isto — se se tornar um problema
  frequente, essa é a correção estrutural a considerar.

## Extensibilidade

- **WTA (decisão pendente, 28/07/2026):** avaliado e adiado — a
  TennisMyLife é só ATP, e o fallback (tennis-data.co.uk) só tem 1 ano
  de histórico WTA, sem colunas de serviço/mão dominante/score detalhado.
  Isso deixaria o WTA com H2H de carreira fraco, e sem serviço/resposta,
  sinal de lesão, recuperação após 1º set, ou canhotos/destros. Vale a
  pena reconsiderar se aparecer uma fonte melhor de histórico WTA (20
  anos, com as colunas certas) — nesse caso, a mudança de código é
  pequena: acrescentar `"wta"` a `TOURS_TO_FOLLOW`, encontrar o
  `tournamentId` WTA do torneio combinado (ex: Washington também tem
  edição WTA 500) e acrescentar a `TRACKED_TOURNAMENT_IDS`.
- Mais fontes gratuitas: qualquer fonte nova só precisa de uma função
  `_load_<fonte>()` em `fetch_data.py` que devolva um DataFrame com pelo
  menos as colunas `winner_name`, `loser_name`, `surface`, `tourney_date`
  — as funções `compute_*` já funcionam em cima desse formato comum.
