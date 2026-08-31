# 🎾 Sharp Signals — Tennis Pre-Live Bot

Sistema pré-live para jogos ATP/WTA. Recolhe dados factuais, calcula um índice
determinístico de evidência, confronta-o com o mercado e produz relatórios HTML
e um resumo Telegram.

> **Estado do produto:** o *pricing* de mercado, fair odds e expected edge são
> experimentais e estão em validação fora da amostra. O bot não executa apostas
> reais; apenas regista cenários elegíveis numa carteira **PAPER**. Uma decisão
> humana continua a ser necessária.

## Fluxo de produção

`python -m src.main` executa a seguinte cadeia:

1. Descobre torneios ATP/WTA a partir do feed RapidAPI *all upcoming* e aceita
   apenas os tiers configurados; a lista manual é fallback e há exceções
   explícitas (`FORCED_TOURNAMENT_IDS`).
2. Obtém fixtures por torneio, remove duplicados e mantém apenas jogos na
   janela `LOOKAHEAD_HOURS_MIN..LOOKAHEAD_HOURS_MAX` (por omissão, 0–36h).
3. Valida que o evento de odds é o mesmo fixture e ainda pré-live; usa a
   Moneyline `recent-odds` da RapidAPI, com evento, ordem e bookmaker
   verificáveis, para pricing/PAPER, e guarda a The Odds API como comparação
   independente opcional; constrói, em paralelo, um payload factual por jogo:
   ranking, H2H, superfície, forma, fadiga, serviço/resposta,
   cenários, mãos, estatísticas ricas e qualidade dos dados.
4. Calcula o índice Fenzobot em Python e avalia se há cobertura factual mínima
   para publicar uma decisão pré-live.
5. Aplica o *Market-Residual Pricing* experimental apenas sobre um par de odds
   recente, identificado e da mesma casa, sem margem; cria uma decisão `EDGE_POSITIVE`, `EDGE_NEGATIVE`,
   `EDGE_ZERO`, `PRICING_UNAVAILABLE` ou `REPORT_NULL`. Um edge positivo só
   entra em PAPER com cobertura ponderada mínima de 60%; abaixo disso fica
   visível como edge positivo sem PAPER.
6. Chama o Claude apenas quando a política seletiva o justifica; a análise
   textual não pode recalcular nem contrariar o motor determinístico.
7. Congela o snapshot pré-jogo, acrescenta entradas PAPER quando elegíveis,
   gera relatórios HTML V2, índice do site e resumo Telegram.

Uma execução com menos de 80% dos jogos elegíveis processados falha antes de
publicar. Entre 80% e 95% é publicada como degradada; a partir de 95% é normal.

## Componentes principais

| Ficheiro | Responsabilidade |
|---|---|
| `src/config.py` | Limites de quota, tiers, janelas, LLM, publicação e parâmetros experimentais de pricing. |
| `src/fetch_data.py` | APIs, fontes históricas, normalização, caches, orçamento RapidAPI e cálculo de métricas factuais. |
| `src/main.py` | Orquestra o pipeline, constrói o payload e aplica as guardas operacionais. |
| `src/report_html.py` | Motor `_calcular_divergencia` e relatório ativo V2. |
| `src/prelive_decision.py` | Contrato único de validade factual e estado operacional pré-live. |
| `src/pricing.py` | De-vig, residual em logit, fair odds, expected edge e gates de qualidade. |
| `src/calibration_store.py` | Snapshots pré-jogo imutáveis, liquidação e métricas de calibração. |
| `src/paper_trading.py` | Carteira PAPER append-only, liquidação e histórico em unidades. |
| `src/cache_store.py` | Cache JSON versionada, com TTL e escrita atómica. |
| `src/analyze.py` | Política seletiva, cache, fallback e validação do output LLM. |
| `src/run_metrics.py` | Telemetria de execução, custo LLM estimado e alertas. |

## Motor Fenzobot

O índice de evidência é 100% determinístico e **não é uma probabilidade**. Para
cada fator disponível, o motor pondera a direção, a força da diferença e a
confiança da amostra. Fatores correlacionados têm limites por família, para
reduzir dupla contagem.

O output inclui índice de 0–100 para ambos os jogadores, classificação, tipo
de sinal, fatores decisivos e o estado de todos os fatores — inclusive os
excluídos por falta de dados, empate ou amostra insuficiente. O relatório
expõe essa informação no Mapa de Forças.

### Pricing experimental

O baseline são as duas odds observadas, convertidas em probabilidades sem
margem. O índice apenas define a direção e a magnitude de um residual limitado
em logit:

`logit(P_estimado) = logit(P_mercado) + shift_max × força_assinada × qualidade`

A qualidade reduz o residual em caso de poucos fatores, massa efetiva baixa,
cobertura insuficiente, resolução de identidade incerta ou falha crítica de
dados. O resultado apresenta *Sharp estimate*, fair odd e expected edge para
os dois lados, sempre com a etiqueta **EXPERIMENTAL — EM VALIDAÇÃO**.

O estado PAPER depende da validade factual e de edge positivo no lado escolhido
pelo Fenzobot; `PRICING_MIN_EDGE_PCT` é diagnóstico de qualidade, não um limiar
que por si só crie uma entrada PAPER.

## Dados e resiliência

