# Forma recente contextual — auditoria das componentes v1

**Data:** 03/11/2026  
**CHANGE-ID:** CHANGE-2026-11-02-175  
**Estado:** observacional, sem efeito operacional

## Pergunta analisada

Que informação dos 90 dias anteriores ajuda a caracterizar a forma atual sem
usar o mercado, sem olhar para o futuro e sem transformar vários reflexos do
mesmo resultado em votos independentes?

## Universo e proteção contra leakage

| Circuito | Alvos | Treino | Validação | Holdout | Período |
|---|---:|---:|---:|---:|---|
| ATP | 26 627 | 16 002 | 5 410 | 5 215 | 02/01/2017–02/11/2026 |
| WTA | 24 436 | 14 666 | 4 931 | 4 839 | 02/01/2017–03/11/2026 |

Todos os jogos do próprio dia foram excluídos do histórico disponível para o
alvo. Retiradas e conclusões não competitivas não entraram. O decaimento foi
escolhido na validação e medido depois no holdout.

## Resultado fora da amostra

| Componente | ATP: regra escolhida | ATP acerto / cobertura | WTA: regra escolhida | WTA acerto / cobertura | Decisão |
|---|---|---:|---|---:|---|
| Resultados | uniforme 90d | 60,16% / 84,9% | uniforme 90d | 60,91% / 83,0% | núcleo |
| Margem de games | meia-vida 45d | 60,20% / 84,8% | meia-vida 90d | 62,28% / 83,0% | competitividade, sem voto duplicado |
| Força dos vencidos | meia-vida 60d | 56,30% / 74,9% | meia-vida 60d | 58,07% / 68,5% | qualidade das vitórias |
| Força nas derrotas | meia-vida 45d | 55,99% / 81,6% | meia-vida 90d | 60,27% / 81,8% | modula penalização das derrotas |
| Resultado no mesmo piso | meia-vida 30d | 57,41% / 69,6% | meia-vida 45d | 61,28% / 64,8% | transferir para superfície |
| “Surpresa” relativa de ranking | meia-vida 21d | 43,48% / 84,9% | meia-vida 21d | 47,44% / 82,9% | rejeitada |

O acerto acima é direcional e descritivo. Não é probabilidade calibrada, edge,
retorno financeiro nem peso final.

## Interpretação simples

Exemplo: dois jogadores chegam com 5 vitórias e 5 derrotas.

- O jogador A venceu adversários fortes e as suas derrotas foram equilibradas
  contra jogadores fortes.
- O jogador B venceu oposição fraca e perdeu de forma larga contra jogadores
  inferiores.

O 5–5 continua a ser o ponto de partida, mas A apresenta forma ajustada melhor.
Uma derrota de A contra um top 5 não é convertida numa “quase vitória”; apenas
é penalizada menos do que uma derrota de B contra o número 180.

## Contrato para a equação seguinte

1. O saldo de resultados é a base da família.
2. A margem de games mede quão competitivos foram esses resultados, com
   influência limitada para não repetir o mesmo jogo duas vezes.
3. A qualidade das vitórias acrescenta força apenas quando existem vitórias.
4. A qualidade das derrotas é assimétrica: uma má derrota pode penalizar mais;
   uma derrota forte apenas reduz a penalização, nunca cria crédito positivo.
5. A adequação ao piso será tratada pela família de superfície e poderá apenas
   ajustar a transferibilidade da forma geral.
6. Ausência de amostra reduz confiança; não produz valor neutro inventado.
7. ATP e WTA podem usar decaimentos diferentes. Challengers ficam
   observacionais e não decidem a equação principal.

## O que ainda não foi feito

Ainda não foi escolhida a combinação numérica entre estas componentes. O passo
seguinte é construir candidatos de equação, comparar calibração cronológica e
verificar se acrescentam valor ao núcleo simples sem sobreajuste. Até essa
prova, nada altera produção, PAPER, índice, fair odds ou relatórios.
