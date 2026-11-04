# Replay da combinação hierárquica v2 — 2026-11-04

## Conclusão

A combinação hierárquica é suportada em SHADOW nos dois circuitos. Acrescentar
superfície, H2H e serviço/resposta de forma limitada melhora a leitura baseada
apenas em forma recente e força estrutural. A perda face a uma combinação livre
é pequena e compra uma garantia metodológica importante: os modificadores nunca
controlam sozinhos a previsão.

| Circuito | Acurácia | Log loss hierárquico | Só famílias principais | Livre | Ganho vs principais | Custo vs livre |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ATP | 65,68% | 0,619615 | 0,624982 | 0,619135 | 0,005367 | 0,000480 |
| WTA | 65,82% | 0,612849 | 0,618234 | 0,611195 | 0,005385 | 0,001654 |

## Coeficientes das famílias

| Circuito | Forma recente | Força estrutural | Superfície | H2H | Serviço/resposta |
| --- | ---: | ---: | ---: | ---: | ---: |
| ATP | 0,273819 | 0,642565 | 0,326430 | 0,147647 | 0,147647 |
| WTA | 0,420409 | 0,678080 | 0,352896 | 0,135629 | 0,135629 |

Estes números são coeficientes sobre a evidência probabilística de cada família,
não pontos do antigo índice nem percentagens fixas de importância.

## Verificações críticas

- mercado usado: **não**;
- fair odd calculada: **não**;
- impacto em produção: **nenhum**;
- combinação melhora as famílias principais: **sim, ATP e WTA**;
- modificadores respeitam a hierarquia: **sim**;
- ausência de dados altera a estimativa central: **não; coeficiente zero**;
- necessidade de validação prospetiva: **sim**.

Fonte integral da auditoria:
`data/validation/contextual-family-combination-v2-2026-11-03.json`.
