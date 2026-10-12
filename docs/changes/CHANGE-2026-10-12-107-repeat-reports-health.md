# CHANGE-2026-10-12-107 — Repetição operacional e telemetria correta

**Nível:** 2 — BEHAVIOUR
**Estado:** IMPLEMENTED / NOT MERGED

## Problema

Depois da ativação da política prospetiva de evidência de competição, um jogo
ATP que já tivesse snapshot canónico era removido por completo das execuções
seguintes. A proteção devia congelar apenas a primeira decisão ex ante, mas
acabou também por impedir a apresentação operacional seguinte com a cotação
mais recente.

Os jogos preservados eram ainda contados no fecho da run como análises
falhadas. Em paralelo, correções determinísticas de validação eram anunciadas
como «fallback LLM elevado» apesar de `LLM_MODE=disabled` e de não existir
qualquer pedido externo.

## Alteração

- Um encontro canónico já decidido volta a produzir relatório nas execuções
  seguintes com os dados e a cotação observados nessa execução.
- A repetição reutiliza a política factual congelada no primeiro snapshot e é
  marcada como apresentação operacional, não como nova decisão prospetiva. Um
  snapshot legado sem metadados de política mantém explicitamente o tratamento
  legado, sem aplicação retrospetiva da política atualmente ativa.
- A repetição não cria nem substitui snapshot e não cria entrada PAPER.
- A recuperação de uma primeira entrega realmente incompleta continua a usar
  o bundle congelado e mantém a sua idempotência.
- `analysis_failed` passa a contar apenas exceções reais de análise.
- Alertas de fallback LLM só são emitidos quando houve pedidos LLM externos.

## Preservado

- Primeira fotografia pré-jogo, odds de entrada, pricing, decisão, validação e
  PAPER permanecem imutáveis e first-write-wins.
- Não há backfill nem reclassificação histórica.
- WTA, discovery, pricing, edge, handicaps, settlement e a política de
  evidência de competição não são alterados.
