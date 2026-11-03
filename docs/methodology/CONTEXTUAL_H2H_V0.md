# H2H contextual v0 — contrato factual

**CHANGE-ID:** CHANGE-2026-11-02-175

**Estado:** observacional; sem ligação ao índice, pricing ou relatórios

**Auditoria cronológica:** `scripts/audit_contextual_h2h_replay.py`. Esta
auditoria separa zero, um, dois a três e quatro ou mais confrontos e mede,
sem mercado, se a direção histórica se repete. Validação e holdout são
cronológicos e os resultados do mesmo dia nunca alimentam outro jogo.

## Princípio

H2H pertence à família de matchup. H2H global e H2H no piso não são duas
fontes independentes: são leituras da mesma lista de partidas. Cada confronto
é, por isso, preservado uma única vez e recebe marcadores contextuais.

## Factos preservados por confronto

- data e distância ao cutoff;
- vencedor factual;
- score e elegibilidade competitiva;
- piso e coincidência com o piso atual;
- circuito/contexto competitivo e respetiva coincidência;
- formato e respetiva coincidência;
- ronda;
- ranking dos dois jogadores à data;
- evolução de ranking de ambos desde esse encontro.

## Estados

- `AVAILABLE`: existem confrontos anteriores utilizáveis ou visíveis;
- `OBSERVED_NONE`: ambos os jogadores foram encontrados e a pesquisa confirmou
  zero confrontos; conta como cobertura, mas tem impacto nulo;
- `IDENTITY_UNRESOLVED`: pelo menos uma identidade não pôde ser confirmada;
- `SOURCE_UNAVAILABLE`: a fonte não tinha contrato mínimo pesquisável.

## Interpretação futura

O módulo permite distinguir sem ainda pontuar:

- um 1–0 antigo e noutro piso;
- um 1–0 recente no mesmo piso;
- um 2–0 recente;
- um 4–1 consistente;
- um confronto Challenger antes de um encontro ATP principal;
- um encontro terminado por retirada.

Um único encontro nunca recebe contribuição nesta fase. Repetição, recência e
coincidência contextual serão avaliadas por replay antes de qualquer curva.
Retiradas ficam visíveis, mas não entram no registo competitivo.

O replay mantém três leituras concorrentes — líder global, líder no mesmo
contexto de piso e líder recente no mesmo contexto — sem as somar. A equação
interna só será escolhida depois de comparar estas leituras no holdout.

## Proteções

- o dia do cutoff e o futuro são integralmente excluídos;
- não existe preço de mercado;
- `score`, `leader`, `weight` e `family_contribution` permanecem nulos;
- o módulo não é importado pelo motor atual;
- ausência confirmada de H2H é diferente de falta de dados.
