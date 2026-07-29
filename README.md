# Tennis Pre-Live Bot

Bot de análise pré-live de ténis, gratuito, a correr em GitHub Actions.
Réplica do espírito do bot de futebol: recolhe dados reais de fontes
gratuitas/documentadas, pede ao Claude uma análise que nunca inventa
informação, e envia um resumo curto no Telegram com link para o relatório
completo no Telegra.ph.

## Fichas de jogador (base de conhecimento leve, 29/07/2026)

`src/player_profile.py` + `src/generate_profile.py` geram uma ficha
markdown por jogador (guardada em `knowledge/players/`), juntando num só
sítio tudo o que o bot já calcula disperso: forma (janelas de 5/10/20),
piso, serviço/resposta, recuperação após 1º set, set decisivo,
canhotos/destros, regresso de pausa, fase do torneio.

Princípio central: **cada número traz a amostra e um rótulo de
fiabilidade ao lado** ("amostra sólida" vs "⚠️ amostra muito pequena").
Não há modelo, pesos, nem previsão — é uma vista organizada dos factos,
para o utilizador (ex-tenista) cruzar com o que sabe.

Uso:
```
python -m src.generate_profile "Jannik Sinner" atp
python -m src.generate_profile "Aryna Sabalenka" wta
```

**Porque é a versão "leve" e não o sistema completo:** o parceiro do
projeto propôs (via ChatGPT) uma base de conhecimento quantitativa
completa — SQLite com 14 tabelas, modelos hierárquicos bayesianos,
partial pooling, efeitos por jogador, validação temporal, 6 fases.
Ficou decidido NÃO avançar com isso por agora, por duas razões: (1) é um
projeto de meses de engenharia; (2) o backtest (ver secção própria) já
mostrou que os sinais simples não batem o mercado — construir um modelo
sofisticado para afinar o peso de sinais sem vantagem comprovada seria
elegante mas provavelmente inútil. A versão leve dá o valor real
(perfil organizado por jogador) sem essa aposta. O caminho para o
sistema completo fica em aberto se algum dia for uma decisão consciente
de investir meses.

## Método de refinamento (experiência humana → regras no código)

O bot organiza os dados; o utilizador (ex-tenista) apanha os casos em
que os números enganam e cada um vira uma regra permanente no prompt do
Claude (`analyze.py`) ou num novo dado (`fetch_data.py`). Formato útil
para propor uma regra nova: "quando acontece X, o bot devia ter em conta
Y". Regras de leitura já aplicadas desta forma:

- **Fim de carreira (29/07):** stats de carreira (piso, set decisivo,
  etc.) de um ex-top que agora mal joga descrevem um jogador que já não
  existe. Amostra grande aqui = desconfiança, não fiabilidade. Cruzar
  sempre com `current_season_*` (jogos esta época) e ranking oficial ao
  vivo. Não sinalizar divergência a favor do jogador em declínio só
  porque a carreira dele parece melhor no papel.
- **Jovem em ascensão (29/07):** amostra pequena num piso não é fraqueza,
  é falta de tempo para acumular — o nível real pode ser bem superior.
- **Challenger/ITF (28/07):** hiato longo + ranking baixo pode ser só
  falta de cobertura do circuito principal, não inatividade real.

## Registo de decisões (para não repetir discussões)

- **Âmbito:** ATP + WTA, tiers Grand Slam / Masters 1000 / ATP-WTA 500 /
  WTA 1000. 250 excluído (sem odds fiáveis). ATP-only entre 16-28/07 por
  o Sackmann ter caído; revertido quando voltou.
