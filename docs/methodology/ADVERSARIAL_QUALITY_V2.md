# Qualidade adversarial v2 — contrato de ensaio

**CHANGE-ID:** CHANGE-2026-11-02-175

**Estado:** implementação observacional; replay real pendente de fonte rica

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
