# Probabilidade e incerteza v2 — replay de 2026-11-04

## Resultado

ATP e WTA rejeitaram a correção Platt: na validação cronológica, preservar a
probabilidade da combinação hierárquica teve menor log loss. Isto evita uma
correção estatística desnecessária.

| Circuito | Teste | Log loss | ECE | Pronto SHADOW | Intervalo mediano | P90 | Grupos cobertos |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ATP | 2.606 | 0,613543 | 2,93% | 86,72% | 8,08 p.p. | 16,67 p.p. | 15/15 |
| WTA | 2.425 | 0,606007 | 2,57% | 81,36% | 11,80 p.p. | 19,33 p.p. | 14/15 |

## Suporte histórico

| Circuito | Faixa de probabilidade suportada | Extrapolações no teste |
| --- | ---: | ---: |
| ATP | 8,51%–90,77% | 14 |
| WTA | 14,26%–90,12% | 34 |

## Leitura crítica

- A probabilidade central continua totalmente independente do mercado.
- Dados em falta não alteram o lado nem o valor central.
- O WTA apresenta incerteza superior ao ATP, refletida em intervalos mais
  largos e menor percentagem pronta.
- O único grupo WTA não coberto foi o bin mais baixo de
  `PRIMARY_DEGRADED`. Esses casos já ficam bloqueados e não são apresentados
  como prontos.
- Um intervalo a 90% descreve incerteza de calibração da faixa histórica; não
  significa 90% de probabilidade de o resultado individual ficar “dentro” do
  intervalo.

## Estado

- probabilidade central SHADOW: suportada;
- faixa de incerteza SHADOW: suportada para observação prospetiva;
- fair odd matemática: disponível;
- fair odd operacional/PAPER: **não autorizada**;
- mercado utilizado: **não**;
- produção alterada: **não**.

Fonte integral:
`data/validation/contextual-probability-uncertainty-v2-2026-11-04.json`.
