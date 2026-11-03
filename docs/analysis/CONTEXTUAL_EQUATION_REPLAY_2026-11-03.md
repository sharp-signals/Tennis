# Replay das equações contextuais — 3 de novembro de 2026

**Estado:** comparação cronológica read-only; nenhuma promoção autorizada  
**Fonte:** TennisMyLife, atualizada até 2 de novembro de 2026  
**Mercado/RapidAPI:** não utilizados

## Desenho

O perfil legado e o perfil contextual foram treinados no mesmo período e
comparados exatamente nos mesmos jogos do holdout. ATP, WTA e Challenger foram
separados. O holdout não foi usado para escolher parâmetros.

| Universo | Treino | Validação | Holdout |
|---|---:|---:|---:|
| ATP | 16 002 | 5 410 | 5 214 |
| WTA | 14 666 | 4 931 | 4 834 |
| Challenger | 28 375 | 9 399 | 9 297 |

## Força estrutural

| Universo | Pares | Log loss legado | Log loss contextual | Diferença contextual | Decisão |
|---|---:|---:|---:|---:|---|
| ATP | 5 143 | 0,626620 | 0,636086 | -0,009466 | rejeitar v1 |
| WTA | 4 815 | 0,622267 | 0,629193 | -0,006926 | rejeitar v1 |
| Challenger | 9 236 | 0,649707 | 0,655285 | -0,005578 | rejeitar v1 |

A curva contextual continua muito melhor do que um intercepto sem informação,
mas perde para o ranking logarítmico contínuo nos três universos. A principal
hipótese é que a zona neutra rígida elimina informação útil em diferenças
moderadas. A próxima versão deve manter uma curva contínua atenuada e usar
trajetória/inatividade como modificadores da representatividade, não como soma
adicional nem substituição do ranking atual.

## Superfície e condições

| Universo | Pares | Log loss legado | Log loss contextual | Diferença contextual | Decisão |
|---|---:|---:|---:|---:|---|
| ATP | 4 883 | 0,660109 | 0,653209 | +0,006900 | candidato, não promover ainda |
| WTA | 4 559 | 0,650585 | 0,648341 | +0,002244 | candidato, não promover ainda |
| Challenger | 8 641 | 0,661944 | 0,666847 | -0,004903 | rejeitar v1 |

O shrinkage das amostras e a regra de não somar piso/indoor/velocidade melhoram
probabilidade e calibração em ATP/WTA. A accuracy direcional desceu ligeiramente,
por isso a curva ainda precisa de análise por superfície, amostra e condição.
Challenger exige parâmetros próprios e não pode herdar a equação ATP.

## Decisões

1. Nenhuma equação é promovida a produção.
2. O modelo SHADOW congelado não é substituído.
3. Força estrutural v1 fica rejeitada como parametrização, mantendo-se o
   contrato metodológico.
4. Superfície v1 continua candidata apenas para ATP/WTA.
5. Hold, break, resposta e recuperação por condição só entram depois de existir
   ownership que impeça dupla contagem com serviço/resposta.
6. O bot automático permanece parado.

## Próxima iteração

- testar uma curva estrutural contínua, sem degrau morto;
- condicionar a representatividade do ranking por trajetória e inatividade;
- auditar a superfície por hard/clay/grass e indoor/outdoor;
- construir versão Challenger separada;
- só então voltar a combinar famílias e calibrar fair probability/fair odd.
