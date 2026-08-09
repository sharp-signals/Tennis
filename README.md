# 🎾 Tennis Pre-Live Bot

Bot de análise **pré-live** de ténis (ATP/WTA). Para cada jogo de um torneio
seguido, recolhe dados de várias fontes, gera um relatório visual com uma
**leitura de mercado** (discrepâncias e pontos a observar), publica-o online
e envia um resumo para o Telegrram.

> **Importante:** o bot **não recomenda apostas** e **não calcula edge nem
> probabilidade própria**. Sinaliza divergências entre os dados e o mercado e
> sugere **mercados a observar** — a decisão é sempre humana. Fala em "favorito
> do mercado" (não "justo") e nunca afirma que "há valor de X%": esta é uma
> decisão informada, validada por backtest (um modelo preditivo próprio não
> mostrou vantagem consistente sobre o mercado).

---

## Índice

- [Como funciona](#como-funciona)
- [Arquitetura e ficheiros](#arquitetura-e-ficheiros)
- [Fontes de dados](#fontes-de-dados)
- [O relatório](#o-relatório)
- [Custos e otimizações](#custos-e-otimizações)
- [Configuração](#configuração)
- [Como correr](#como-correr)
- [O que falta fazer](#o-que-falta-fazer)

---

## Como funciona

Fluxo de uma execução (`python -m src.main`):

1. **Buscar jogos** do(s) torneio(s) seguido(s) via RapidAPI.
2. **Filtrar** por janela temporal e por tier/elegibilidade.
3. Para cada jogo, **recolher dados**: H2H, forma, época, ranking, piso,
   fadiga, serviço/resposta, meteorologia, odds, e dados ricos de carreira.
4. **Analisar** com o Claude (Sonnet), quando o motor deteta divergência
   relevante — devolve só a *análise* (resumo executivo + veredicto), a partir
   da classificação do motor, não o relatório todo.
5. **Montar o relatório HTML** (o Python monta as secções de dados; o Claude
   fornece a análise).
6. **Publicar** no GitHub Pages e **enviar resumo** para o Telegram.

---

## Arquitetura e ficheiros

Todos em `src/`:

| Ficheiro | Função |
|---|---|
| `config.py` | Configuração central: torneios seguidos, modelo, janelas, URLs, flags. |
| `main.py` | Orquestra a execução: busca jogos, monta o payload, chama a análise, gera o site, envia Telegram. |
| `fetch_data.py` | Recolha de dados de todas as fontes (RapidAPI, históricos, odds, meteo). Cálculo de H2H, forma, fadiga, etc. |
| `analyze.py` | Chamada ao Claude com o prompt de análise. Formato estruturado, recuperação parcial, cache. |
| `report_html.py` | Geração do relatório HTML (secções de dados + gráficos + análise). |
| `telegram_bot.py` | Envio das mensagens para o Telegram. |
| `test_dry_run.py` | Teste de ponta a ponta sem gastar API (usa mock; API real com `USE_REAL_LLM=1`). |
| `backtest.py`, `player_profile.py`, `generate_profile.py`, `telegraph.py` | Utilitários / legado. |

Workflow: `.github/workflows/tennis-bot.yml` (GitHub Actions).

---

## Fontes de dados

### Dados (RapidAPI — plano **Pro**, $29/mês)
- **Fixtures** dos torneios, **rankings** oficiais.
- **Dados ricos de carreira** (`getH2HVsAllOppStats`): cenários de 1º set,
  set decisivo, tie-breaks, resposta, estilo (winners/erros/rede/duração),
  e **opponentStats** (o que os adversários fazem contra o jogador).
- **Desempenho por nível de adversário** (`perf-breakdown`): vs top 10/50/100.
- **Desempenho por piso específico** (`perf-breakdown`): registo de carreira
  no piso exato do jogo, com hard indoor/outdoor separados.
- **Jogos recentes** (`past-matches`): para a **fadiga real** (inclui os jogos
  do torneio em curso).
- Base: `https://tennis-api-atp-wta-itf.p.rapidapi.com/tennis/v2/`
- Consumo medido: **~18-26 chamadas por execução** (varia com dados ricos e
  fadiga). Registado em `data/rapidapi_usage_log.json`.

### Dados de jogos e estatísticas (RapidAPI — fonte principal)
- **RapidAPI** (`tennis-api-atp-wta-itf`, plano PRO) é a fonte **principal** de
  forma, época, piso, H2H, fadiga, serviço/resposta, sets decisivos, mão e
  regresso após paragem. Cobre ATP e WTA de forma consistente.
- Os históricos gratuitos (TennisMyLife ATP, tennis-data.co.uk WTA, Sackmann)
  ficam como **fallback**: só entram quando a RapidAPI não tem o dado. Quando as
  fontes divergem, a RapidAPI ganha e a discrepância é registada no log
  (`[fontes]`).
- Profundidade histórica: **10 anos** (`HISTORY_YEARS_TO_LOAD`).

### Odds (RapidAPI)
- As odds (Moneyline) vêm da **RapidAPI** (endpoint `recent-odds`), casadas por
  event ID. Probabilidade de mercado sem margem calculada no cabeçalho. Sem
  odds, o motor não classifica divergência (o jogo fica assinalado "sem odds").

### Análise (Anthropic)
- Modelo: **`claude-sonnet-5`**. Escolha deliberada de manter o Sonnet (não
  Haiku) para preservar a qualidade do julgamento de mercado.

---

## O relatório

Estrutura, de cima para baixo:

1. **Cabeçalho** — jogadores, ranking, odds, probabilidade de mercado sem
   margem, e a **bola do motor** (🟢 oportunidade forte / 🟡 acompanhar /
   🔴 mercado eficiente / ⚪ sem odds). Mostra o **índice de evidência**
   (0-100 a favor de quem os indicadores apoiam) e a **cobertura de dados**
   (quantas fontes presentes, chips ✓/✗).
2. **Gráficos** — Serviço/Resposta, Forma recente, Desempenho vs adversário.
3. **Secções de dados** (montadas em Python, números sempre certos):
   H2H, forma/época, ranking, piso, fadiga, cenários de jogo (sets decisivos,
   recuperação de 1º set), matchup de mão, regresso após paragem, meteo, mercado.
4. **Indicadores vs Mercado** — o índice de evidência de cada jogador vs a
   probabilidade de mercado; comparação **direcional** (concordam = mercado
   eficiente; discordam = divergência classificada em ligeira/moderada/forte).
5. **Fatores decisivos** — os pesos que sustentam a leitura, com **barras de
   intensidade** (forte/moderado/fraco). As cores (🟢🟡🔴) ficam reservadas à
   conclusão/divergência, para o vermelho ter um só significado.
6. **Veredicto** — a leitura de trader: onde está (ou não) o valor, pré-live
   ou ao vivo.

### Padrões de mercado que o bot caça (no veredicto)
1. **Recuperação de 1º set** — entrada após perder o 1º set, se recupera bem.
2. **Vai a 3 sets** — "mais de 2.5 sets" quando ambos fortes em decisivo.
3. **Domínio frágil** — valor no underdog quando o favorito ganha por erro
   alheio (não por winners próprios).
4. **Fadiga vs fresco** — o mais fresco / over games quando há desgaste
   acumulado.

> Regra de ouro: o mercado sugerido corresponde **exatamente** à estatística
> (ex: "fecha o jogo após 1º set" ≠ "vence 2-0" — inclui 2-1).

---

## Custos e otimizações

Duas contas separadas:
- **RapidAPI** (dados): plano Pro $29/mês.
- **Anthropic** (análise): pago ao uso.

Otimizações já implementadas:
- **Cache do prompt de sistema** (input repetido a ~10%).
- **Cache de análises** por hash (jogos iguais não são repagos; invalida por
  `PROMPT_VERSION`).
- **"Medida 6"** — o Python monta as secções de dados; o Claude devolve só a
  análise. Cortou o output ~60% e garante números sempre certos. Mesmo que a
  análise falhe, os dados persistem no relatório.
- **Recuperação parcial** — se a resposta do Claude é cortada, extrai os campos
  que vieram completos (nunca perde a análise toda).
- **Payload enxuto** — remove do que vai ao Claude campos duplicados que já
  vêm no `rich_stats`.
- **1x/dia** — execução única de manhã (05:00 UTC) com janela alargada
  (0-36h) para cobrir o dia inteiro. Corta ~50% em ambas as contas.

Estado atual: `max_tokens=1500`, output médio ~400-600 tokens/jogo (o Claude
recebe a classificação do motor e escreve a partir dela — resumo executivo de
4 frases + veredicto, sem divagar). Execuções recentes custaram ~9-16 cêntimos.

---

## Configuração

Principais em `src/config.py`:

| Variável | Valor atual | Nota |
|---|---|---|
| `TRACKED_TOURNAMENT_IDS` | Canadian Open (21337 ATP, 16739 WTA Toronto) | **Trocar a cada torneio novo** |
| `CLAUDE_MODEL` | `claude-sonnet-5` | |
| `HISTORY_YEARS_TO_LOAD` | 10 | |
| `LOOKAHEAD_HOURS_MIN/MAX` | 0 / 36 | Janela para 1x/dia |
| `SITE_BASE_URL` | `https://sharp-signals.github.io/Tennis` | GitHub Pages |
| `SITE_OUTPUT_DIR` | `docs` | Pasta publicada |

### Secrets (GitHub Actions)
`ANTHROPIC_API_KEY`, `RAPIDAPI_KEY`, `ODDS_API_KEY`, `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_CHAT_ID`.

### Publicação
GitHub Pages: **Settings → Pages → Deploy from a branch → `main` → `/docs`**.

---

## Como correr

- **Manual:** GitHub → Actions → "Tennis Pre-Live Bot" → *Run workflow*.
- **Automático:** atualmente **desativado** (comentado no workflow) durante os
  testes. Para reativar 1x/dia, descomentar as linhas `schedule` e `cron`
  (05:00 UTC) em `.github/workflows/tennis-bot.yml`.
- **Teste local sem custo:** `python -m src.test_dry_run` (usa mock).

---

## Auditoria externa (rigor adotado)

O projeto passou por duas auditorias externas. Adotadas as recomendações de
**rigor e transparência**, mantendo a filosofia de "observação, não edge":

- **Índice de evidência, não probabilidade** — o motor apresenta um índice
  0-100 ("quanto do peso dos sinais aponta para A"), nunca uma probabilidade
  de vitória. A comparação com o mercado é **direcional** (concordam/discordam),
  sem inventar "pontos percentuais" de vantagem.
- **Selective pelo motor** — o Claude (pago) é chamado quando o motor deteta
  divergência relevante (nível ≥2), não pelos líderes dos sinais. Assim não se
  salta o jogo mais interessante (todos os sinais num lado, mercado no outro).
- **Confiança de amostra** — cada fator pesa conforme a robustez da amostra
  (8 jogos num piso pesam menos que 300).
- **Sem double counting** — fatores correlacionados (ranking/época/forma/
  serviço) agrupados em famílias com teto, para não contar a "qualidade geral"
  várias vezes.
- **Fadiga só de fonte recente fiável** (`api_recent`), nunca histórica.
- **Testes do motor** — suite determinística (`tests/test_motor.py`).
- "Favorito do mercado" (não "justo"); nunca afirmar "há valor de X%".

A recomendação de calcular **edge/probabilidade própria** foi **conscientemente
não adotada** — o bot reúne informação e compara com o mercado, não pretende
bater o mercado com um modelo próprio.

---

## O que falta fazer

### 🔴 Crítico (antes do próximo torneio)
- [ ] **Trocar `TRACKED_TOURNAMENT_IDS`** para o torneio novo (IDs ATP+WTA).
      Sem isto, o bot não apanha os jogos certos.
- [ ] **Uma execução manual de teste** para validar que o índice de evidência
      produz resultados sensatos nos jogos reais, antes de reativar o schedule.

### 🟡 Melhorias em curso / a validar
- [ ] Validar a **leitura de trader** no veredicto (padrões 1/2/4/5) em jogos
      reais — confirmar que aparece quando faz sentido e não é forçada.
- [ ] Confirmar que a **fadiga real** (jogos do torneio) aparece bem em
      jogadores de fase avançada.
- [ ] Afinar equilíbrio **qualidade vs custo** do output (discrepâncias curtas
      + veredicto rico) após ver mais relatórios.

### 🟢 Ideias futuras (não urgentes)
- [ ] **Automação de torneios por categoria** — em vez de IDs manuais, seguir
      automaticamente todos os ATP/WTA de nível **250, 500, 1000 e Grand Slam**
      (descartar Challengers/ITF). A implementar depois dos testes, com um
      "travão" de custo (limite de jogos/dia ou escolha de categorias ativas),
      já que mais torneios = mais custo Anthropic + RapidAPI.
- [ ] **Mais padrões de mercado** — a biblioteca de raciocínios está aberta a
      crescer (tie-break specialists, etc.).
- [ ] **Haiku preparado mas desligado** — modelo mais barato para a análise, a
      ligar só se o volume justificar e a qualidade aguentar (risco de perder o
      julgamento fino que é o diferencial do bot).
- [ ] **Plano RapidAPI custom** — negociar um plano intermédio (o grátis 50/dia
      é apertado, o Pro 5000/dia é exagero para 1 torneio).
- [ ] Terceira fonte de histórico WTA como reforço extra.

---

*Projeto pessoal. Análise informativa, não é recomendação de aposta.*
