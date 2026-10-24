# CHANGE-2026-10-24-155 — Consistência da força dos fatores

## Objetivo

Corrigir, de forma conservadora, fatores percentuais que recebiam força total
logo após ultrapassarem o limiar mínimo de 3 pontos percentuais. A alteração
não muda pesos máximos, limites de famílias, direção dos fatores, pricing nem
critérios PAPER.

## Contrato aprovado

- `velocidade_piso`, `indoor_outdoor`, `tiebreak`, `pressao_ronda`,
  `nivel_adversario` e `comeback_set1` passam a combinar:
  - peso máximo já existente;
  - magnitude da diferença, com saturação aos 15 p.p. e chão prudente de 30%;
  - confiança da menor amostra bilateral, pela regra de raiz quadrada já usada
    pelo motor.
- Uma amostra não declarada recebe confiança neutra de 50%, nunca confiança
  total inventada.
- H2H global com um único jogo continua sem inclinar o índice.
- H2H no mesmo piso com um único jogo continua utilizável, mas limitado a 15%
  do peso disponível. A confiança cresce por patamares: 15%, 35%, 55%, 75% e
  100% para 1, 2, 3, 4–5 e 6+ jogos, respetivamente; dentro de cada patamar, a
  força distingue uma série dominante de uma série dividida.
- Os caps atuais por família continuam a ser aplicados depois destes ajustes.

## Preservado deliberadamente

- `PESOS` e `CAPS_FAMILIAS_PESOS`.
- Escala final 0–100 do índice de evidência.
- Limiar de ativação de 3 p.p.
- Separação ATP/WTA/Challenger e políticas de evidência por competição.
- Snapshots históricos ex ante e resultados já registados.
