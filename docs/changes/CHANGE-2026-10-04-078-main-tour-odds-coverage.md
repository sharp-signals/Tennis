# CHANGE-2026-10-04-078 — Cobertura de odds RapidAPI nos torneios elegíveis

## Objetivo

Evitar que um jogo ATP/WTA elegível fique em **Mercado pendente** apenas porque
o respetivo torneio não foi uma das competições consultadas pela The Odds API
naquela execução. Isto afetava, por exemplo, torneios ATP 500/1000 simultâneos
como Tokyo e Shanghai.

## Decisão

1. A The Odds API continua a ser preferida quando devolve uma Moneyline
   bilateral com timestamp fresco por bookmaker.
2. Quando essa fonte não devolve preço para o jogo, o motor consulta
   `RapidAPI event/recent-odds/get/{eventId}` na própria execução.
3. A resposta RapidAPI só entra no pricing se cumprir todos estes requisitos:
   evento pré-live e identidade verificados, uma casa nomeada, os dois lados
   na mesma casa, odds decimais válidas e Market Quote Integrity disponível.
4. Não são promovidas para pricing as odds embutidas em `upcoming`, respostas
   de cache, combinações de lados de casas diferentes ou identidades não
   verificadas.

## Semântica e limites

O timestamp `addTime` da RapidAPI permanece guardado como auditoria, mas não é
usado como relógio de frescura: foi observado que pode permanecer inalterado
quando as odds devolvidas se alteram. A proveniência passa a dizer
`OBSERVED_AT_CAPTURE`: significa que a resposta foi recebida diretamente nesta
execução, não que a idade do timestamp do bookmaker foi confirmada.

Por isso a fonte é válida para gerar o relatório/preço desta execução, mas não
é comparável para CLV temporal. A The Odds API mantém prioridade sempre que a
sua quote timestamped estiver disponível.

O bot continua fail-closed se a própria RapidAPI não devolver uma Moneyline
bilateral verificável, se o jogo já não for pré-live ou se exceder o orçamento
diário. Nesses casos o relatório factual permanece, mas não se inventa preço
nem PAPER.

## Preservado

- Limite mensal conservador da The Odds API; não é aumentado.
- Política de tiers, limiares de edge e regras PAPER.
- Monitor SHADOW, dados históricos e snapshots já guardados.
- A feed `upcoming` continua observação/telemetria e não pricing normal.
