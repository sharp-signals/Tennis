# CHANGE-2026-11-13-207 — proteção contra emparelhamentos provisórios

## Problema

O fornecedor expôs simultaneamente Mirra Andreeva–Karolina Muchova na ronda
atual e Mirra Andreeva–Jessica Pegula numa ronda posterior das WTA Finals. O
segundo emparelhamento era provisório, mas tinha IDs exatos e odds, pelo que o
pipeline o tratou incorretamente como jogo factual e publicou um relatório.

## Alteração

- Uma fixture de fase posterior é excluída enquanto um dos jogadores ainda
  surge noutra fixture anterior do mesmo torneio.
- Jogos de round-robin com o mesmo identificador de ronda continuam válidos.
- Observações antigas de torneios `Championships` deixam de ser reativadas pela
  continuidade quando a descoberta factual da execução atual não as reconstrói.
- A telemetria passa a expor `provisional_fixture_guard.excluded`.

## Garantias

- Odds ou IDs exatos não transformam um emparelhamento futuro especulativo num
  jogo confirmado.
- O histórico permanece preservado; a proteção atua apenas na seleção corrente
  de fixtures e na publicação de relatórios ativos.
- A alteração não mexe em pricing, famílias, fair odds, PAPER ou GREEN.

## Verificação

- Regressão que reproduz Andreeva–Muchova + Andreeva–Pegula.
- Regressão que preserva múltiplos jogos legítimos de round-robin.
- Regressão que impede a continuidade de ressuscitar uma fixture volátil das
  Finals ausente da execução corrente.
