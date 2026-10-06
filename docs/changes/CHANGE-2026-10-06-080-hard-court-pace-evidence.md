# CHANGE-2026-10-06-080 — Evidência de velocidade em hard court

## Objetivo

Substituir o uso genérico de velocidade do piso por uma evidência auditável:
apenas hard courts com classificação factual no registo CPI podem ser
comparados. O fator só inclina o índice Fenzobot quando ambos os jogadores
têm pelo menos 10 jogos históricos comparáveis.

## Regra operacional

- **Hard court classificado:** compara os jogadores apenas no mesmo balde CPI
  (`slow`, `medium_slow`, `medium`, `medium_fast`, `fast`).
- **Amostra inferior a 10 de qualquer jogador:** apresenta o contexto no
  relatório, mas o fator não recebe peso nem muda o índice.
- **Hard sem classificação factual:** permanece sem velocidade, com motivo
  explícito; não é estimado a partir do nome do torneio.
- **Terra batida e relva:** velocidade do piso é `não aplicável`; a leitura
  usa o desempenho real na respetiva superfície, já existente no relatório.

## Fonte e proveniência

O registo versionado `COURT_PACE_INDEX` contém valores CPI observados da
fonte pública [Court Speed](https://courtspeed.com/). Cada retorno inclui
fonte, URL, chave canónica do torneio, ano usado e indicação de ano exato ou
de referência próxima (máximo dois anos). Não existe recolha automática em
runtime nem extrapolação para eventos não cobertos.

## Exemplo corrigido

`Shanghai Rolex Masters - Shanghai` é normalizado para a entrada canónica
`shanghai`. Para 2026, a entrada de 2025 é tratada como referência factual
próxima e identificada como tal, em vez de ser confundida com ausência de
dados.

## Preservado

- O fator de desempenho por superfície continua disponível para todos os
  pisos.
- Pricing, edge, regras PAPER e snapshots pré-jogo não são alterados.
- Dados ausentes continuam ausentes; nenhuma velocidade é inventada.
