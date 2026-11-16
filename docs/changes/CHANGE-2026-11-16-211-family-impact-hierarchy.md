# CHANGE-2026-11-16-211 — hierarquia do impacto realizado das famílias

## Implementation Brief

### Objetivo

Garantir que `Forma recente ajustada` e `Força estrutural` são as famílias
principais também no impacto efetivo de cada previsão, e não apenas nos
coeficientes globais do modelo.

### Problema confirmado

A combinação v8 limita os coeficientes das famílias secundárias, mas os logits
produzidos por cada família têm escalas diferentes. Assim, num jogo concreto,
uma família secundária pode produzir uma contribuição superior à das famílias
principais e o bloco secundário pode dominar a fair odd.

### Regra candidata

- O mercado permanece totalmente fora da previsão e da fair odd.
- Não existem ajustes manuais por jogador, ranking ou encontro.
- Em cada previsão, nenhuma família secundária pode exceder a contribuição
  absoluta média das duas famílias principais.
- Em cada previsão, a soma absoluta das famílias secundárias não pode exceder
  a soma absoluta das duas famílias principais.
- O sinal e a proporção relativa das famílias secundárias são preservados; só
  a magnitude excessiva é contraída.
- Se não existir contribuição principal utilizável, o bloco secundário não
  pode criar sozinho uma previsão operacional.

### Validação obrigatória antes de promoção

1. Replay cronológico emparelhado ATP/WTA contra a v8 congelada.
2. Verificação explícita da hierarquia em todas as linhas do holdout.
3. Comparação de log-loss, Brier, calibração e mudanças de lado.
4. Testes unitários de alinhamento, conflito, neutralidade e simetria.
5. Recalibração cronológica da incerteza caso a combinação seja promovida.

### Preservado

- SHADOW sem PAPER, GREEN ou execução automática.
- Snapshots e previsões históricas permanecem imutáveis e versionados.
- As cinco famílias e as respetivas equações internas não são alteradas.
- A fair odd continua independente do mercado.

## Resultado do replay cronológico

Foram reutilizados os caches validados com 26 691 jogos ATP e 24 498 WTA,
sem novas chamadas externas. A avaliação final permaneceu exclusivamente no
holdout cronológico:

- ATP: 5 279 jogos; a hierarquia contraiu o bloco secundário em 28,36% dos
  casos e terminou com zero violações. A diferença de log-loss contra a v8 foi
  `-0,000718`, com intervalo de 95% `[-0,001783; +0,000346]` — inconclusiva.
- WTA: 4 846 jogos; a hierarquia contraiu o bloco secundário em 17,95% dos
  casos e terminou com zero violações. A diferença de log-loss contra a v8 foi
  `+0,000188`, com intervalo de 95% `[-0,000916; +0,001292]` — inconclusiva.
- A calibração afim posterior foi estimada apenas no período de desenvolvimento
  e a calibração de incerteza foi reconstruída para a nova combinação.
- O mercado não foi usado em nenhuma previsão, ajuste ou decisão do replay.

## Decisão

A v9 é adotada em SHADOW como regra explícita de produto: as duas famílias
principais passam a governar também o impacto realizado por encontro. O replay
não demonstrou ganho preditivo, mas também não demonstrou degradação material;
a alteração resolve uma incoerência metodológica confirmada e permanece
versionada, experimental e reversível. Previsões v8 anteriores não são
reescritas.

