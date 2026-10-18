# CHANGE-2026-10-18-144 — Histórico de odds e aliases auditados

## Problema

A construção paralela dos relatórios podia iniciar várias cargas simultâneas
do histórico de odds antes de a cache em memória ficar preenchida. Quando a
listagem comum do `tennis-data.co.uk` devolvia HTTP 403, o mesmo pedido era
repetido por vários jogos e por vários anos, sem recuperar dados e com muito
ruído no log.

Além disso, o feed operacional fornecia os nomes completos `Paula Badosa
Gibert` e `Leylah Annie Fernandez`, enquanto o histórico os guardava como
`Paula Badosa` e `Leylah Fernandez`.

## Decisão

- Serializar o primeiro carregamento do histórico de odds por processo.
- Preferir a cache persistida para anos já encerrados.
- Abrir um *circuit breaker* durante a execução depois de a listagem comum
  falhar, evitando pedidos idênticos para os anos e circuitos seguintes.
- Voltar a tentar normalmente na execução seguinte.
- Adicionar apenas as duas equivalências exatas de nome confirmadas nos dados.

## Guardas

- O histórico de odds mantém uso descritivo e não substitui pricing atual.
- Pricing, índice, edge, PAPER e critérios de elegibilidade não mudam.
- Não é criada uma correspondência para `Zangar Nurlanuly`: o jogador não
  existe no histórico ATP principal disponível e essa ausência permanece
  factual.
- Uma falha externa não é apresentada como se os dados tivessem sido obtidos.

## Validação

- Cobertura de HTTP 403 e *circuit breaker*.
- Preferência pela cache local em anos encerrados.
- Uma única carga sob concorrência de vários trabalhadores.
- Aliases exatos confirmados e ausência preservada para nome desconhecido.
- Suites direcionadas de transformação e resiliência externa.
