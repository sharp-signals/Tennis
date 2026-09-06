# GREEN_STRONG_V1 — validação prospetiva

`GREEN_STRONG_V1` é uma coorte SHADOW de validação, não uma estratégia provada nem uma autorização de aposta. O contrato `CHANGE-2026-09-06-026` aplica-se apenas à primeira fotografia ex-ante imutável criada depois da sua entrada em produção.

## Critério congelado

Uma fotografia é elegível apenas quando, simultaneamente: estado `EDGE_POSITIVE`; `paper_eligible=true`; divergência determinística `tipo=direcao`, nível 3; lado Fenzobot coerente com a divergência; pricing disponível; probabilidades válidas dos dois lados; e ausência de conflito de integridade.

Dados ausentes ou contraditórios tornam o registo inelegível com `reason_code`. Flags/texto de LLM, cores do HTML, resultado e closing market são proibidos na classificação. Snapshots antigos sem tag nunca são retroclassificados para a coorte prospetiva.

## Proveniência, métricas e segmentos

A tag fica em `validation.cohorts.GREEN_STRONG_V1` e guarda contrato, instante, lado/jogador, razões, versões disponíveis, `GITHUB_SHA` e `GITHUB_RUN_ID`; desconhecidos são `UNAVAILABLE`.

`data/validation/green-strong-v1.json` é uma vista reconstruível a partir dos snapshots, Market-Time Ledger e liquidações. Mede N, win rate, probabilidades médias, Brier, Log Loss, deltas emparelhados e movimento até à última observação comparável pré-início. Segmentos fixos: ATP/WTA, BO3/BO5 quando comprovado, favorito/underdog, modelo/fingerprint e revisão de código. Todos mostram N; não há ordenação por performance.

## GUERRA_SELECTION_V1

É uma seleção humana opcional, separada e restrita a candidatos ligados exatamente pelo snapshot key antes do início. Não altera o PAPER técnico.

- Moneyline 22Bet `>= 1.75` pode seguir para consideração manual.
- Abaixo de `1.75`, apenas revisão manual de handicap; handicap nunca é automático.
- Não existe teto `1.90`.
- Cobertura equivalente, preço compensatório e decisão final continuam humanos.
- A proteção advisory de 20% do underdog permanece informativa, não é um gate.

A Sheet mantém as 15 colunas existentes. O instalador de menu acrescenta cinco colunas opcionais de forma idempotente. Da Sheet, o repositório recebe apenas agregados: nunca nomes, snapshot keys, notas ou linhas individuais. A vista técnica da coorte publica os keys gerados pelo Fenzobot estritamente para permitir a validação exata.

## Limites

Não há backfill, chamadas API, LLM, tuning, alteração de pesos/pricing/thresholds ou promoção para REAL. Uma falha desta vista não bloqueia pipeline, decisão nem PAPER.
