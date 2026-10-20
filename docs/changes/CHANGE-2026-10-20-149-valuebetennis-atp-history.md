# CHANGE-2026-10-20-149 — Histórico ATP licenciado e recuperação de odds

## Objetivo

Acrescentar histórico ATP/Challenger com odds observadas e recuperar, quando a
identidade for inequívoca, odds de jogos canónicos que ficaram guardados sem
preço. A alteração é aditiva: nenhum snapshot pré-jogo, resultado, PAPER ou
agregado histórico protegido é reescrito.

## Fonte e licença

- Fonte: Valuebetennis — `https://www.valuebetennis.com/donnees.htm`.
- Dataset: resultados e odds anuais desde 2021.
- Licença declarada pela fonte: CC BY 4.0.
- Atribuição: “Valuebetennis, Résultats et cotes de tennis depuis 2021”.

## Decisão

- Guardar caches ATP anuais normalizadas, com abertura e fecho separados.
- Para as faixas históricas do relatório, usar o par de fecho quando existe;
  usar abertura apenas como fallback explicitamente identificado.
- Aplicar corte temporal: um relatório só pode consultar jogos anteriores ao
  encontro em análise.
- Manter Main Tour e Challenger identificados na origem.
- Criar um mapeamento separado de recuperação para snapshots ATP sem odds.
  Aceitar correspondência única por par exato de jogadores normalizados e
  data. Para a fronteira entre data local e UTC, aceitar ±1 dia apenas com
  torneio exato e candidato único; ambiguidades permanecem sem odd.
- Publicar no Histórico & Aprendizagem abas ATP e a auditoria de odds
  recuperadas, incluindo fonte, licença e semântica pós-jogo.

## Guardas

- Odds recuperadas nunca passam a ser `market_odds_decimal` do snapshot.
- Não reescrever HTMLs antigos nem recalcular decisões, edge ou PAPER.
- Não misturar abertura e fecho; ambos ficam auditáveis.
- Não chamar a recuperação pós-jogo de captura ex ante.
- Não alterar pesos, pricing, thresholds ou critérios de entrada.
- A baseline `forward-only` mantém-se byte a byte; as novas vistas são
  produtos operacionais aditivos.
