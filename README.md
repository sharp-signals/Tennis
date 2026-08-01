# 🎾 Tennis Pre-Live Bot

Bot de análise **pré-live** de ténis (ATP/WTA). Para cada jogo de um torneio
seguido, recolhe dados de várias fontes, gera um relatório visual com uma
**leitura de mercado** (discrepâncias e pontos a observar), publica-o online
e envia um resumo para o Telegram.

> **Importante:** o bot **não recomenda apostas**. Sinaliza divergências entre
> os dados e o mercado e sugere **mercados a observar** — a decisão é sempre
> humana.

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
4. **Analisar** com o Claude (Sonnet) — devolve só a *análise* (pontos-chave,
   discrepâncias, veredicto), não o relatório todo.
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
- **Jogos recentes** (`past-matches`): para a **fadiga real** (inclui os jogos
  do torneio em curso).
- Base: `https://tennis-api-atp-wta-itf.p.rapidapi.com/tennis/v2/`
- Consumo medido: **~18-26 chamadas por execução** (varia com dados ricos e
  fadiga). Registado em `data/rapidapi_usage_log.json`.

### Histórico de jogos (grátis)
- **ATP:** TennisMyLife (fiável, nunca falhou).
- **WTA:** tennis-data.co.uk multi-ano (**10 anos**, ~22 mil jogos). Fiável.
  O Sackmann (`tennis_wta`) é tentado primeiro mas anda instável (404); há
  **cópia local** em `data/history_cache/` que se auto-atualiza quando a fonte
  está disponível.
- Profundidade: **10 anos** (`HISTORY_YEARS_TO_LOAD`).

### Odds (grátis)
- The Odds API — devolve `{nome_jogador: preço}`. Probabilidade sem margem
  calculada no cabeçalho.

### Análise (Anthropic)
- Modelo: **`claude-sonnet-5`**. Escolha deliberada de manter o Sonnet (não
  Haiku) para preservar a qualidade do julgamento de mercado.

---

## O relatório

Estrutura, de cima para baixo:

1. **Cabeçalho** — jogadores, odds, probabilidade sem margem, confiança da
   leitura, e **alerta de topo** 🔴 quando há discrepância forte.
2. **Gráficos** — Serviço/Resposta, Forma recente, Qualidade do adversário.
3. **Secções de dados** (montadas em Python, números sempre certos):
   H2H, forma/época, ranking, piso, fadiga, desistências, cenários de jogo,
   estilo, domínio vs adversários, meteorologia, mercado.
4. **Pontos-chave** — os sinais mais importantes (análise do Claude).
5. **Discrepâncias** — divergências dados vs mercado, com selos
   🔴 forte / 🟡 moderado / ⚪ fraco.
6. **Veredicto** — a **leitura de trader**: onde está (ou não) o valor,
   pré-live ou ao vivo.

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

Estado atual: `max_tokens=5500`, output médio ~4000 tokens/jogo (análise rica).
Projeção Anthropic com 1x/dia: **~$12-19/mês** conforme o volume de jogos.

---

## Configuração

Principais em `src/config.py`:

| Variável | Valor atual | Nota |
|---|---|---|
| `TRACKED_TOURNAMENT_IDS` | Washington (21344 ATP, 16738 WTA) | **A trocar por torneio** |
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

## O que falta fazer

### 🔴 Crítico (antes do próximo torneio)
- [ ] **Trocar `TRACKED_TOURNAMENT_IDS`** do Washington para o torneio novo
      (precisa dos IDs ATP+WTA). Sem isto, o bot não apanha os jogos certos.
- [ ] **Reativar o schedule** (descomentar `schedule`/`cron` no workflow)
      quando os testes terminarem.
- [ ] **Auditoria externa** do projeto (revisão por terceiro).

### 🟡 Melhorias em curso / a validar
- [ ] Validar a **leitura de trader** no veredicto (padrões 1/2/4/5) em jogos
      reais — confirmar que aparece quando faz sentido e não é forçada.
- [ ] Confirmar que a **fadiga real** (jogos do torneio) aparece bem em
      jogadores de fase avançada.
- [ ] Afinar equilíbrio **qualidade vs custo** do output (discrepâncias curtas
      + veredicto rico) após ver mais relatórios.

### 🟢 Ideias futuras (não urgentes)
- [ ] **Mais padrões de mercado** — a biblioteca de raciocínios está aberta a
      crescer (tie-break specialists, etc.).
- [ ] **Haiku preparado mas desligado** — opção de modelo mais barato para a
      análise, a ligar só se o volume (vários torneios) justificar e a
      qualidade aguentar.
- [ ] **Alargar a vários torneios** em simultâneo (decisão dependente de custo;
      com Pro a quota aguenta, o custo Anthropic escala com os jogos).
- [ ] Reduzir mais o consumo Anthropic (payload ainda mais enxuto, etc.).
- [ ] Terceira fonte de histórico WTA como reforço extra.

---

*Projeto pessoal. Análise informativa, não é recomendação de aposta.*
