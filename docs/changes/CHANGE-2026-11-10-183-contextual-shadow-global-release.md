# CHANGE-2026-11-10-183 — Identidade global do modelo contextual

## Nível

LEVEL 3 — metodologia probabilística, versionamento e runtime prospetivo.

## Decisão

O próximo ciclo contextual recebe a identidade global inequívoca
`FENZOBOT_CONTEXTUAL_2026_11`. Os números de versão internos deixam de ser
usados isoladamente como nome do produto ou da geração global.

O manifesto fixa e identifica separadamente:

- ranking: `contextual-ranking-v6`;
- combinação das famílias: `contextual-family-combination-v3-ranking-v6`;
- calibração de probabilidade: `contextual-probability-uncertainty-v3`;
- geração de runtime: `3`.

Os hashes dos contratos de origem e um fingerprint global tornam cada
observação reproduzível e impedem a associação silenciosa a outros pesos ou
calibrações.

## Fronteira operacional

Esta release permanece `PROSPECTIVE_SHADOW_ONLY`:

- não usa mercado para formar a previsão;
- não calcula edge nesta fase;
- não cria PAPER nem GREEN;
- não publica relatórios nem notificações;
- não produz efeito no bot operacional;
- exige ativação manual explícita e grava um ledger novo append-only.

O ledger V2 e os respetivos identificadores permanecem intactos como audit
trail. Não existe migração, reclassificação ou mistura retrospetiva.

## Critério de validação

- export determinístico do manifesto e bundle de runtime;
- regressões do runtime V2 preservadas;
- probabilidade, intervalo e fair odd produzidos pelo novo runtime;
- isolamento, deduplicação e identificação global auditáveis;
- workflow exclusivamente manual.
