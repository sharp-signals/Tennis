# Superfície e condições v0 — contrato factual

**CHANGE-ID:** CHANGE-2026-11-02-175

**Estado:** observacional; sem ligação ao índice, pricing ou relatórios

## Problema atual

O motor atual pode atribuir contribuições separadas a superfície, velocidade,
indoor/outdoor e mudança de piso. Como estas componentes usam frequentemente
as mesmas partidas e o mesmo contexto físico, somá-las trata evidência
dependente como se fossem quatro confirmações independentes.

## Nova fronteira familiar

As quatro leituras passam a pertencer à família única
`surface_and_conditions`:

- desempenho na superfície física;
- desempenho no contexto indoor/outdoor explicitamente conhecido;
- desempenho no balde de velocidade, apenas em hard classificado;
- exposição e transição recente entre superfícies.

Os componentes permanecem visíveis, mas a política futura será uma só
contribuição familiar, nunca a soma dos seus pesos individuais.

## Proteções factuais

- o próprio dia e o futuro ficam excluídos;
- `Hard` simples não é assumido como outdoor sem evidência explícita;
- velocidade é `NOT_APPLICABLE_NON_HARD` em terra e relva;
- piso hard sem classificação de velocidade fica `UNCLASSIFIED`;
- ausência de venue/velocidade reduz cobertura, não produz empate ou zero;
- transição preserva sequência, piso dominante, exposição recente e dias
  desde o último encontro no piso atual;
- não existe preço de mercado, líder, score, peso ou contribuição.
- contextos atuais divergentes entre os dois jogadores falham como
  `CONTEXT_MISMATCH`, em vez de escolher silenciosamente um deles.

## Janelas preservadas

São expostas duas leituras factuais já coerentes com o projeto:

- 90 dias para a sequência contextual ligada à forma recente;
- 35 dias para exposição imediata e transição, mantendo também os valores
  brutos para futura auditoria.

Estas janelas ainda não determinam impacto. A sua utilidade terá de ser medida
por replay ATP, WTA e Challenger.
