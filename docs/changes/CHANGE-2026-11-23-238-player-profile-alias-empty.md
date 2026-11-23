# CHANGE-2026-11-23-238 — Alias e histórico vazio nas fichas

## Causa

O catálogo consolidava aliases auditados na seleção, mas a extração interna
dos jogos da ficha ainda comparava nomes literalmente. Uma variante podia,
por isso, produzir um histórico vazio. A janela de 90 dias assumia depois a
existência da coluna temporal auxiliar e falhava com `KeyError: _date`.

## Correção

- a ficha reutiliza as máscaras normalizadas e os aliases já auditados pelo
  histórico canónico;
- um histórico vazio passa a manter uma coluna temporal vazia e tipada;
- ausência de jogos continua a ser `NOT_APPLICABLE`, nunca zero factual.
