# Smoke test do replay conjunto — ATP 2026 local

## Âmbito

Teste técnico read-only sobre `valuebetennis_atp_2026.csv.gz`. Esta cópia local
tem resultados, datas individuais, pisos, scores e H2H reconstruível, mas não
tem rankings nem estatísticas ponto a ponto. Não serve para calibrar o modelo.

## Execução

- linhas de origem: 13 518;
- alvos reconstruídos: 13 518;
- treino: 8 161;
- validação: 2 718;
- holdout: 2 639;
- duração local observada: cerca de 9 segundos;
- odds e mercado usados: não;
- pesos/probabilidades ajustados: não.

## Cobertura no holdout

| Família | Alvos com pelo menos uma componente | Cobertura |
|---|---:|---:|
| Forma recente | 2 408 / 2 639 | 91,25% |
| Superfície e condições | 2 471 / 2 639 | 93,63% |
| Matchup/H2H | 359 / 2 639 | 13,60% |
| Força estrutural | 0 / 2 639 | 0% |
| Serviço/resposta | 0 / 2 639 | 0% |

Os zeros das duas últimas famílias são uma limitação conhecida do schema desta
cópia, não evidência de que os fatores não funcionam.

## Sanidade direcional, não calibração

No holdout, as componentes disponíveis ficaram entre 54,5% e 59,6% de acerto
direcional. H2H no mesmo piso atingiu a maior percentagem, mas apenas em 302
alvos; não autoriza um peso elevado nem qualquer inferência causal.

## Decisão

O motor do replay está operacional e escalável. A execução oficial continua
fail-closed: exige a fonte histórica completa e atual, com ranking bilateral.
Serviço/resposta só será avaliado onde existam agregados ponto a ponto. Estes
resultados não alteram produção e não serão usados para escolher pesos.
