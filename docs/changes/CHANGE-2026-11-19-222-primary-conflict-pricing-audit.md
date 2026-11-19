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

