# CHANGE-2026-11-12-202 — união segura no dashboard Challenger

## Causa

O sincronismo tentava executar `breakApart()` sobre o `dataRange`, que podia
intersetar apenas parte de uma união existente. O Google Sheets rejeita essa
operação quando o intervalo não contém todas as células unidas.

## Correção

- recolher todas as uniões da folha completa;
- anular cada união através do respetivo intervalo integral;
- aplicar a mesma proteção à folha de entradas Challenger;
- garantir 280 linhas para as tabelas-fonte dos gráficos, que chegam à linha
  277.

## Verificação

- teste unitário específico para múltiplos intervalos unidos;
- suite do sincronismo PAPER;
- `git diff --check`.
