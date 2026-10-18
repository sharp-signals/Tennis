# CHANGE-2026-10-18-145 — Integridade da Sheet e rankings WTA

## Objetivo

Corrigir a projeção da Sheet `Fenzobot — Histórico & Aprendizagem` sem alterar
pesos, pricing, edge, seleção operacional ou qualquer dado histórico.

## Problemas confirmados

- A versão instalada da projeção podia manter folhas antigas porque o
  fingerprint do conteúdo não mudava após uma correção apenas estrutural.
- Nomes abreviados do cache WTA (`apelido + inicial`) podiam ligar uma única
  aparição recente ao histórico completo de uma homónima antiga.

## Alteração

- Incrementar a versão da projeção do Apps Script para forçar uma reconstrução
  integral na próxima execução, criando as folhas de cobertura e limpando
  resíduos antigos já tratados pelo código atual.
- Considerar uma jogadora ativa nos rankings apenas após duas aparições no
  período móvel de 365 dias. O histórico bruto permanece intacto; a regra
  afeta somente a apresentação Top/Bottom 10.
- Cobrir por testes a janela temporal, a colisão de uma única aparição e o
  regresso confirmado por duas aparições.

## Preservado deliberadamente

- Pesos congelados até à revisão humana no final de outubro de 2026.
- Snapshots, resultados e histórico WTA bruto.
- Limiares de amostra dos rankings e todas as métricas do motor.
