# 🎾 Tennis Pre-Live Bot

Bot de análise **pré-live** de ténis (ATP/WTA). Para cada jogo de um torneio
seguido, recolhe dados de várias fontes, calcula um **motor de divergência
100% determinístico** (Python), gera um relatório visual, publica-o online e
envia um resumo para o Telegram.

> **Importante:** o bot **não recomenda apostas**. O Sharp Signals não trata o
> índice de evidência como probabilidade e não tenta reconstruir o mercado do
> zero. Usa a probabilidade de mercado sem margem como baseline e aplica um
> ajuste residual experimental, limitado e derivado dos seus indicadores.
> A camada de pricing está em desenvolvimento e validação fora da amostra.
> Fair odds e expected edge são estimativas experimentais, não recomendações
> de aposta validadas; a decisão continua a ser humana.

---

## Índice

- [Como funciona](#como-funciona)
- [Arquitetura e ficheiros](#arquitetura-e-ficheiros)
- [O motor de divergência](#o-motor-de-divergência)
- [Fontes de dados](#fontes-de-dados)
- [O relatório](#o-relatório)
- [Custos e otimizações](#custos-e-otimizações)
- [Configuração](#configuração)
- [Como correr](#como-correr)
- [Histórico de bugs corrigidos (11-12/08/2026)](#histórico-de-bugs-corrigidos)
- [O que falta fazer](#o-que-falta-fazer)

---

## Como funciona

Fluxo de uma execução (`python -m src.main`):

1. **Descobrir torneios automaticamente** — lê o feed "all upcoming matches"
   da RapidAPI (mesmo usado para as odds), agrupa por torneio, e filtra pelo
   tier permitido (`ALLOWED_TOURNAMENT_TIERS`). **Não é preciso trocar IDs
   manualmente a cada torneio novo** — só serve como rede de segurança se a
   descoberta falhar (`TRACKED_TOURNAMENT_IDS` em `config.py`).
2. **Buscar fixtures** de cada torneio descoberto via RapidAPI.
3. **Filtrar** por janela temporal e deduplicar.
4. **Indexar odds** (Moneyline) do mesmo feed all-upcoming — chamadas
   separadas por tour (`ms-api/upcoming/matches/atp` e `.../wta`; o tour é um
   segmento do URL, não um query param).
5. Para cada jogo, **recolher dados**: H2H (global e por piso), forma, época,
   ranking, piso, fadiga, serviço/resposta, recuperação de sets, matchup de
   mão, regresso após paragem, meteorologia.
6. **Calcular o motor de divergência** (Python, `_calcular_divergencia`) —
   índice de evidência 0-100, classificação (nível 0-3), fatores-chave, e o
   estado de **todos** os fatores (não só os que contribuíram).
7. **Calcular o Market-Residual Pricing v0.1** — remove a margem das duas odds,
   aplica em log-odds um residual pequeno e limitado pela qualidade da evidência
   e produz estimativa Sharp, fair odd e expected edge para ambos os jogadores.
   O índice de evidência determina apenas direção/magnitude; nunca é usado como
   probabilidade.
8. **Chamar o Claude** só quando o motor justifica (ver
   [O motor de divergência](#o-motor-de-divergência)) — devolve só a *análise*
   (resumo executivo + veredicto), nunca recalcula nem contradiz o motor.
9. **Montar o relatório HTML** (o Python monta as secções de dados e o
   "Fatores Detalhados"; o Claude só contribui com 2 frases finais quando é
   chamado).
10. **Publicar** no GitHub Pages, enviar o resumo para o Telegram e, depois
    do push, um único digest HTML por email com todos os jogos e links.

---

## Arquitetura e ficheiros

Todos em `src/`:

| Ficheiro | Função |
|---|---|
| `config.py` | Configuração central: torneios seguidos (fallback), tiers permitidos, modelo, janelas, URLs, flags. |
| `main.py` | Orquestra a execução: descobre torneios, busca jogos, monta o payload (incl. H2H por piso e matchup de mão), chama a análise, gera o site, envia Telegram. |
| `fetch_data.py` | Recolha de dados de todas as fontes (RapidAPI, históricos, odds, meteo). Descoberta automática de torneios, cálculo de H2H (global+piso), forma, fadiga, matchup de mão, etc. |
| `analyze.py` | Política de quando chamar o Claude (`_evaluate_selective_policy`), prompt, fallback determinístico (`_build_selective_result`), validação pós-Claude, recuperação parcial, cache. |
| `pricing.py` | Market-Residual Pricing v0.1: de-vig, residual limitado em log-odds, fair odds, expected edge, gates de qualidade e fingerprint de configuração. |
| `report_html.py` | O **motor de divergência** (`_calcular_divergencia`) e a geração do relatório HTML completo (secções de dados + "Fatores Detalhados" + análise). |
| `email_digest.py` | Manifesto, HTML/texto e envio SMTP do digest único de cada execução publicável. |
| `llm_provider.py` | Wrapper da chamada à API Anthropic (`AnthropicProvider`), mock e provider desativado. |
| `telegram_bot.py` | Envio das mensagens para o Telegram. |
| `test_dry_run.py` | Teste de ponta a ponta sem gastar API (usa mock; API real com `USE_REAL_LLM=1`). |
| `backtest.py`, `player_profile.py`, `generate_profile.py`, `telegraph.py` | Utilitários / legado. |

Workflow: `.github/workflows/tennis-bot.yml` (GitHub Actions).

---

## O motor de divergência

O coração do bot é `_calcular_divergencia` (`report_html.py`) — **100%
determinístico, o Claude nunca recalcula nem tem autoridade sobre isto.**

### Índice de evidência
Não é uma probabilidade — é a **quota do peso total** dos sinais disponíveis
que aponta para cada jogador (0-100). Se todos os sinais concordam, pode
legitimamente bater em 100/0; isso não é bug, é o índice a fazer o que promete.
Quando o índice é extremo (≥95 ou ≤5) com poucos sinais (≤3), o relatório
mostra uma nota de transparência a avisar disso.

### Pesos dos fatores (`PESOS` em `report_html.py`)

| Fator | Peso | Nota |
|---|---|---|
| **H2H no piso** | 12 | O mais alto — confronto direto NESTE piso, mais específico que o global |
| Piso (superfície) | 10 | |
| Recuperação de sets | 9 | Sets decisivos / recuperar 1 set abaixo |
| Matchup de mão | 8 | Canhoto vs destro — taxa de vitória contra a mão real do adversário |
| **H2H global** | 6 | Desceu de 10 → 6 (o piso é mais relevante) |
| Forma recente | 7 | |
| Ranking | 5 | Só conta se a diferença for ≥5 posições |
| Regresso após paragem | 5 | Só ativa em regressos claros (≥60 dias parado) |
| Fadiga | 4-7 | Sobe para 7 se o último jogo foi longo |
| Época atual | 4 | |
| Serviço | 4 | |
| Meteorologia | 1 | Não implementado como fator direcional (decisão consciente) |

Fatores correlacionados (H2H, piso, matchup de mão) ficam na mesma "família"
com um teto conjunto, para não contar a mesma informação várias vezes.

### Classificação (nível 0-3)
- **Nível 0** — Mercado e indicadores apontam para o mesmo jogador.
- **Nível 1** — Divergência direcional ligeira.
- **Nível 2** — Divergência direcional moderada.
- **Nível 3** — Divergência direcional forte.

O índice interno (0-100) mede concentração dos sinais e **não é uma
probabilidade prevista**. Por isso, nunca se subtrai à probabilidade implícita
do mercado nem é convertido diretamente numa odd. Na camada experimental de
pricing, apenas determina a direção e a força normalizada de um residual
limitado aplicado à probabilidade de mercado sem margem. O motor determinístico
continua independente e interpretável; o alinhamento, por si só, não prova
subvalorização.

### Market-Residual Pricing v0.1

A cadeia económica é: `odds observadas → probabilidade de-vig → motor de
evidência → residual limitado em log-odds → estimativa Sharp → fair odd →
expected edge`. A fórmula é:

`logit(P_sharp) = logit(P_market) + MAX_LOGIT_SHIFT × signed_strength × quality`

onde `signed_strength = (indice_evidencia_a - 50) / 50`, limitado a `[-1,1]`.
`quality` reduz o residual quando há poucos fatores, pouca massa efetiva ou
baixa intensidade. A promoção inicial exige expected edge ≥5%, pelo menos dois
fatores, qualidade mínima e Moneyline válida dos dois lados. Todos estes
parâmetros, a versão `market-residual-v0.1` e um hash determinístico ficam
congelados no snapshot pré-jogo. A magnitude inicial é uma hipótese de
modelação, não calibração empírica concluída.

### Quando o Claude é chamado
Só nos casos onde a interpretação paga acrescenta valor sobre o texto
determinístico (que já usa a classificação do motor):
- **Nível 3** (divergência direcional forte).
- **"Sinais fortemente contraditórios"** — os fatores internos discordam muito
  entre si (≥2 líderes diferentes, ≥4 sinais), mesmo com nível de mercado
  baixo — vale a interpretação porque é difícil de resumir com um template.

Nível 0-2 usa sempre o fallback determinístico (`_build_selective_result`),
que constrói o texto a partir da classificação oficial do motor — nunca
diverge da "Leitura" do topo do relatório.

### Validação pós-Claude
Quando o Claude é chamado, a resposta é validada contra o motor
(`_save_and_return` em `analyze.py`) antes de ser aceite:
- Favorece o jogador errado? → rejeitado, cai no fallback.
- Diz "eficiente" quando há divergência (ou vice-versa)? → rejeitado.
- Apresenta alinhamento como divergência, valor ou subvalorização? → rejeitado.

### "Fatores Detalhados"
Módulo no relatório (colapsável) que mostra **todos** os ~11 fatores, não só
os 3-4 que mais pesaram — incluindo os que não contribuíram, com o motivo
("sem dados", "empate", "amostra insuficiente", "abaixo do limiar"). Gerado
100% em Python a partir de `fatores_status` (devolvido por
`_calcular_divergencia`, propagado por `_normalizar_div`).

### Aproveitamento dos dados já recolhidos

- **Forma ajustada ao mercado** — nos jogos históricos com duas odds válidas,
  remove a margem proporcionalmente e compara vitórias reais com vitórias
  esperadas. É uma medida retrospetiva em unidades de vitória, não uma previsão.
- **Qualidade da oposição** — mostra o ranking médio dos adversários da época e
  a respetiva amostra, sem o converter num score arbitrário.
- **Pressão de serviço e resposta** — agrupa primeiro/segundo serviço, break
  points e eficácia permitida aos adversários numa comparação direta, mantendo
  as percentagens e amostras originais em vez de fabricar um índice opaco.
- **Perf-breakdown temporal** — novas respostas preservam `raw` e `by_year`
  (ranking, piso, nível e ronda), além dos agregados existentes, permitindo
  calcular evolução e momentum sem nova chamada à API.
- **Surface Momentum** — compara a taxa de vitória de carreira no piso atual
  com os dois anos mais recentes, mostrando diferença, anos e amostra; só
  aparece quando existem pelo menos cinco jogos recentes nesse piso.
- **Desempenho por ronda** — as novas respostas também preservam um agregado
  `by_round`, além da divisão anual original.

Estas métricas aparecem dentro do Mapa de Forças e, nesta fase, não alteram o
motor nem a prioridade dos jogos. Índices compostos de serviço, resposta,
domínio, estilo e clutch só devem receber peso após calibração/backtest; um
score 0-100 não calibrado criaria falsa precisão semelhante ao problema já
corrigido no índice de sinais.

A cobertura pode ser acompanhada sem rede nem custos com:
`python scripts/analyze_advanced_metric_coverage.py`.

Cada execução publicável guarda ainda em `data/calibration_snapshots.json` uma
fotografia compacta das odds, métricas e sinal disponíveis antes do jogo. Uma
repetição não substitui a primeira fotografia. O workflow reconcilia depois o
vencedor usando apenas as caches locais de jogos terminados, sem chamadas
adicionais à RapidAPI. Assim, futuros índices compostos podem ser validados
fora da amostra antes de influenciarem o relatório.

---

## Fontes de dados

### Dados e odds (RapidAPI — plano **Pro**, 5000 chamadas/dia)
- Base: `https://tennis-api-atp-wta-itf.p.rapidapi.com/tennis/v2/`
- **Descoberta de torneios + odds**: `ms-api/upcoming/matches/{atp|wta}` —
  o tour é um segmento do URL, não query param. Cada jogo já vem com
  `tournament.id/name`, odds embutidas (`player.odd`), e `type` (atp/wta).
- **Fixtures** por torneio, **rankings** oficiais.
- **Dados ricos de carreira** (`getH2HVsAllOppStats`): cenários de 1º set,
  set decisivo, tie-breaks, resposta, estilo — sujeito a orçamento limitado
  por execução + cache local (`knowledge/players/`).
- **Perfil do jogador** (`ms-api/profile/{nome}`): mão dominante (`plays`),
  usado tanto para `player_hands` do jogo atual como para o matchup de mão.
- **Jogos recentes** (`past-matches`): fadiga real e recuperação de sets.
- A cache de jogos recentes dura **4 horas**: evita repetir chamadas na mesma
  execução sem esconder um resultado da véspera no relatório do dia seguinte.
- **Fichas ricas consolidadas**: cada jogador analisado fica guardado em
  `knowledge/players/<tour>/<id>-<nome>.json`, com identidade, versão do
  esquema e data de atualização. O workflow publica essas fichas para serem
  reutilizadas em execuções futuras, reduzindo chamadas e inconsistências;
  por omissão são renovadas após 30 dias (`PLAYER_SHEET_MAX_AGE_DAYS`).
- Consumo medido: registado em `data/rapidapi_usage_log.json`.

### Históricos (fallback)
- **TennisMyLife** (ATP, 10 anos) — fonte principal do histórico ATP, inclui
  `winner_hand`/`loser_hand` (necessário para o matchup de mão).
- **tennis-data.co.uk** (WTA, 10 anos) — fonte principal do histórico WTA.
  **Não tem colunas de mão** — por isso o matchup de mão para WTA vem só do
  perfil RapidAPI (`player_hands`), não do histórico de confrontos.
- **Sackmann** (`JeffSackmann/tennis_wta` no GitHub) — **desativado para WTA**
  (12/08/2026): o repositório devolve 404 para todos os anos, confirmado em
  testes reais. Mantido como fallback só para ATP (raramente ativado, a
  TennisMyLife cobre quase tudo).
- Quando as fontes divergem, a RapidAPI ganha e a discrepância é registada no
  log (`[fontes]`).

### Análise (Anthropic)
- Modelo: **`claude-sonnet-5`**.
- **Não aceita "assistant message prefill"** — confirmado por erro real de
  API (`This model does not support assistant message prefill`). Não tentar
  reintroduzir essa técnica sem confirmar primeiro que o modelo em uso aceita.

---

## O relatório

Estrutura, de cima para baixo:

1. **Cabeçalho** — jogadores, forma, torneio, odds, probabilidade de mercado e,
   quando disponíveis, fonte e instante de captura das odds.
2. **Leitura** — 1 frase, sempre gerada por Python, com a bola de estado
   (🟢 forte / 🟡 ligeiro / ⚪ eficiente).
3. **Sharp Pricing — Market Residual** — para os dois jogadores mostra
   probabilidade de mercado sem margem, estimativa Sharp, ajuste em p.p., fair
   odd, odd observada e expected edge, sempre marcado `EXPERIMENTAL — EM
   VALIDAÇÃO`. A antiga faixa indicativa deixa de decidir valor e permanece
   apenas como infraestrutura/contexto legado.
4. **Fatores principais** (chips) — apenas os fatores existentes que mais
   pesaram na classificação; não são criados cartões vazios para completar uma grelha.
5. **Mercado e indicadores** — barras lado a lado, identificadas como escalas
   diferentes e não subtraíveis.
6. **Mercado observado** — aparece apenas quando existe divergência direcional
   e mostra somente Moneyline. Total Games e Handicap não são apresentados sem
   odds e modelos próprios.
7. **Cenários decisivos** — secção factual visível quando diferencia os jogadores.
8. **Mapa de Forças** (colapsável) — todos os ~11 fatores do motor, incluindo
   os detalhes de forma, época, serviço/resposta, carga e H2H. Começa fechado
   para não dominar nem duplicar a leitura inicial.
9. **Veredicto/Leitura final** — texto do Claude (nível 3 / contraditórios) ou
   o fallback determinístico (nível 0-2), sempre coerente com a classificação.

> Linguagem: o relatório distingue o favorito do mercado da fair odd
> experimental. Um expected edge é sempre identificado como estimativa em
> validação, nunca como lucro garantido, aposta ou recomendação.

---

## Custos e otimizações

Duas contas separadas:
- **RapidAPI** (dados): plano Pro, 5000 chamadas/dia.
- **Anthropic** (análise): pago ao uso.

### Chamadas ao Claude — só quando compensa
Desde 12/08/2026, o Claude só é chamado em **nível 3** ou **"contraditórios"**
(antes era nível ≥2). Confirmado em log real, mesmo conjunto de 73 jogos:
**43 → 18 chamadas (-58%)**. Nível 0-2 usa sempre o fallback determinístico,
que já está alinhado com o motor (mesma classificação, favorecido e fatores).

### Outras otimizações
- **Cache do prompt de sistema** (`cache_control: ephemeral`) — input repetido
  reaproveitado entre chamadas.
- **Cache de análises** por hash — jogos iguais não são repagos.
- **Payload enxuto** — o que vai ao Claude remove campos duplicados já
  resumidos nas `features`.
- **Recuperação parcial** — se a resposta do Claude é cortada, extrai os
  campos que vieram completos antes de cair no fallback total.
- **Fallback nunca apaga jogos** — se a chamada à API falhar por qualquer
  razão (rede, rate limit, etc.), cai no texto determinístico em vez de
  descartar o jogo do relatório (corrigido 11/08/2026 — antes uma falha da
  API fazia o jogo desaparecer silenciosamente).

Estado atual: `max_tokens=1500` (teto de segurança — o custo típico não muda
com o teto, só protege contra casos-limite; a maioria das chamadas reais usa
128-180 tokens de output). Execução de 73 jogos, 18 chamadas ao Claude: ~39
cêntimos antes do ajuste do limiar; espera-se bem menos agora.

---

## Configuração

Principais em `src/config.py`:

| Variável | Valor atual | Nota |
|---|---|---|
| `TRACKED_TOURNAMENT_IDS` | Rede de segurança (usada só se a descoberta automática falhar) | Já não é preciso trocar a cada torneio |
| `ALLOWED_TOURNAMENT_TIERS` | Tiers elegíveis para a descoberta automática | Define o que conta como "torneio a seguir" |
| `CLAUDE_MODEL` | `claude-sonnet-5` | Não aceita prefill |
| `PRICING_MAX_LOGIT_SHIFT` | `0.30` | Teto experimental do residual em log-odds |
| `PRICING_MIN_EDGE_PCT` | `5.0` | Limiar inicial de edge experimental |
| `PRICING_MIN_FACTORS` | `2` | Gate mínimo de fatores contribuintes |
| `PRICING_MIN_QUALITY` | `0.45` | Gate mínimo da qualidade combinada |
| `HISTORY_YEARS_TO_LOAD` | 10 | |
| `SITE_BASE_URL` | `https://sharp-signals.github.io/Tennis` | GitHub Pages |
| `SITE_OUTPUT_DIR` | `docs` | Pasta publicada |

### Secrets (GitHub Actions)
`ANTHROPIC_API_KEY`, `RAPIDAPI_KEY`, `ODDS_API_KEY`, `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_CHAT_ID`.

Para o digest por email:

- `REPORT_EMAIL_SMTP_USERNAME` e `REPORT_EMAIL_SMTP_PASSWORD` — conta SMTP e
  palavra-passe de aplicação;
- `REPORT_EMAIL_TO` — destinatários separados por vírgulas;
- opcionais: `REPORT_EMAIL_FROM`, `REPORT_EMAIL_SMTP_HOST` (por omissão
  `smtp.gmail.com`) e `REPORT_EMAIL_SMTP_PORT` (por omissão `465`).

Os endereços e credenciais nunca são gravados no repositório. Se os secrets
obrigatórios ainda não existirem, o workflow publica normalmente os relatórios
e regista que o envio foi ignorado.

### Publicação
GitHub Pages: **Settings → Pages → Deploy from a branch → `main` → `/docs`**.

---

## Como correr

- **Manual:** GitHub → Actions → "Tennis Pre-Live Bot" → *Run workflow*.
- **Automático:** ver `.github/workflows/tennis-bot.yml` para o schedule atual.
- **Teste local sem custo:** `python -m src.test_dry_run` (usa mock).

---

## Histórico de bugs corrigidos (11-12/08/2026)

Sessão longa de correções — registo para não repetir o mesmo erro:

1. **Odds WTA em falta** — o endpoint `ms-api/upcoming/matches` sem tour só
   devolvia ATP. O tour é um **segmento do URL**, não query param. Corrigido
   para chamar `.../matches/atp` e `.../matches/wta` separadamente.
2. **Sackmann WTA morto** — repositório GitHub devolve 404 para todos os anos.
   Desativado só para WTA (ATP continua com Sackmann como fallback raro).
3. **Descoberta automática de torneios** — reaproveita o feed de odds
   (já tem `tournament.id`) em vez de manter uma lista manual de IDs.
4. **Bug de chave `market` vs `prob_mercado_a`** (3 ocorrências) — o payload
   cru de `_calcular_divergencia` nunca teve a chave `"market"`, só
   `prob_mercado_a`. Isto fazia: (a) o Claude nunca ser chamado mesmo com
   divergência real, (b) o fallback calcular um "dominante" à parte em vez de
   usar o motor, (c) a validação pós-Claude nunca correr. Todos corrigidos.
5. **`matchup_maos` sempre morto** — o motor lia
   `handedness_matchup_a.get("win_pct")`, chave que nunca existia (a função
   só devolvia `vs_left_handed`/`vs_right_handed`). Nova função
   `resolve_handedness_matchup` liga a mão real do adversário ao sub-dado
   certo.
6. **`recuperacao_sets` só via fonte com orçamento limitado** — ignorava
   `deciding_set_stats_a/b` (mais disponível). Adicionado fallback com
   extração das duas formas possíveis (plana RapidAPI / bo3+bo5 Sackmann).
7. **`lesao` só funcionava por uma via** — lia `days_out`, campo que só
   existe na variante RapidAPI; o fallback histórico usa outro conceito
   (`win_rate_pct`, taxa histórica, não "está a regressar agora"). Trocado
   para `days_since_last_match` do sinal de fadiga, consistente nas duas
   fontes.
8. **`fadiga` — escalada "jogo longo" morta** — lia `last_match_sets`, campo
   nunca preenchido. Adicionado às duas fontes de fadiga.
9. **H2H por piso não existia** — `compute_h2h` já calculava `on_surface` mas
   nada o lia. Novo fator `h2h_piso` (peso 12), H2H global desceu para 6.
10. **`_normalizar_div` esquecia campos novos** — `fatores_status`/`n_fatores`
    eram calculados mas descartados nesta função intermédia. O módulo
    "Fatores Detalhados" e a nota de índice frágil nunca apareciam no HTML
    real, apesar do CSS estar presente. Corrigido.
11. **Prefill de assistente partiu 100% das chamadas** — tentativa de poupar
    tokens com `{"role": "assistant", "content": "{"}` causou erro 400 em
    todas as chamadas (`claude-sonnet-5` não aceita prefill). Revertido.
12. **Falha da API apagava o jogo do relatório** — `provider.generate()` sem
    `try/except`; uma exceção propagava até ao `main.py` e o jogo
    desaparecia silenciosamente. Agora cai sempre no fallback determinístico.
13. **Índice interno tratado como probabilidade** — a comparação de magnitudes
    criava falsos gaps em p.p. e “convicção” no mesmo lado do mercado. Agora a
    comparação é apenas direcional; alinhamento não é apresentado como valor.

---

## Controlo operacional e validação

- Produção instala `requirements.lock`; `requirements.txt` mantém os intervalos
  aceites para atualizações deliberadas.
- Cada execução grava estado, fase, duração, chamadas RapidAPI por endpoint,
  tokens, custo LLM estimado e falhas. Os preços são configuráveis por variáveis
  `LLM_PRICE_*` e devem ser confirmados contra a faturação real.
- Cada snapshot pré-jogo congela a versão, configuração/hash, baseline de-vig,
  estimativa Sharp, fair odds, expected edge e candidato antes do encontro. Uma
  repetição nunca substitui a primeira fotografia; o resultado só é anexado
  posteriormente, preservando validação OOS honesta.
- A quota RapidAPI tem checkpoint incremental. Em falha ou timeout, o workflow
  preserva apenas telemetria — nunca publica relatórios parciais.
- Alertas de consumo, fallback LLM, custo e relatórios falhados são configuráveis
  por `ALERT_RAPIDAPI_CALLS`, `ALERT_LLM_FALLBACK_RATE` e `ALERT_LLM_COST_USD`.
- O backtest usa apenas história anterior ao jogo e apresenta ROI flat-stake,
  lucro em unidades, drawdown, intervalo de confiança, resultados anuais
  walk-forward e baselines. Continua a ser validação histórica, não promessa.
- No índice, verde significa exclusivamente “valor a analisar”; mercado alinhado
  é neutro, amarelo é acompanhamento e vermelho é prioridade alta.
- Uma métrica comparativa só atribui peso quando os dois jogadores têm dados
  equivalentes. A ausência de um lado é “indisponível”, nunca zero ou derrota.
- “Desempenho face ao esperado” identifica a subamostra com odds históricas,
  mostra a cobertura e separa os jogos/vitórias excluídos por falta de odds.

## O que falta fazer

### 🟡 A validar continuamente
- [ ] Confirmar o motor em mais jogos de divergência forte/moderada,
      contraditórios e sem edge — feito uma ronda (11-12/08), sem falsos
      negativos encontrados, mas vale a pena repetir com mais volume.
- [ ] Confirmar `h2h_piso` a disparar com dados reais (nos exemplos vistos
      até agora apareceu sempre "sem dados" — plausível dado serem confrontos
      raros, mas ainda não confirmado num caso com histórico real no piso).

### 🟢 Ideias futuras (não urgentes)
- [ ] Mais padrões de mercado na biblioteca de raciocínios (tie-break
      specialists, etc.).
- [ ] Haiku preparado mas desligado — modelo mais barato para a análise, a
      ligar só se o volume justificar e a qualidade aguentar.
- [ ] Terceira fonte de histórico WTA como reforço (dado que a Sackmann WTA
      está permanentemente indisponível).
- [ ] Remover as funções mortas do Sackmann-WTA do código (hoje ficam
      definidas mas nunca chamadas) se a decisão de as manter como rede de
      segurança deixar de fazer sentido.

---

*Projeto pessoal. Análise informativa, não é recomendação de aposta.*
