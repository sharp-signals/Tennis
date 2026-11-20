# CHANGE-2026-11-20-229 — integridade do H2H e do movimento de mercado

## Decisão

Laver Cup, exibições, World Tennis League e Ultimate Tennis Showdown podem
permanecer visíveis como confrontos factuais, mas têm peso zero no H2H usado
para construir a probabilidade e a fair odd.

Uma variação de mercado só pode ser apresentada quando a cotação anterior e a
atual pertencem à mesma casa e à mesma fonte. Duas casas diferentes são duas
fotografias de mercado, não um movimento temporal comparável.

## Problemas corrigidos

1. O replay cronológico incluía Laver Cup no H2H, apesar de a recolha factual
   do provider já possuir uma exclusão parcial para competições não
   competitivas.
2. O relatório comparava a cotação atual com a fotografia imediatamente
   anterior mesmo quando as casas eram diferentes.
3. A decomposição visual da forma recente mostrava o coeficiente estatístico
   ajustado, mas não o piso e o limite dos modificadores efetivamente usados
   pelo pricing desde `CHANGE-2026-11-19-225`.

## Comportamento

- o total factual de H2H continua auditável;
- apenas os confrontos competitivos entram na curva de fiabilidade do H2H;
- confrontos excluídos são marcados no relatório como `não entra no cálculo`;
- o placar principal do H2H mostra apenas o registo competitivo usado no
  preço;
- sem fotografia anterior da mesma casa/fonte, o relatório não apresenta
  movimento;
- a forma recente passa a mostrar o contributo efetivo depois da governação,
  preservando em paralelo o contributo estatístico ajustado para auditoria.

## Preservação

- previsões já congeladas não são reescritas;
- o mercado continua proibido na construção da fair odd;
- não são introduzidos novos pesos nem thresholds de pricing;
- a governação da forma recente e as probabilidades permanecem inalteradas;
- dados em falta continuam sem votar.

## Validação exigida

- regressão do replay cronológico com Laver Cup antes de um jogo competitivo;
- regressão do target prospetivo com total factual e amostra elegível distintos;
- regressão de relatório com casas diferentes sem falso movimento;
- regressão do trace efetivo da forma recente;
- CI completa por tocar runtime, replay e reporting decisório.
