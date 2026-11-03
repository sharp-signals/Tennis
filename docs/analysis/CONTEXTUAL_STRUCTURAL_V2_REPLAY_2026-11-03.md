# Replay da força estrutural v2 — 3 de novembro de 2026

**Estado:** comparação cronológica read-only; v2 não promovida  
**Âmbito principal:** ATP e WTA  
**Challenger:** fora da decisão desta iteração  
**Fonte:** TennisMyLife, atualizada até 2 de novembro de 2026  
**Mercado/RapidAPI:** não utilizados

## O que mudou

A v2 removeu a zona neutra rígida da força estrutural. Diferenças moderadas de
ranking passaram a produzir um sinal pequeno e contínuo, enquanto diferenças
como top 10 contra número 200 continuam a produzir um sinal material. Ranking
atual permanece a âncora; trajetória, recuperação de ranking e inatividade
alteram sobretudo a confiança do sinal e não criam votos independentes.

## Resultado cronológico

Os perfis foram treinados no mesmo período e avaliados exatamente nos mesmos
jogos do holdout.

| Circuito | Pares | Log loss legado | Log loss v1 | Log loss v2 | Ganho v2 vs legado | Decisão |
|---|---:|---:|---:|---:|---:|---|
| ATP | 5 143 | 0,626620 | 0,636086 | 0,629267 | -0,002647 | não promover |
| WTA | 4 815 | 0,622267 | 0,629193 | 0,625612 | -0,003345 | não promover |

A v2 recuperou aproximadamente 72% do défice da v1 no ATP e 52% no WTA, mas
ainda não supera a referência histórica. A accuracy também ficou ligeiramente
abaixo: ATP 64,55% contra 64,61%; WTA 64,11% contra 64,20%.

## Superfície e condições, sem alteração de fórmula

| Circuito | Pares | Log loss legado | Log loss contextual | Ganho | Decisão |
|---|---:|---:|---:|---:|---|
| ATP | 4 883 | 0,660109 | 0,653209 | +0,006900 | manter candidata SHADOW |
| WTA | 4 559 | 0,650585 | 0,648341 | +0,002244 | manter candidata SHADOW |

Esta repetição confirma que a melhoria da família de superfície não dependia da
força estrutural v1. Ainda assim, não existe autorização para produção antes da
auditoria por piso, condição e dimensão de amostra.

## Decisão metodológica

1. A força estrutural v2 fica registada como experiência rejeitada para
   promoção, não como código de produção.
2. A hierarquia metodológica mantém-se: nível atual é contexto primário, mas a
   curva ainda precisa de melhor calibração.
3. Superfície v1 permanece candidata apenas em ATP/WTA.
4. Challengers não condicionam esta decisão e continuarão numa linha
   observacional separada.
5. Não há alterações no relatório, índice, fair odd, edge, PAPER ou GREEN.
6. O bot automático permanece parado.

## Próximo passo recomendado

Em vez de voltar a ajustar números manualmente, decompor a força estrutural em
segmentos auditáveis — diferenças moderadas, top 10/top 20 contra ranking baixo,
regresso após inatividade e trajetória recente — e localizar onde a v2 perde
log loss. Só depois deve existir uma v3.
