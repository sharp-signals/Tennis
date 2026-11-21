# CHANGE-2026-11-21-230 — impacto preditivo zero para exibições

## Decisão

Laver Cup, exibições, World Tennis League e Ultimate Tennis Showdown podem
permanecer visíveis como factos históricos, mas têm impacto zero em todas as
famílias usadas para construir a probabilidade e a fair odd.

## Causa corrigida

`CHANGE-2026-11-20-229` retirou estes encontros do H2H competitivo, mas o
histórico dos jogadores continuava a alimentá-los na forma recente, superfície,
serviço/resposta e trajetória. Além disso, a política não fazia parte do
fingerprint do release; uma observação já congelada podia por isso ser
reutilizada depois da mudança de código.

## Comportamento

- eventos não competitivos deixam de entrar em qualquer feature preditiva;
- estes eventos não são targets do replay cronológico nem treino/calibração;
- no H2H continuam auditáveis no total factual, marcados como excluídos;
- a política `zero-predictive-impact-v1` passa a fazer parte do fingerprint;
- o runtime avança para a geração 22 e preserva a geração 21 como histórica;
- uma partida futura já observada pode receber uma nova observação versionada,
  sem reescrever nem apagar a previsão anterior.

## Preservação

- o mercado continua fora da construção da fair odd;
- observações e resultados históricos permanecem imutáveis;
- não são alterados pesos, thresholds ou hierarquia das famílias;
- os encontros competitivos mantêm exatamente o tratamento anterior.

## Validação exigida

- equivalência total das features com e sem uma Laver Cup adicional;
- replay cronológico sem target nem histórico preditivo de exibições;
- H2H factual distinto do H2H competitivo;
- fingerprint novo com geração anterior aceite como histórica;
- replay/modelos recalculados e CI completa.
