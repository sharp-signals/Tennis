# Calendário ATP 2026 — torneios a seguir (Grand Slam / Masters 1000 / ATP 500)

> Fontes: calendário oficial ATP 2026 (atptour.com) e Wikipedia, consultados
> em 28/07/2026. Datas podem sofrer pequenos ajustes — confirma sempre
> perto da data antes de assumires que já começou.
>
> **Como usar:** quando um torneio desta lista estiver prestes a começar
> (ou já tiver começado), volta à conversa com o Claude, encontra o
> `tournamentId` na Playground do RapidAPI (mesmo processo que fizemos
> para o Washington Open — `getTournamentInfo`/`getTournamentFixtures`),
> e acrescenta-o a `TRACKED_TOURNAMENT_IDS` no `config.py`. Risca a linha
> (ou marca `[x]`) depois de o teres adicionado.

## Já a decorrer

- [x] **Citi Open - Washington** (ATP 500) — 27/07 a 02/08 — `tournamentId: 21344` ✅ já adicionado

## Próximos (por ordem cronológica)

- [ ] **Canadian Open** (Masters 1000) — Montreal, Hard — **2 a 13 de agosto**
- [ ] **Cincinnati Open** (Masters 1000) — Mason OH, Hard — **13 a 23 de agosto**
- [ ] **US Open** (Grand Slam) — Flushing Meadows, Hard — quadro principal **30 de agosto a 13 de setembro**
- [ ] **Japan Open - Tokyo** (ATP 500) — Hard — **~28 de setembro**
- [ ] **China Open - Beijing** (ATP 500) — Hard — **~28 de setembro**
- [ ] **Shanghai Masters** (Masters 1000) — Hard — **~7 a 18 de outubro**
- [ ] **Swiss Indoors Basel** (ATP 500) — Hard indoor — **~26 de outubro**
- [ ] **Erste Bank Open - Vienna** (ATP 500) — Hard indoor — **~26 de outubro**
- [ ] **Rolex Paris Masters** (Masters 1000) — Hard indoor — **~2 a 8 de novembro**

## Fora do âmbito atual (não seguimos, por decisão já tomada)

- ATP Finals - Turin (tier "Finals", não é Grand Slam/Masters/500 — fora
  de `ALLOWED_TOURNAMENT_TIERS`; podes acrescentar se quiseres alargar o
  âmbito no futuro)
- Todos os ATP 250 do calendário (Winston-Salem, Los Cabos, Almaty,
  Bruxelas, Lyon, Estocolmo, etc.) — excluídos desde a decisão de âmbito
  de 15/07/2026 (falta de odds fiáveis nesse nível)

## Nota sobre precisão das datas

As datas de ATP 500/Masters 1000 costumam ser estáveis, mas confirma
sempre no site oficial (atptour.com) ou pesquisando antes de assumir que
um torneio já arrancou — já vimos hoje que mesmo o calendário de um único
torneio (Washington) publica o quadro de jogos progressivamente ao longo
dos dias, não tudo de uma vez.
