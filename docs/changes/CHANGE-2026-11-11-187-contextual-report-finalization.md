# CHANGE-2026-11-11-187 — Finalização contextual e relatório decisional

## Objetivo

Corrigir o último bloco técnico antes de nova validação humana do Fenzobot
contextual: normalização da superfície, dependência legítima de famílias
principais, regressos prolongados após lesão e leitura visual do relatório.

## Âmbito autorizado

- preservar integralmente o modo `PROSPECTIVE_SHADOW_ONLY`;
- impedir que mercado, odds ou edge entrem na probabilidade e na fair odd;
- usar o mercado apenas depois da previsão como controlo de plausibilidade;
- distinguir liderança sólida de uma família principal de dependência frágil;
- contrair ranking e pontos atuais em regressos prolongados com pouca amostra;
- recuperar serviço/resposta quando a API escreve superfícies como `I.hard`;
- tornar o relatório direto, visual e auditável, mantendo valores técnicos
  recolhidos numa secção colapsada;
- mostrar fotos e odds congeladas no cabeçalho quando disponíveis;
- manter Moneyline e handicaps como evidência para decisão humana, sem PAPER,
  GREEN, notificação operacional ou publicação automática.

## Regra de controlo pelo mercado

Uma divergência relevante não altera a previsão independente. Quando a
probabilidade implícita sem margem ficar fora do intervalo de 90% do modelo, o
relatório deve assinalar `REVISÃO DE PLAUSIBILIDADE`, identificar o lado e
explicar que pode existir evidência em falta, erro de identidade ou modelo mal
calibrado. Esta regra é diagnóstica e nunca recalcula a fair odd.

## Critérios de aceitação

1. `I.hard`, `Hard` e variantes equivalentes produzem o mesmo contexto.
2. Serviço/resposta volta a usar as linhas históricas do mesmo piso.
3. Uma família principal sólida pode liderar sem bloqueio automático; uma
   família parcial, secundária ou internamente frágil continua bloqueável.
4. Regresso prolongado reduz a confiança no ranking atual sem restaurar
   automaticamente o antigo nível do jogador.
5. O relatório mostra, por ordem: jogadores/odds, leitura direta, pricing e
   plausibilidade, Moneyline/handicaps, mapa visual das famílias e auditoria.
6. Testes específicos e suites contextuais relevantes passam.

## Fora de âmbito

- promoção do SHADOW;
- criação de PAPER/GREEN;
- alteração de resultados ou previsões históricas;
- alteração automática de pesos com base no mercado;
- exceções codificadas para jogadores concretos.
