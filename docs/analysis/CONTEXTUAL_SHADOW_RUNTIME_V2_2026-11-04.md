# Runtime SHADOW v2 — validação de integração de 2026-11-04

## Estado

O runtime v2 foi ligado ao final da análise, depois da decisão operacional. A
previsão é guardada num ledger novo e não altera relatório, Telegram, PAPER,
GREEN ou pricing existente.

## Ensaio real completo

Foi construído um alvo prospetivo ATP com o histórico local até 03/11/2026:

**Ben Shelton vs Taylor Fritz · hard indoor**

- forma recente: 20 e 19 jogos;
- H2H: 5 jogos, 3 no mesmo contexto de superfície;
- cinco famílias disponíveis;
- cobertura: 100%;
- probabilidade Shelton: 41,59%;
- fair odd central Shelton: 2,40;
- intervalo de fair odd: 2,13–2,56;
- estado: `READY_FOR_PROSPECTIVE_SHADOW`.

O ensaio prova integração e coerência de contratos. Não valida esta previsão
individual nem autoriza entrada.

## Ensaio de bloqueio

**Alex de Minaur vs Jannik Sinner · cutoff 04/11/2026** ficou bloqueado porque
o histórico disponível não continha jogos de Sinner nos 90 dias anteriores ao
cutoff. O runtime:

- preservou probabilidade e diagnóstico para investigação;
- marcou `PRIMARY_FAMILY_UNAVAILABLE`;
- classificou `NOT_OPERATIONALLY_READY`;
- não produziu edge, PAPER ou GREEN.

## Challengers

Challenger recebe `OUT_OF_SCOPE / CHALLENGER_MODEL_NOT_CALIBRATED` sem exceção
nem aviso de falha. Não é persistido no ledger v2.

## Persistência

- novo ledger: `data/contextual_shadow_observations-v2.jsonl`;
- histórico v1 preservado;
- deduplicação por identidade canónica, versão e fingerprint;
- caminho incluído no perfil de publicação `bot`.
