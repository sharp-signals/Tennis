# Qualidade adversarial v2 — contrato de ensaio

**CHANGE-ID:** CHANGE-2026-11-02-175

**Estado:** replay ATP/WTA concluído; componentes aprovadas para construção da
equação observacional da forma recente

## Objetivo

Substituir a regra rejeitada «vitória/derrota surpresa pela diferença relativa
de ranking» por componentes factuais independentes. Nenhuma componente é ainda
um peso e nenhuma soma está autorizada.

## Componentes preservadas por jogador

1. `win_opponent_strength`: força absoluta dos adversários vencidos, expressa
   continuamente por `-log(ranking_adversário)`. Um ranking menor produz um
   valor maior; não existem patamares arbitrários.
2. `loss_opponent_strength`: força absoluta dos adversários nas derrotas. Uma
   derrota contra oposição muito forte é distinguida de uma derrota contra
   oposição fraca, mas não se transforma automaticamente em sinal positivo.
3. `game_margin_balance`: diferencial factual de games, com sinal do jogador,
   apenas para scores completos e normais.
4. `result_balance`: resultados competitivos normais nos 90 dias anteriores.
5. `same_surface_result_balance`: a mesma forma limitada ao piso do encontro.
6. `ranking_surprise_balance_v1`: preservada apenas como controlo rejeitado;
   o nome impede que volte a ser confundida com a qualidade final.

Vitórias e derrotas ficam separadas porque respondem a perguntas diferentes.
Não é legítimo usar uma derrota contra um top 10 para compensar
automaticamente a ausência de vitórias fortes.

## Regras do ensaio

- replay cronológico sem mercado;
- data do próprio jogo e datas futuras excluídas;
- ATP, WTA e Challenger separados;
- decaimento escolhido na validação e medido num holdout intocado;
- cada componente é avaliada isoladamente;
- combinação e coeficientes só numa fase posterior;
- a fonte tem de ter pelo menos 90% de rankings bilaterais e atualização nos
  últimos 14 dias; caso contrário o replay falha explicitamente.

## Estado operacional da fonte

Durante a primeira tentativa v2 em 02/11/2026, a TennisMyLife sofreu uma falha
DNS. O fallback ATP/Challenger não tinha rankings, pelo que os resultados dessa
tentativa foram descartados e os ficheiros temporários eliminados. Foi
adicionada uma barreira de saúde para impedir que isso volte a produzir um
relatório aparentemente válido.

Foi também criado um workflow diário exclusivamente para atualizar a última
cópia válida de ATP, WTA e Challenger, sem executar o bot, sem odds e sem APIs
pagas. Assim, o histórico pode continuar atualizado enquanto o workflow do bot
permanece desativado.

## Decisão após replay cronológico de 03/11/2026

O replay usou 26 627 alvos ATP e 24 436 WTA entre 2017 e 2026. A escolha do
decaimento foi feita apenas na validação; o holdout permaneceu intocado até à
avaliação final.

- `result_balance` é o núcleo factual e mantém uma janela uniforme de 90 dias
  nos dois circuitos.
- `game_margin_balance` é uma medida de competitividade, não um segundo voto
  completo. O decaimento selecionado foi 45 dias no ATP e 90 dias no WTA.
- `win_opponent_strength` confirmou sinal adicional com meia-vida de 60 dias
  nos dois circuitos.
- `loss_opponent_strength` confirmou que a qualidade das derrotas contém
  informação. Usa meia-vida de 45 dias no ATP e 90 dias no WTA, mas apenas para
  modular a penalização de uma derrota: perder com oposição forte nunca vale
  como vitória nem produz crédito positivo autónomo.
- `same_surface_result_balance` mostrou sinal, mas pertence à família
  `surface_conditions`. Na equação de forma recente será apenas contexto de
  transferência/relevância, sem novo voto independente.
- `ranking_surprise_balance_v1` ficou abaixo de 50% fora da amostra nos dois
  circuitos e continua formalmente rejeitada.

Os Challengers não participaram nesta decisão. Podem ser observados em replay
separado, mas não determinam a equação principal ATP/WTA.

Este contrato continua sem efeito em produção, PAPER, fair odds ou relatórios.

## Comparação das equações aninhadas

A comparação posterior confirmou, com intervalos de confiança inteiramente
positivos no ATP e no WTA, ganho incremental da competitividade, da qualidade
das vitórias e do contexto das derrotas sobre o saldo simples de resultados.
Isto autoriza a construção da equação seguinte, não a promoção do ajuste
estatístico atual. Em particular, o contexto das derrotas continua bloqueado
até existir uma barreira assimétrica que impeça uma derrota contra oposição
forte de gerar crédito positivo autónomo.

O primeiro candidato de barreira foi rejeitado: remover integralmente da
margem de games a parte associada ao resultado piorou significativamente o
holdout ATP e WTA, e a penalização isolada por derrotas contra jogadores pior
classificados recebeu coeficiente zero. Resultado e margem permanecem, por
isso, dentro de uma única equação calibrada — não como votos somados. O próximo
ensaio deverá limitar o alívio de derrotas fortes ao nível do próprio jogador,
sem permitir que a sua forma atravesse zero por essa via.

O ensaio dessa modulação limitada também não justificou promoção: o ATP
escolheu intensidade zero; o WTA escolheu 0,25 na validação, mas teve ganho
inconclusivo no holdout e coeficiente zero para a componente ajustada. A
qualidade das derrotas fica, portanto, como diagnóstico factual. A equação v1
da forma recente avança apenas com resultados, competitividade e qualidade das
vitórias.
