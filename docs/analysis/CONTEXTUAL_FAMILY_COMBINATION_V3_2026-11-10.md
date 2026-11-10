# Combinação final das famílias v3 — ranking contextual

**Data:** 2026-11-10  
**Estado:** contrato SHADOW congelado; sem promoção operacional  
**Mercado:** ausente da previsão

## Pergunta

O ranking contextual v6 acrescenta valor quando deixa de ser avaliado sozinho
e passa a dialogar com forma recente, superfície, H2H e serviço/resposta?

Para evitar trabalho e comparação injusta, cada histórico foi construído uma
única vez. Os mesmos jogos, partições cronológicas e restantes famílias foram
usados em dois candidatos. A única diferença foi:

- baseline: força estrutural `legacy_v0`;
- candidato: força estrutural `contextual_v6`.

## Perfis congelados

- forma recente: `recent_v2`;
- força estrutural: `contextual_v6`;
- superfície: `surface_exact_career_seasons_shrunk`;
- H2H: `h2h_global_shrunk_v1`;
- serviço/resposta ATP: pontos no piso + desvio recente reduzido;
- serviço/resposta WTA: pontos no piso reduzidos.

A hierarquia mantém forma recente e força estrutural como pilares. Superfície,
H2H e serviço/resposta continuam limitados e nunca podem dominar sozinhos.

## Resultado emparelhado

| Circuito | Holdout | Log loss baseline | Log loss v3 | Ganho | IC 95% | Acurácia baseline | Acurácia v3 |
| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| ATP | 5 265 | 0,619879 | 0,618786 | +0,001093 | +0,000411 a +0,001776 | 65,66% | 65,70% |
| WTA | 4 894 | 0,612927 | 0,610486 | +0,002441 | +0,001153 a +0,003728 | 65,86% | 66,04% |

O intervalo de confiança fica totalmente acima de zero nos dois circuitos.
Logo, o ranking v6 é **suportado dentro da combinação final**, apesar de o seu
teste familiar isolado ter sido inconclusivo. A leitura prática é que a sua
informação ganha valor quando combinada com as outras famílias.

O ECE passou de 0,021928 para 0,022092 no ATP e de 0,017325 para 0,016851 no
WTA. A pequena degradação ATP será tratada no bloco próprio de calibração e
incerteza; não invalida o ganho confirmado de log loss, mas impede promoção
direta sem essa etapa.

## Gestão de recursos

O comparador constrói as linhas históricas uma vez por circuito e reutiliza-as
nos dois modelos. O contrato resultante guarda os modelos familiares e os
coeficientes necessários para a próxima calibração, evitando reconstruir todas
as famílias a cada análise seguinte.

## Decisão

- congelar `contextual-family-combination-v3-ranking-v6` como candidato SHADOW;
- não alterar ainda bot, relatórios, fair odd, PAPER ou GREEN;
- usar este contrato como entrada da calibração final de probabilidade e
  incerteza;
- manter comparação pós-mercado completamente separada.

Artefactos:

- `data/validation/contextual-family-combination-v3-ranking-v6.json`;
- `data/models/contextual-family-combination-v3.json`.
