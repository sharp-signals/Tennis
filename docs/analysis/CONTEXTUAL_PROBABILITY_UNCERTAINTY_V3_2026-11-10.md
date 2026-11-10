# Probabilidade, incerteza e fair odd v3

**Data:** 2026-11-10  
**Estado:** contrato SHADOW congelado; sem promoção operacional  
**Combinação:** `contextual-family-combination-v3-ranking-v6`

## Método

A calibração reutiliza diretamente os modelos e coeficientes congelados da
combinação v3. As cinco famílias não são novamente ajustadas. A janela exata
de desenvolvimento e holdout fica gravada no contrato e tem de ser reproduzida
integralmente; qualquer divergência falha de forma fechada.

Dentro do holdout congelado:

1. a primeira metade cronológica calibra a probabilidade e os intervalos;
2. a segunda metade testa log loss, Brier, acerto, calibração e cobertura;
3. identidade é comparada com uma correção Platt monotónica;
4. a correção só sobrevive se melhorar log loss numa seleção cronológica
   anterior ao teste final.

## Resultado

| Circuito | Teste final | Calibrador | Log loss | Brier | Acerto | ECE | Casos SHADOW prontos |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| ATP | 2 630 | Identidade | 0,612783 | 0,212627 | 66,01% | 0,027963 | 86,73% |
| WTA | 2 415 | Identidade | 0,604546 | 0,209116 | 66,25% | 0,025859 | 81,61% |

A identidade venceu a correção Platt nos dois circuitos. Portanto, a
probabilidade central da combinação v3 é preservada sem uma transformação
adicional escolhida artificialmente.

## Incerteza

| Circuito | Largura mediana | P90 | Grupos cobertos | Extrapolações |
| --- | ---: | ---: | ---: | ---: |
| ATP | 8,39 p.p. | 16,43 p.p. | 15/15 | 14 |
| WTA | 11,84 p.p. | 20,44 p.p. | 15/15 | 29 |

O WTA mantém intervalos mais largos, refletindo maior incerteza observada. Os
casos com forma recente ou força estrutural indisponível ficam bloqueados:
335 no ATP e 415 no WTA no teste final. Dados em falta não alteram a estimativa
central nem são tratados como empate.

## Fair odd

A fair odd é uma transformação exclusivamente matemática e market-free:

- central: `1 / probabilidade`;
- limite inferior: `1 / limite superior da probabilidade`;
- limite superior: `1 / limite inferior da probabilidade`.

O mercado só poderá ser consultado depois de a previsão e a faixa de fair odd
ficarem congeladas. Esta etapa não calcula edge, não cria PAPER/GREEN e não
publica relatórios operacionais.

## Gestão de recursos e leakage

- os modelos familiares são reutilizados sem refit;
- a fronteira desenvolvimento/holdout fica gravada por circuito;
- jogos posteriores à data final de avaliação não recalibram este contrato;
- futuras observações entram apenas na validação prospetiva;
- não há chamadas a fornecedores de odds.

Artefactos:

- `data/models/contextual-probability-uncertainty-v3.json`;
- `data/validation/contextual-probability-uncertainty-v3.json`.
