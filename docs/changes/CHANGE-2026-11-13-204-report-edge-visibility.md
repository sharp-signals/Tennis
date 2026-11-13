# CHANGE-2026-11-13-204 — mercados apenas com edge conservador confirmado

## Objetivo

Eliminar sugestões ambíguas nos relatórios contextuais e tornar explícita a
diferença entre pricing analítico e um mercado efetivamente confirmado.

## Regras

- Moneyline e handicaps só são exibidos quando o estado é
  `CONSERVATIVE_POSITIVE`.
- Edge apenas central, preço contrarian sem apoio familiar, dependência crítica
  e jogos `BALANCED_SENSITIVE` mantêm o pricing visível, mas não apresentam
  mercados sugeridos.
- A revisão de plausibilidade distingue a divergência total modelo–mercado do
  excesso para lá do intervalo estatístico.
- O cabeçalho identifica edge central como não confirmado.
- A evidência histórica de Moneyline mostra a força da amostra: `<20` pequena,
  `20–39` tendência e `>=40` utilizável.
- Nos relatórios confirmados, cada handicap mostra apenas o preço mínimo; o teto
  comum da janela (`2.50`) aparece uma vez.
- A fase de grupos das WTA Finals inferida por torneio fica explicitamente
  identificada como inferência.

## Preservado

- Probabilidades, famílias, pesos, fair odds e intervalos não são recalculados.
- O mercado continua fora da construção da fair odd.
- SHADOW não cria PAPER, GREEN nem recomendação automática.

## Contrato

`fenzobot-contextual-2026-11-report.11`.