- **O bot NÃO recomenda apostas** — sinaliza divergências (🔴/🟡/🟢) e dá
  contexto; a decisão é humana. Recusadas várias propostas de o
  transformar em sistema de apostas automático (Kelly, paper trading
  automático, execução). O relatório termina numa secção "🎯 Discrepâncias
  e mercados a observar" (29/07/2026): quando a leitura dos dados diverge
  do mercado, o bot usa julgamento para apontar QUE mercados vale a pena
  observar nesse caso concreto (handicap de games, total de sets, "ganha
  1 set", momentos de live como favorito a perder set/break) — sempre
  ligado a um número com amostra, sempre como sugestão de OBSERVAÇÃO e
  nunca de aposta. É a distinção-chave que o utilizador quis: o bot não
  prevê o vencedor melhor que o mercado (o backtest mostrou que não
  consegue), mas traduz a sua leitura em onde apontar os olhos.
- **Vantagem estatística:** testada a sério (backtest), não encontrada
  nos sinais simples. O bot é assumidamente uma ferramenta de research,
  não uma máquina de lucro.
- **Track record:** a fazer manualmente pelo utilizador ao longo do
  tempo (entradas fictícias de 1 unidade, provavelmente em Excel), não
  automatizado — decisão do utilizador, adiado para quando quiser.
- **Auditoria externa (ChatGPT, 28/07):** útil, apanhou bugs reais que
  foram corrigidos (ver secção Robustez: A3 falha silenciosa, B1 datas
  sem timezone, B2 token Telegraph, B3 limite Telegram, B4 RET em set
  decisivo, B5 ranking recuado, A6 fadiga aproximada, A7 docs
  contraditórias, .gitignore). Recusadas as recomendações que
  implicavam o sistema quantitativo completo (SQLite obrigatório, tirar
  a flag ao LLM, Elo, modelo residual) — mesmo motivo das fichas.
- **Planos RapidAPI:** decidido ficar no free por agora. PRO ($29) dá
  quota + stats avançadas mas não dá movimento de odds; ULTRA ($59) dá
  movimento de odds mas decidiu-se que provavelmente não aporta valor
  suficiente para justificar. Reavaliar se a quota free se tornar
  limitante na prática.

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
- **Desempenho vs canhotos/destros** (`compute_handedness_matchup_stats`)
  — taxa de vitória específica contra cada estilo, usando as colunas
  `winner_hand`/`loser_hand` já presentes no histórico.
- **Regresso após paragem longa** (`compute_return_from_layoff_stats`) —
  como o jogador se sai historicamente no primeiro jogo depois de uma
  pausa de 60+ dias. Ver limitação abaixo sobre jogadores de
  Challenger/ITF, onde este número pode enganar.
- **Set decisivo** (`compute_deciding_set_stats`) — taxa de vitória
  quando o jogo vai até ao set decisivo (3º em Bo3, 5º em Bo5).
- **Fase do torneio** (`compute_round_stage_stats`) — rondas iniciais vs
  finais, para identificar quem é inconsistente cedo mas forte "quando é
  a sério", ou o inverso.

Todas estas juntam-se numa secção final do relatório, **"🎾 Cenários para
live"**, estruturada como condicionais ("Se X acontecer: [dado +
lembrete curto]") — nunca como recomendação de aposta.

## Validação estatística (backtest) — resultado já obtido

Existe um script separado, `src/backtest.py` (workflow manual
`.github/workflows/backtest.yml`, não corre no agendamento normal), que
testa se os sinais do bot (H2H, forma, piso — sozinhos e combinados) têm
alguma vantagem real contra odds históricas (2015-2025, tennis-data.co.uk),
com metodologia cuidada para evitar fuga de informação temporal (ver
`LEAKAGE_SAFETY_BUFFER_DAYS` no próprio ficheiro).

**Resultado obtido (27/07/2026, gravado em `data/backtest_results/`):**
nos casos em que o sinal do bot diverge do favorito do mercado, o nosso
pick ganhou **menos** vezes do que a própria probabilidade implícita das
odds sugeria (H2H sozinho +1.7 p.p., forma +0.2, piso -0.1, combinado
+0.8 — todos dentro da margem de erro estatística, ou seja, sem
vantagem distinguível de ruído). **Conclusão:** estes três sinais
simples, tal como calculados hoje, não batem o mercado. Isto não invalida
o bot como ferramenta informativa — só confirma que não há "dinheiro
fácil" a encontrar com esta abordagem simples, e evita a falsa sensação
de vantagem que a análise textual, por si só, poderia sugerir.

## Calendário de torneios a seguir

Ver `CALENDARIO-2026.md` na raiz do repositório — lista os próximos
Grand Slam/Masters 1000/ATP 500 do ano, para saberes quando voltar e
adicionar o `tournamentId` seguinte a `TRACKED_TOURNAMENT_IDS`.

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

## Âmbito: ATP + WTA (revisto 28/07/2026)

O bot cobre **ATP e WTA** — Grand Slam, ATP Masters 1000/500, WTA
1000/500. Nível 250 continua excluído (ver decisão de tiers abaixo).

**Histórico da decisão:** entre 16/07 e 28/07 o âmbito foi só ATP,
porque os repositórios do Sackmann (única fonte profunda de histórico
WTA) desapareceram do GitHub com 404 real confirmado. Em 28/07
confirmámos ao vivo que o `tennis_wta` voltou a estar disponível
(via `raw.githubusercontent.com` — atenção: o jsDelivr manteve cache
antiga do 404 durante mais tempo, por isso trocámos para o raw direto),
e o WTA foi reativado de ponta a ponta: fixtures (id 16738 no
`TRACKED_TOURNAMENT_IDS`), tiers, odds (`tennis_wta_washington_open`),
histórico multi-ano do Sackmann, e H2H rico via matchstat (ver secção
própria acima).

`TOURS_TO_FOLLOW = ("atp",)` em `config.py` é atualmente **código morto
funcional**: as fixtures vão diretamente por `TRACKED_TOURNAMENT_IDS`
(que decide o tour por torneio), e essa constante só é usada pela função
antiga `fetch_all_upcoming_fixtures` (não chamada; mantida como
referência). Alterá-la não tem efeito no pipeline atual.

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

## H2H rico via matchstat para WTA (28/07/2026)

Descoberto ao explorar a mesma API que já usamos para fixtures: os
endpoints `getH2HMatches`/`getH2HStats` (secção "H2h" na Playground)
dão H2H detalhado — serviço, resposta, break points, sets decisivos,
tiebreaks, por piso/tier — **específico ao confronto entre dois
jogadores**, por ID matchstat, independente do Sackmann. Implementado
só para WTA (decisão explícita: o ATP já funciona bem com a
TennisMyLife/Sackmann, e isto usa a mesma quota de 50/dia da RapidAPI).

Cache própria (`H2H_CACHE_MAX_AGE_HOURS = 24`), já que H2H muda pouco de
um dia para o outro.

**Estado (28/07/2026): ativo em produção.** O `TRACKED_TOURNAMENT_IDS`
inclui o Washington WTA (16738, "Mubadala DC Open", confirmado via
getTournamentInfo), pelo que os jogos WTA passam no pipeline e o
`fetch_h2h_stats` é chamado para cada um.

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

## Robustez (correções acumuladas, 27-28/07/2026)

- **Flag mínima garantida por regra** (`_enforce_minimum_flag` em
  `main.py`): se faltarem odds de mercado E H2H ao mesmo tempo, o jogo
  nunca pode sair 🟢 — sobe automaticamente para 🟡, independentemente do
  que o Claude decida sozinho. É uma regra determinística, não um
  critério do modelo.
- **Reparação automática de JSON** (`json_repair`, em `analyze.py`): o
  Claude ocasionalmente gera JSON malformado (aspas não escapadas,
  vírgulas em falta) apesar da instrução — antes de desistir e cair no
  relatório de erro, tentamos reparar automaticamente.
- **Relatório completo: uma página do Telegra.ph POR JOGO**, não uma
  página única com todos os jogos do dia — evita o erro `CONTENT_TOO_BIG`
  quando há muitos jogos (confirmado na prática: um torneio inteiro com
  12 jogos excedia o limite de tamanho de uma única página).
- **Deduplicação de jogos por `id`**: o matchstat pode devolver o mesmo
  jogo mais do que uma vez entre pedidos.
- **Nomes com tolerância a acentos/variações** (`resolve_player_name`):
  compara por normalização + correspondência aproximada antes de
  desistir com "sem dados".
- **Cache de fixtures e de torneios** grava no próprio repositório
  (commit automático do workflow), com tempo de vida de 4h — equilíbrio
  entre poupar quota (50 pedidos/dia no plano free) e não ficar preso a
  dados desatualizados durante um torneio ativo.

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

## Extensibilidade

- **WTA: reativado em 28/07/2026** (ver secção "Âmbito" acima) — a nota
  anterior de "decisão pendente" deixou de se aplicar quando o
  repositório do Sackmann voltou a estar disponível. O histórico WTA vem
  do Sackmann multi-ano; o fallback continua a ser o tennis-data.co.uk
  (1 ano, colunas limitadas) se o Sackmann voltar a falhar.
- Mais fontes gratuitas: qualquer fonte nova só precisa de uma função
  `_load_<fonte>()` em `fetch_data.py` que devolva um DataFrame com pelo
  menos as colunas `winner_name`, `loser_name`, `surface`, `tourney_date`
  — as funções `compute_*` já funcionam em cima desse formato comum.
