# CHANGE-2026-10-11-100 — Cobertura histórica Challenger 125

## Objetivo

Reduzir relatórios Challenger 125 degradados por ausência de histórico, sem
baixar os gates experimentais nem misturar silenciosamente este universo com o
ATP principal.

## Alteração

- O ATP principal mantém o histórico TennisMyLife anual já usado.
- Um jogo identificado factualmente como `Challenger 125` usa uma vista
  combinada dos ficheiros ATP anuais, `*_challenger.csv` e
  `challenger_ongoing_tourneys.csv` dos últimos dez anos.
- Cada linha recebe proveniência `main` ou `challenger`.
- Partidas repetidas entre o ficheiro anual e o ficheiro ongoing são
  deduplicadas por `tourney_id + match_num`, com fallback conservador.
- A cache passa a distinguir `atp:main` de `atp:challenger_125` e fica
  protegida contra carregamentos concorrentes.
- O relatório e os logs mostram quantas partidas ATP principal e Challenger
  sustentaram a análise.

## Segurança analítica

- Não foram alterados pesos, mínimos de cobertura, limiares de edge ou stake.
- Challenger 125 continua bloqueado para PAPER/GREEN automático.
- Challenger 100/75/50, Futures e ITF continuam excluídos.
- Não se inventa ranking. O fallback usa apenas o ranking registado numa
  partida histórica; se não existir, permanece sem dados.
- Nenhuma fonte com termos que proíbam recolha automatizada foi integrada.

## Validação

- Testes de composição e separação dos universos.
- Teste de deduplicação anual/ongoing.
- Teste de resolução de um jogador existente apenas no histórico Challenger.
- Suite Challenger e suite completa obrigatórias antes do merge.
