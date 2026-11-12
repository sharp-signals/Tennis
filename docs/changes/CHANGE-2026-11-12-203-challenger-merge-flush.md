# CHANGE-2026-11-12-203 — sincronização das uniões Challenger

## Causa

Após anular as uniões, o serviço Sheets ainda podia executar a limpeza visual
antes de materializar essa alteração. A limpeza da linha 1927 encontrava então
uma união antiga parcialmente abrangida e falhava.

## Correção

- executar `SpreadsheetApp.flush()` depois de anular as uniões;
- verificar novamente as uniões que intersetam a área visual;
- executar um segundo `flush` antes de limpar essa área.

## Verificação

- teste unitário da sincronização explícita;
- suite do Apps Script PAPER: 46/46;
- `git diff --check`.
