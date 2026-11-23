# CHANGE-2026-11-21-232 — Fecho metodológico da temporada

**Nível:** 3 — pricing/metodologia central  
**Estado:** implementado e validado; pronto para revisão
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

## Fecho factual do ledger de 2026

Foram registados os três resultados finais confirmados manualmente pelo
utilizador, sem inventar vencedores nem incluir jogos não disputados nas
métricas primárias:

- Fritz–Rune: `WALKOVER`, resolvido mas excluído da avaliação primária;
- Muchova–Andreeva: `CANCELLED`, resolvido sem vencedor e excluído;
- Zverev–Alcaraz: vitória de Alcaraz por `6-2 7-6`, elegível para avaliação.

O settlement distingue agora `ready_resolved` de `ready_settled`: um cancelado
fecha a pendência do ledger, mas não entra em accuracy, Brier ou log loss.

## Auditoria adicional das fichas e da força estrutural

O replay cronológico reutilizou a mesma recolha local para evitar chamadas
externas e testou apenas componentes já disponíveis nas fichas dos jogadores.

- qualidade dos adversários recentes: mantida;
- nível dos torneios recentes: mantido;
- ranking representativo: mantido;
- granularidade adicional por ronda: rejeitada por ganho inconclusivo;
- prior especial top-2/top-3/top-5: rejeitado por ganho inconclusivo e risco de
  sobrestimar o favorito de elite;
- trajetória bruta do ranking ATP: removida da família estrutural, pois
  duplicava informação já representada pelo nível atual, ranking
  representativo, pontos e contexto de regresso.

### Promoção ATP suportada

Perfil promovido: `contextual_v8_atp_no_raw_trajectory`.

- holdout cronológico: 5.279 jogos;
- log loss anterior: `0,618301`;
- log loss candidato: `0,618131`;
- ganho: `0,000170`;
- IC95% do ganho: `[0,000024; 0,000315]`;
- estado: **SUPPORTED**;
- mercado usado na previsão: **não**.

A melhoria é pequena, mas sustentada fora da amostra. Não foi aplicado qualquer
bónus manual a favoritos ou jogadores de elite.

## Fair odd e incerteza

A probabilidade e os intervalos ATP foram recalibrados depois da promoção. O
release passa para `runtime_generation: 23`. O contrato WTA — combinação,
coeficientes e incerteza — é preservado exatamente, porque esta alteração foi
validada apenas para ATP.

O workflow guarda o contrato WTA anterior antes de reconstruir o baseline,
impedindo uma recalibração WTA silenciosa durante uma promoção exclusivamente
ATP.

## Verificação final

- 73 testes dirigidos aprovados;
- 67 testes Google Apps Script aprovados;
- 1.105 testes Python verificados: 1.102 passaram na suite conjunta e os três
  bloqueados pelo isolamento Windows passaram individualmente fora da sandbox;
- lint, scanner de segredos e `git diff --check` aprovados;
- fair odd continua independente do mercado;
- nenhuma entrada PAPER/REAL ou GREEN foi criada por esta alteração.
