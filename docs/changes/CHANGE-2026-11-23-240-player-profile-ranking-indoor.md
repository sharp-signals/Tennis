# CHANGE-2026-11-23-240 — Ranking legível e indoor separado

## Problema

- o gráfico de evolução mostrava a forma da curva e o ano, mas não o número
  concreto do ranking;
- a tabela anual juntava hard indoor e outdoor numa única coluna.

## Alteração

- cada ponto do gráfico passa a apresentar o ranking típico da época;
- a tabela anual passa a separar `Hard outdoor` e `Indoor`, mantendo Clay e
  Grass;
- a separação usa o indicador canónico `indoor` e reconhece também rótulos
  explícitos de hard indoor.

## Garantias

- métricas continuam factuais e descritivas;
- nenhuma equação de fair odd foi alterada;
- testes cobrem a separação entre hard outdoor e indoor e os rótulos do
  ranking no HTML.
