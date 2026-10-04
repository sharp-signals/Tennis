# CHANGE-2026-10-04-077 — Histórico: ATP operacional e leitura de rentabilidade

## Objetivo

Tornar o ficheiro **Fenzobot — Histórico & Aprendizagem** mais útil para
leitura de decisão, sem inventar um histórico ATP bruto que não existe neste
repositório e sem alterar o motor de pricing, PAPER ou os snapshots antigos.

## Alterações

- Cria abas **ATP operacional** a partir de snapshots canónicos Fenzobot já
  liquidados, separadas do histórico WTA de `tennis-data.co.uk`.
- Acrescenta tabelas de **acerto × faixa de odd**, **índice × faixa de odd** e
  respetiva odd média, break-even teórico e margem em pontos percentuais.
- Atualiza o gráfico de odds para comparar diretamente acerto com break-even
  e exclui a categoria `sem faixa` do gráfico.
- Esclarece em todos os rankings de handicap que `-4.5`, `+2`, etc. são
  linhas internas BO3 de referência; não são lucro, rendimento ou linhas de
  bookmaker. A métrica do Top/Bottom 10 é `% cobre`.
- Mantém WTA histórico, ATP operacional e PAPER/REAL explicitamente
  separados. Não há nova recolha externa nem reprocessamento do passado.

## Limites assumidos

- O break-even é apenas `1 / odd média decimal` das observações canónicas.
  Não mede ROI nem incorpora stake, margem, limites ou a execução na 22Bet.
- Não existe cache histórica ATP bruta local para produzir as mesmas métricas
  de handicap, recuperação, tiebreak ou set decisivo disponíveis para WTA.
  Por isso as novas abas ATP dizem `operacional` e não `histórico`.

## Validação

- Testes unitários do histórico devem validar agregação por faixa, cruzamento
  índice × odd, separação ATP/WTA e rótulo de handicap.
- Após merge, atualizar o Apps Script `sync_system_history.gs` na conta
  Fenzobot e executar `syncSystemHistoryToSheet` uma vez para reconstruir as
  abas geradas.
