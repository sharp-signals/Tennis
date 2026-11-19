# CHANGE-2026-11-19-224 — Simetria e hierarquia do pricing contextual

## Problema

O runtime contextual v15 ainda permite dois comportamentos incompatíveis com a
metodologia acordada:

1. a orientação alfabética de jogador A/B pode deslocar a probabilidade neutra
   para fora de 50%; e
2. uma família secundária pode produzir mais impacto realizado do que as
   famílias principais, apesar da hierarquia declarada.

Além disso, um edge conservador pode continuar verde quando a cotação de
mercado fica fora do intervalo estatístico de 90% do modelo.

## Escopo

- tornar o pricing invariável à troca dos jogadores;
- aplicar a hierarquia às contribuições efetivamente usadas na fair odd;
- impedir que ausência de dados vote;
- colocar divergências de plausibilidade em revisão, sem alterar a fair odd;
- clarificar no relatório a diferença entre mercado indisponível e valor não
  confirmado;
- manter o modelo em `SHADOW_ONLY` e independente do mercado.

## Critérios de aceitação

- para ATP e WTA, `P(A,B) = 1 - P(B,A)` dentro de tolerância numérica;
- um confronto neutro produz 50%/50%, sem voto do nome ou da ordem alfabética;
- o bloco secundário não domina o bloco principal quando existe evidência
  principal;
- superfície permanece abaixo da autoridade principal e serviço/resposta é o
  modificador de menor autoridade;
- H2H sem jogos vale zero; H2H robusto pode reforçar a leitura, mas não substituir
  sozinho as duas famílias principais;
- uma cotação fora do intervalo de 90% nunca gera sinal verde nem sugestões de
  Moneyline/handicap; fica assinalada para revisão humana;
- o replay é cronológico, o mercado não entra na previsão e não existem ajustes
  por jogador ou encontro;
- testes direcionados e checkpoint CI completo ficam verdes.

## Validação

1. testes sintéticos de troca A/B, neutralidade, hierarquia e ausência;
2. reconstrução cronológica ATP/WTA e comparação no holdout;
3. replay dos jogos recentes que expuseram o problema;
4. suite completa antes de entrega.
