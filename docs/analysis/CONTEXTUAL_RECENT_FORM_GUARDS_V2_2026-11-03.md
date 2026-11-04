# Forma recente contextual — teste das barreiras v2

**Data:** 03/11/2026  
**CHANGE-ID:** CHANGE-2026-11-02-175  
**Estado:** candidato rejeitado; produção inalterada

## Hipóteses testadas

1. Substituir a margem de games bruta pela parte residual que não fosse
   explicada pelo saldo de vitórias/derrotas. A relação foi estimada apenas no
   treino, com intercepto zero para manter simetria entre os jogadores.
2. Substituir o contexto livre das derrotas por uma penalização unilateral:
   apenas derrotas contra adversários pior classificados penalizam; derrotas
   contra adversários melhores valem zero e nunca crédito positivo.

## Resultado

| Circuito | Modelo livre | Modelo protegido | Diferença de log loss | IC 95% | Veredicto |
|---|---:|---:|---:|---:|---|
| ATP | 0,655743 | 0,659121 | -0,003378 | -0,005734 a -0,001023 | livre melhor |
| WTA | 0,639120 | 0,646483 | -0,007363 | -0,009665 a -0,005061 | livre melhor |

O modelo protegido também baixou ligeiramente o acerto: 60,99% para 60,70%
no ATP e 62,93% para 62,83% no WTA. A calibração ECE ficou semelhante, mas não
compensou a perda de log loss e Brier.

A relação treino entre saldo de resultados e margem foi aproximadamente 5,30
games no ATP e 5,54 no WTA. Remover integralmente esta relação foi excessivo:
a margem de uma vitória ou derrota contém intensidade competitiva útil, não
apenas repetição mecânica do resultado.

A penalização isolada por derrotas contra jogadores pior classificados recebeu
coeficiente zero nos dois circuitos depois das restantes componentes. Portanto
não há suporte para lhe atribuir já um voto autónomo.

## Decisão metodológica

- `recent_guarded_v4` fica rejeitado.
- Resultado e margem podem coexistir dentro de **uma única equação calibrada**.
  Não serão apresentados nem somados como dois votos independentes.
- A penalização por derrota fraca permanece como diagnóstico factual, não como
  peso confirmado.
- O modelo livre `recent_v3` continua apenas como benchmark: apesar de melhor
  estatisticamente, ainda permite que o contexto de uma derrota forte produza
  contribuição positiva e por isso não está autorizado para produção.
- A próxima alternativa deve operar ao nível de cada jogador: uma derrota
  forte poderá apenas aliviar, com limite, a componente negativa da sua forma;
  nunca elevar a forma acima de zero. A dimensão desse alívio será escolhida na
  validação e testada num holdout intacto.

Nenhum resultado alterou o bot, PAPER, fair odds, relatórios ou o agendamento
automático.
