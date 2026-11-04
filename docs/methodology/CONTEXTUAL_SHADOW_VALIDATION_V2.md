# Contrato de validação prospetiva contextual v2

## Objetivo

Avaliar a probabilidade e a fair odd congeladas antes do jogo, sem permitir que
o preço de mercado entre no modelo. O mercado é observado apenas depois de a
previsão estar persistida e serve exclusivamente como benchmark.

## Três ledgers separados

1. previsão imutável: `data/contextual_shadow_observations-v2.jsonl`;
2. primeira cotação bilateral válida:
   `data/contextual_shadow_market-v2.jsonl`;
3. resultado confirmado: `data/contextual_shadow_outcomes-v2.jsonl`.

Nenhum destes ficheiros cria PAPER, GREEN, relatório, notificação ou decisão.

## Amostra pré-declarada

- 200 resultados válidos no total;
- 75 por circuito antes de concluir sobre ATP ou WTA;
- 150 jogos com resultado e benchmark de mercado pareado;
- 30 por segmento ou bin antes de o apresentar como evidência própria.

O mínimo global de 200 limita a margem de erro de uma proporção próxima de
50% a aproximadamente sete pontos percentuais a 95%. Os mínimos menores por
segmento destinam-se apenas a impedir conclusões sobre células residuais; não
substituem a validação global.

## Métricas

- Brier Score e log loss contra o baseline neutro de 50%, usando a diferença
  pareada e o respetivo intervalo de confiança aproximado a 95%;
- ECE em dez bins, com limite descritivo pré-declarado de 0,07;
- calibração dos intervalos por taxas empíricas, nunca tratando um resultado
  binário como um valor contínuo dentro do intervalo;
- comparação pareada entre modelo e probabilidade de-vig do mercado, também
  com intervalo de confiança aproximado a 95%;
- retorno hipotético de uma unidade por faixas de diferença probabilística,
  sempre marcado como SHADOW e não como estratégia aprovada.

## Benchmark de mercado

- IDs dos dois jogadores, circuito e hora do jogo têm de coincidir;
- a previsão tem de existir antes da captura;
- a captura tem de ocorrer antes do início;
- as duas odds vêm da mesma casa e passam o gate de integridade já auditado;
- a primeira cotação válida é preservada; novas cotações não a substituem;
- The Odds API é tentada primeiro e RapidAPI `recent-odds` é fallback;
- ausência de mercado permanece `N/D` e não invalida a previsão.

## Governação

Os gates produzem `INSUFFICIENT_SAMPLE`, `REVIEW_REQUIRED_PASS` ou
`REVIEW_REQUIRED_FAIL`. Mesmo um passe nunca promove automaticamente o modelo.
Qualquer utilização operacional exige auditoria humana, nova alteração
versionada e decisão explícita.
