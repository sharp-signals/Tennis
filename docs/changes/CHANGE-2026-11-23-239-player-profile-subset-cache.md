# CHANGE-2026-11-23-239 — Cache isolada por jogador

## Evidência

A primeira execução completa publicou 311 fichas, mas o resumo indicou 713
jogadores ignorados. Os subconjuntos por jogador herdavam a mesma
`history_cache_key` do histórico completo. O índice de nomes podia, por isso,
ser reutilizado entre jogadores diferentes.

## Correção

- cada subconjunto recebe uma chave composta pela fonte e identidade do
  jogador;
- aliases auditados continuam agregados na mesma chave;
- o workflow passa a falhar antes da publicação se existir qualquer jogador
  ignorado, impedindo um catálogo parcial silencioso.