- **RapidAPI Matchstat:** descoberta, fixtures, ranking,
  jogos recentes, H2H, perfis e dados ricos. O contador é persistido durante a
  execução; limites por run/dia e retry de timeout, 429 e 503 são obrigatórios.
  A RapidAPI `all-upcoming` serve exclusivamente para descobrir fixtures e
  nunca alimenta pricing. O preço operacional é o par da mesma casa em
  `recent-odds`, depois de confirmar evento, jogadores, ordem e estado
  pré-live. A auditoria `CHANGE-2026-08-30-010` mostrou que o campo `addTime`
  pode ficar congelado mesmo quando as odds mudam; por isso é guardado como
  metadado, enquanto a frescura operacional é a hora da resposta observada
  nesta execução. A The Odds API é uma comparação independente opcional, não
  é misturada com o preço RapidAPI e a sua ausência não bloqueia pricing/PAPER.
  Sem um par RapidAPI válido, o relatório mantém a análise factual como
  `PRICING_UNAVAILABLE` e bloqueia edge/PAPER.
- **Históricos:** TennisMyLife, Sackmann e tennis-data.co.uk são usados como
  complemento/fallback consoante o tour e a métrica. Nunca se inventa um valor
  quando uma fonte falha.
- **Caches:** fixtures e torneios são persistidos; os dados por jogador usam
  `JsonCacheStore` com TTL próprio. Caches corrompidas degradam para ausência de
  dado, sem bloquear a run.
- **Qualidade:** falhas de resolução de nomes e dados essenciais em falta são
  gravados no payload e podem impedir pricing/decisão.

## Calibração e PAPER

Cada run publicável guarda a primeira fotografia pré-jogo em
`data/calibration_snapshots.json`: identidade, odds capturadas (fonte, UTC e
tipo de captura), métricas, pricing,
configuração/fingerprint e resultado da análise. Repetições do mesmo jogo não
substituem essa fotografia.

Depois da run, `scripts/update_calibration_outcomes.py` usa apenas as caches
locais de jogos concluídos para liquidar snapshots e a carteira PAPER. O
histórico de acerto e os intervalos de Wilson só são mostrados quando existe
amostra suficiente. Isto permite validação OOS sem reescrever informação
pré-jogo.

## Relatórios e distribuição

O HTML de produção é gerado por `build_report_html_v2`. Mostra estado do
relatório, qualidade/cobertura, mercado, fatores e pricing experimental; uma
falha de análise produz layout factual reduzido, não um sinal inventado.

Os ficheiros entram em `docs/relatorios/`; `docs/index.html` reúne a execução
do dia e GitHub Pages serve `https://sharp-signals.github.io/Tennis`.

O Telegram recebe um resumo por grupos de decisão, com links para cada
relatório. Mensagens longas são divididas abaixo do limite do Telegram.
Quando `REPORT_EMAIL_APP_PASSWORD` está configurado, o bot envia também um
e-mail por run para `fenzobot@gmail.com`, com o mesmo conjunto de links (sem
anexos). O e-mail tem rodapé Fenzo, logo servido pelo GitHub Pages e aviso de
uso analítico responsável.

## Execução e GitHub Actions

O workflow `.github/workflows/tennis-bot.yml` corre automaticamente às 05:30
e 17:30 UTC (06:30 e 18:30 em Portugal durante o horário de verão), além de
aceitar execução manual (`workflow_dispatch`). Em produção usa:

- Python 3.11 e `requirements.lock`;
- `LLM_MODE=anthropic`, `LLM_POLICY=selective` e `ALLOW_PAID_LLM=1`;
- limites RapidAPI de 2250 chamadas/run e 4500/dia;
- commit automático direto em `main` apenas para caches, telemetria, snapshots,
  PAPER, relatórios e dados SHADOW gerados; mudanças de código continuam por
  Pull Request.

Em caso de falha, o workflow preserva telemetria e alerta o Telegram; não deve
publicar relatórios parciais.

### Secrets necessários

`ANTHROPIC_API_KEY`, `RAPIDAPI_KEY`, `ODDS_API_KEY`, `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_CHAT_ID`, `TELEGRAPH_ACCESS_TOKEN` e `REPORT_EMAIL_APP_PASSWORD`.
O último é uma App Password da conta Gmail `fenzobot@gmail.com`, não a sua
palavra-passe normal.

## Desenvolvimento

- Teste sem chamada LLM paga: `python -m src.test_dry_run`
- Suite: `python -m pytest -q`
- Execução completa local: `python -m src.main` (requer as credenciais acima)

Antes de alterar `fetch_data.py`, `config.py`, `report_html.py`,
`prelive_decision.py`, `pricing.py` ou `calibration_store.py`, confirma os
contratos em `tests/`. Mudanças nesses módulos podem alterar simultaneamente a
decisão, o relatório, a carteira PAPER e a calibração histórica.

## Limites conhecidos

- O modelo de pricing está em validação e não deve ser apresentado como edge
  comprovado, previsão garantida ou recomendação de aposta.
- A cobertura e a qualidade variam por tour, jogador, fonte e momento da run.
- Valores em falta devem permanecer visíveis como indisponíveis; não devem ser
  preenchidos com estimativas silenciosas.

Projeto pessoal de análise informativa.
