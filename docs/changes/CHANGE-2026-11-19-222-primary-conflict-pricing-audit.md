# CHANGE-2026-11-19-222 — auditoria do pricing em conflito primário

## Nível e objetivo

Alteração **Level 3**, inicialmente read-only. Auditar o caso em que `Forma
recente ajustada` e `Força estrutural` apontam para lados opostos, enquanto as
três famílias secundárias apontam para o mesmo jogador. O caso motivador é
Medvedev–Tiafoe, mas nenhuma regra pode depender dos jogadores ou do mercado.

## Causa técnica a testar

Na regra v14, o conflito entre as duas famílias principais ativa um limite
rígido: o bloco secundário total não pode exceder o orçamento absoluto das
principais. Quando esse limite satura, a magnitude adicional de superfície,
H2H e serviço/resposta deixa de alterar a previsão. É necessário verificar no
replay cronológico se essa compressão é excessiva neste perfil.

## Hipóteses

- Baseline: política v14 congelada.
- Candidatas: preservar a concordância das três secundárias em conflito
  primário, com limites individuais progressivos, ou sem limite adicional.
- A orientação e a intensidade das famílias continuam aprendidas apenas em
  dados anteriores ao encontro.
- O mercado não entra no modelo, na seleção nem na fair odd.

## Critério de decisão

Só pode ser proposta uma nova combinação se for selecionada no período de
validação e não degradar materialmente log-loss, Brier e calibração no holdout.
O segmento de conflito primário com três secundárias alinhadas é reportado em
separado. Um único jogo não autoriza promoção.

## Preservado

- SHADOW sem PAPER, GREEN ou execução real.
- Observações e previsões históricas não são reescritas.
- Equações internas das cinco famílias não são alteradas nesta auditoria.
- Fair odd independente do mercado.

## Resultado da auditoria

- ATP: a política que preserva as três famílias secundárias quando estão todas
  disponíveis e concordam no conflito entre as duas principais foi escolhida
  na validação cronológica. No holdout, passou de `0,619816` para `0,619745` em
  log-loss e de `0,215805` para `0,215754` em Brier. No segmento específico,
  a accuracy passou de `59,35%` para `60,57%`.
- A melhoria global emparelhada é pequena e estatisticamente inconclusiva; por
  isso a mudança fica estritamente limitada ao padrão auditado, sem alterar as
  equações internas das famílias.
- WTA: o baseline v14 continuou a ser escolhido na validação. A política WTA
  fica, portanto, inalterada.
- Medvedev–Tiafoe, usando apenas as cinco probabilidades familiares já
  congeladas, passa de `50,55%` / fair odd `1,98` para `59,75%` / fair odd
  `1,67`. O mercado não participa neste cálculo.

## Correção factual associada

O H2H no piso atual passa a exigir o contexto exato. Um H2H em hard outdoor
continua a contar no H2H global, mas deixa de ser contado e apresentado como
H2H no piso atual quando o encontro é hard indoor (e vice-versa).

