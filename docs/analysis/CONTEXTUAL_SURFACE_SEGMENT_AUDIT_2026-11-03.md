# Auditoria segmentada da família de superfície

**Data:** 03/11/2026
**Estado:** análise read-only

## Problema encontrado

A versão inicial atribuía um ajuste fixo ao jogador em transição recente de
piso. O segmento mostrou que esse voto era prejudicial:

| Circuito | Jogos em transição | Ganho de log loss da v1 | IC 95% | Decisão |
|---|---:|---:|---:|---|
| ATP | 552 | -0,029327 | -0,052005 a -0,006649 | rejeitar |
| WTA | 481 | -0,050909 | -0,076099 a -0,025720 | rejeitar |

Sem transição, a mesma equação melhorava ATP e WTA. Foi criada a v2 mantendo a
transição apenas como alerta. Face à v1, a v2 melhorou:

- ATP: log loss 0,653183 para 0,647717;
- WTA: 0,648360 para 0,640907.

## Contexto específico — limite do teste

A v3 retirou também o ajuste de indoor/outdoor ou velocidade, mantendo apenas
o registo no piso. Face à v2:

| Circuito | Ganho v2→v3 | IC 95% | Decisão |
|---|---:|---:|---|
| ATP | -0,000325 | -0,000729 a 0,000080 | inconclusivo |
| WTA | -0,000042 | -0,000202 a 0,000117 | inconclusivo |

Este resultado não demonstra que indoor/outdoor seja irrelevante. A v2 usava
o recinto apenas como um pequeno ajuste ao hard genérico, e não como um dos
quatro históricos de piso exigidos. Por isso a v3 é apenas um baseline de
comparação e não a família final.

## Segmentos principais da versão inicial

- Hard melhorava de forma confirmada em ATP e WTA.
- Relva melhorava no ATP e era inconclusiva no WTA.
- Terra era inconclusiva antes de retirar o voto de transição.
- Amostras pequenas eram corretamente encolhidas e não geravam certeza.
- A velocidade histórica estava essencialmente indisponível; não foi inferida
  a partir de ases ou serviço.

## Limite estatístico

A hipótese de remover o voto fixo de transição nasceu da leitura do primeiro
holdout. Os resultados v2/v3 são, por isso, evidência exploratória pós-auditoria
e não um novo holdout intocado. O que foi rejeitado foi a métrica binária e o
seu voto fixo, não o conceito de adaptação a uma mudança de piso. A promoção
exige uma nova equação e confirmação futura.
