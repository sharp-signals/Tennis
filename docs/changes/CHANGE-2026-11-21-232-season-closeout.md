# CHANGE-2026-11-21-232 — Fecho metodológico da temporada

**Nível:** 3 — pricing/metodologia central  
**Estado:** em implementação e validação  
**Modo:** SHADOW_ONLY

## Objetivo

Fechar a temporada corrigindo a leitura factual dos relatórios sensíveis e
testando, sem efeito operacional, se o H2H específico da superfície melhora a
calibração cronológica do modelo.

## Problema observado

- O relatório resume no singular uma sensibilidade que pode envolver várias
  famílias.
- Uma divergência de preço ainda bloqueada surge no cabeçalho como “Valor
  Moneyline”, sugerindo uma seleção que o próprio contrato recusou.
- O H2H no piso atual é recolhido, mas o relatório mostra apenas a amostra e o
  modelo ativo usa apenas o H2H global.

## Hipótese metodológica

O H2H específico da superfície pode acrescentar informação ao H2H global,
desde que a comparação cronológica ATP e WTA não degrade o holdout. A alteração
não será promovida com base num único jogo.

## Alteração autorizada

1. Contar e nomear todas as famílias cuja retirada muda o favorito.
2. Tratar sinais sensíveis como divergência de mercado por auditar, sem
   Moneyline ou handicap sugeridos.
3. Mostrar o resultado agregado do H2H no piso atual.
4. Executar uma auditoria cronológica read-only do perfil H2H global versus o
   perfil global + superfície antes de qualquer promoção.

## Preservado deliberadamente

- A fair odd continua independente do mercado.
- Não são reescritas previsões históricas nem snapshots ex ante.
- Não são criadas entradas PAPER/REAL.
- A divergência de preço no underdog permanece visível, mas não é convertida em
  aposta enquanto a direção for sensível.

## Critério de promoção do H2H contextual

Só promover se a seleção ocorrer na validação e o holdout cronológico mostrar
ganho não negativo, sem degradação material em ATP ou WTA. Caso contrário,
manter o perfil global ativo e registar o resultado como experiência rejeitada.

## Resultado da auditoria cronológica

Replay local congelado em 19/11/2026, sem chamadas externas e sem mercado na
previsão:

- **ATP:** 2.357 jogos emparelhados. O perfil global + piso melhora o log loss
  em apenas `0,000423`, com IC95% `[-0,000936; 0,001781]`. Resultado
  **INCONCLUSIVO**.
- **WTA:** 2.066 jogos emparelhados. O perfil global + piso piora o log loss em
  `0,000835`, com IC95% totalmente negativo `[-0,001424; -0,000245]`.
  Resultado **REJEITADO**.

**Decisão:** não promover o H2H específico da superfície para o pricing. O
H2H global continua ativo; o resultado no piso atual passa a ser mostrado como
contexto informativo, sem peso separado na fair odd. Esta decisão evita ajustar
o modelo retrospetivamente ao caso Zverev–Alcaraz.

Resultado estruturado: `data/validation/contextual-h2h-surface-context-audit-2026-11-21.json`.
