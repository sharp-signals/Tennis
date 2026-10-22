# CHANGE-2026-10-22-152 — performance por fase do torneio

## Objetivo

Separar a performance observacional do GREEN automático e do PAPER manual de
Guerra em três fases factuais do torneio:

- qualificação;
- primeiras rondas do quadro principal;
- fases finais: quartos de final, meias-finais e final.

Cada grupo publica amostra resolvida, vitórias/derrotas, taxa de acerto, unidades
e ROI. O GREEN acrescenta o cruzamento com alinhamento ou divergência face ao
mercado; o PAPER de Guerra acrescenta o cruzamento com alinhamento ou
divergência face ao Fenzobot.

## Contrato de classificação

A fase usa exclusivamente o identificador ou rótulo factual da ronda guardado
no snapshot canónico. Não é inferida pela data, pelo nome dos jogadores ou pelo
tamanho presumido do torneio.

- IDs 1–3: `QUALIFYING`;
- IDs 4–7: `EARLY_ROUNDS`;
- IDs 9, 10 e 12: `LATE_STAGES`;
- evidência ausente ou desconhecida: `ROUND_UNRESOLVED`.

Os rótulos equivalentes Q/Q1–Q3, R128/R64/R32/R16 e QF/SF/F são aceites. O
grupo não resolvido permanece visível e separado para impedir conclusões
baseadas numa classificação inventada.

## Integração

- O relatório agregado GREEN lê os snapshots canónicos e publica `by_stage` e
  `by_stage_and_alignment`.
- O índice público usado pelo Apps Script inclui apenas a fase factual compacta,
  sem resultados privados nem seleções manuais.
- A sincronização PAPER publica `by_stage` e `by_stage_and_alignment` dentro de
  `GUERRA_SELECTION_V1`.
- O dashboard apresenta GREEN e Guerra lado a lado, incluindo acerto, ROI e
  dimensão da amostra.

## Limites e segurança

Esta alteração é exclusivamente analítica e descritiva. Não altera pesos,
pricing, edge, seleção, criação de PAPER/GREEN ou regras de entrada. Resultados
com amostras pequenas não constituem validação de rentabilidade futura.

