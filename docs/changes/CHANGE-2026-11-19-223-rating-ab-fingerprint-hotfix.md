# CHANGE-2026-11-19-223 — compatibilidade do sidecar rating A/B

## Problema

O release principal passou para a geração 18/v15, mas o ensaio isolado rating
A/B continua congelado sobre a geração 17/v14. O runner bloqueava toda a
execução principal com `RATING_AB_BASELINE_FINGERPRINT_MISMATCH`.

## Decisão

- Não alterar artificialmente o fingerprint do ensaio antigo.
- Desativar apenas o sidecar A/B quando a baseline não coincide.
- Continuar a execução principal v15 e registar no resumo o estado e os dois
  fingerprints.
- Não produzir observações A/B enquanto os contratos forem incompatíveis.

## Preservado

- O mismatch continua visível e auditável; não é tratado como compatível.
- Nenhuma previsão, PAPER ou GREEN histórica é reescrita.
- A fair odd principal continua independente do mercado.
