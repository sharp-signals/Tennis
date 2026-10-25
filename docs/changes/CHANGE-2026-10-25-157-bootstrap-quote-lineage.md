# CHANGE-2026-10-25-157 — Inicializar a linhagem de odds pelo ledger

## Regressão observada

Depois da ativação do contrato v6, Cameron Norrie–Francisco Cerundolo voltou a
ser publicado com `2.14 / 1.70`. A nova cache de linhagem estava vazia e
classificou a quote como `FIRST_OBSERVATION`, embora o Market-Time Ledger já
tivesse o mesmo preço desde 24 de outubro às 17:33 UTC.

## Causa-raiz

A proteção de CHANGE-156 só lia a cache criada por essa própria alteração.
Não inicializava a primeira observação a partir do histórico factual já
persistido. Assim, a primeira execução pós-merge tinha uma janela cega.

## Correção

- O histórico RapidAPI do Market-Time Ledger é indexado uma vez por processo.
- A linhagem consulta sempre as observações anteriores do mesmo evento e par
  de odds, incluindo quando a cache nova já contém uma primeira observação.
- Observações duplicadas da mesma captura são deduplicadas.
- Apenas a sequência contínua mais recente do mesmo preço é considerada; uma
  alteração real da quote reinicia a linhagem.
- O caso factual `690252`, observado a `2.14 / 1.70` desde
  `2026-10-24T17:33:31Z`, passa imediatamente a exceder a janela de seis horas
  na primeira execução com este código.

## Preservado

Não se alteram pesos, índice, edge mínimo, estratégia, resultados históricos,
Sheets ou chamadas externas. Uma quote sem prova temporal que exceda a janela
continua disponível apenas como observação factual e não cria edge/PAPER.

O contrato passa a `verified-direct-pre-match-v7`, com semântica
`provider-timestamp-or-ledger-bootstrapped-lineage-v4`.
