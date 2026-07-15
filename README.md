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

## Fontes de dados usadas (todas gratuitas)

- **The Odds API** — fixtures próximos + odds de mercado (Slams, Masters
  1000/500). Tier gratuito, sem cartão de crédito.
- **TennisMyLife** (stats.tennismylife.org) — histórico de resultados e
  rankings, licença MIT, dataset atualizado incluindo o torneio da semana
  corrente. Fonte primária para H2H/forma/piso.
- **Jeff Sackmann — tennis_atp / tennis_wta** (GitHub) — fallback caso a
  TennisMyLife esteja indisponível. Licença CC BY-NC-SA (uso não comercial,
  com atribuição — ok para este projeto pessoal).
- **tennis-data.co.uk** — segunda fonte de fallback / cruzamento, CSV
  semanal com resultados, odds e piso.

Todas são APIs/downloads documentados — nenhuma é scraping de um site que
bloqueia pedidos não-oficiais (o problema que já tiveste com o Sofascore).

## Limitações conhecidas (aceites por design, tal como no bot de futebol)

- **Lesões**: não há nenhuma fonte gratuita fiável e estruturada para
  estado físico/lesões de tenistas. O campo `injury_data` vai sempre a
  `None`, e o prompt instrui o Claude a dizer explicitamente que não há
  esse dado — nunca a especular.
- **Piso**: é aproximado pelo nome do torneio (`_surface_guess` em
  `main.py`), não vem estruturado da The Odds API. Para torneios fora da
  lista conhecida assume "Hard" por defeito — considera expandir esse
  mapeamento à medida que aparecerem falsos positivos.
- **Fadiga**: é uma aproximação (nº de jogos nos últimos N dias a partir do
  histórico), não o calendário exato dia-a-dia do torneio em curso.
- **Dados desatualizados de terceiros**: tal como o caso do treinador
  errado no futebol, isto pode acontecer aqui também (ex: ranking
  desatualizado numa fonte). Não vale a pena complicar com correções
  manuais — se acontecer com frequência lidamos nessa altura.

## Extensibilidade

- Fase 2 (ATP/WTA 500): adiciona os `sport_key` correspondentes em
  `config.py` e ajusta `MIN_RANK_TO_INCLUDE_IF_LOWER_TIER` se quiseres
  filtrar por ranking nesses torneios menores.
- Mais fontes gratuitas: qualquer fonte nova só precisa de uma função
  `_load_<fonte>()` em `fetch_data.py` que devolva um DataFrame com pelo
  menos as colunas `winner_name`, `loser_name`, `surface`, `tourney_date`
  — as funções `compute_*` já funcionam em cima desse formato comum.
