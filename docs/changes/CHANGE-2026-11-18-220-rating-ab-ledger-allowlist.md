# CHANGE-2026-11-18-220 — persistência do ledger A/B

## Problema

O Fenzobot gerou corretamente o ledger prospetivo A/B, mas o publicador seguro
recusou o novo caminho por ainda não constar da allowlist do perfil `bot`.

## Correção

Autorizar exclusivamente `data/contextual_rating_ab_observations-v1.jsonl` no
perfil `bot`. A regra não autoriza diretórios adicionais, código ou segredos.

## Verificação

- O ledger A/B é aceite e preparado para commit.
- Um caminho não relacionado continua a falhar fechado.

## Rollback

Remover a entrada específica da allowlist.
