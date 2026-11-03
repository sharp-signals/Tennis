# Forma recente — modulação limitada das derrotas v3

**Data:** 03/11/2026  
**Estado:** qualidade das derrotas não promovida

## Regra ensaiada

Para cada jogador, uma derrota contra oposição pior classificada aumentava a
penalização. Uma derrota contra oposição superior só podia aliviar uma forma já
negativa e nunca atravessar zero. Foram definidos antes do replay cinco níveis
de intensidade: 0, 0,10, 0,25, 0,50 e 1,00.

A intensidade foi escolhida na validação; só depois se consultou o holdout.

## ATP

- A validação escolheu intensidade **0**.
- O modelo resultante é exatamente a versão sem qualidade das derrotas.
- Holdout: log loss 0,659009, Brier 0,233391 e acerto 60,72%.

## WTA

- A validação escolheu 0,25 por uma diferença muito pequena.
- No holdout, o ganho de log loss foi -0,000003, com IC 95% de
  -0,000523 a 0,000517: **inconclusivo**.
- O coeficiente da componente ajustada foi zero.
- O acerto subiu de 62,70% para 62,85%, mas o log loss não melhorou e o ECE
  piorou de 0,011268 para 0,013662.

## Decisão

Não existe suporte para incluir a qualidade das derrotas na equação v1. Fica
registada como diagnóstico factual para futura reavaliação com mais dados ou
uma formulação diferente. A família aprovada avança com resultados,
competitividade e qualidade das vitórias.
