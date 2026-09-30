# CHANGE-2026-09-08-030 — integração e desambiguação de âmbito

Estado: validação funcional confirmada pelo utilizador em 08/09/2026; integração na branch da PR #120, sem merge em main.

## Rastreabilidade da colisão de identificador

Foram observados dois trabalhos distintos com o mesmo CHANGE-ID. Esta nota preserva ambos e usa a PR e os commits para identificar inequivocamente cada âmbito; não renomeia branches, commits, métricas ou registos históricos.

| Referência inequívoca | Âmbito | Evidência histórica |
|---|---|---|
| CHANGE-2026-09-08-030 / PR #120 | Auditoria, observabilidade, continuidade de métricas e apresentação | Head funcional aprovado e3979f51523b2d7a605746efc5c930af4247efbc; permanece sem merge nesta integração |
| CHANGE-2026-09-08-030 / PR #121 | Aliases auditados de eventos de odds e diagnósticos | Merge em main 948895fb780621b95c489f3c908c73649ac0c0e2, em 08/09/2026 |

O âmbito da PR #121 não é atribuído à PR #120. O identificador isolado é ambíguo neste caso; as referências acima mantêm o audit trail sem escolher retroativamente um novo CHANGE-ID.

## Integração

Base combinada: main 948895fb780621b95c489f3c908c73649ac0c0e2.
Preservar integralmente fetch_data.py, main.py e os testes de aliases da base. Em report_html.py, manter os diagnósticos da PR #121 e a identificação de cobertura operacional da PR #120. Nenhuma nova regra de pricing, seleção, aquisição ou classificação é introduzida.

## Gate de entrega

Suite Python e motor, Node, lint, compileall, pesquisa de segredos, paridade das métricas legacy antes/depois do refresh e igualdade dos dados primários contra a base. O workflow só publica a integração na branch se todos estes gates passarem. A revisão/merge em main e a verificação da publicação permanecem passos separados.
