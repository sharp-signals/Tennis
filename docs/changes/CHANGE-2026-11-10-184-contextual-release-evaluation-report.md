# CHANGE-2026-11-10-184 — avaliação e relatório privado da release contextual

## Objetivo

Completar a cadeia prospetiva de `FENZOBOT_CONTEXTUAL_2026_11` sem ligar a
release ao bot operacional. A previsão continua a ser criada sem mercado e é
imutável. Resultados e preços são registos separados, ligados posteriormente
pela identidade canónica do jogo.

## Cadeia executada

1. Liquidar observações anteriores através de resultados confirmados.
2. Criar novas observações da release global.
3. Congelar a primeira cotação válida observada depois da previsão e antes do
   início do encontro.
4. Atualizar métricas descritivas de calibração e comparação com o mercado.
5. Construir relatórios HTML privados e carregá-los apenas como artefacto da
   execução.
6. Publicar somente os ledgers e resumos gerados permitidos pelo contrato do
   writer.

## Garantias

- O mercado nunca entra na probabilidade nem na fair odd.
- O resultado nunca reescreve a previsão original.
- A primeira cotação válida fica congelada; cotações posteriores não substituem
  o benchmark.
- O relatório é `SHADOW_PREVIEW_ONLY`: não cria PAPER, GREEN, Telegram, email
  ou relatório operacional público.
- Os mínimos de 200 jogos e restantes gates destinam-se à avaliação de eventual
  promoção futura; não impedem criar relatórios privados desde já.
- Não existe promoção automática. Qualquer decisão futura exige revisão humana.
- A implementação V2 permanece funcional por defeito; a release global usa
  wrappers e contratos próprios, evitando duplicação da lógica matemática.

## Ficheiros gerados da release

- `data/contextual_shadow_observations-fenzobot-contextual-2026-11.jsonl`
- `data/contextual_shadow_handicap_evidence-fenzobot-contextual-2026-11.jsonl`
- `data/contextual_shadow_market-fenzobot-contextual-2026-11.jsonl`
- `data/contextual_shadow_outcomes-fenzobot-contextual-2026-11.jsonl`
- `data/validation/fenzobot-contextual-2026-11-evaluation-latest.json`
- `data/validation/fenzobot-contextual-2026-11-market-latest.json`

## Fora de âmbito

Esta alteração não reativa o agendamento automático, não substitui o relatório
operacional antigo e não autoriza registos de apostas. O objetivo é observar,
liquidar, medir e apresentar a nova metodologia com rastreabilidade antes de
qualquer ativação.
