# Replay dos quatro contextos de piso

**Data:** 03/11/2026
**Estado:** família fechada para SHADOW; sem promoção operacional

## Desenho

Foram comparados cronologicamente:

1. carreira no contexto exato;
2. carreira + época anterior;
3. carreira + época anterior + época atual;
4. as três anteriores com redução para 50% conforme a amostra.

Hard outdoor e hard indoor são contextos distintos. ATP usa TennisMyLife;
WTA usa a cache tennis-data com `Court` explícito. Resultado, odds e ranking
não são utilizados para identificar o contexto.

## Resultado global

### ATP — 4 661 jogos no holdout emparelhado

| Candidato | Log loss | Acerto |
|---|---:|---:|
| Carreira | 0,660869 | 60,24% |
| + época anterior | 0,656790 | 61,68% |
| + época atual | 0,655740 | 61,21% |
| + redução pela amostra | **0,644625** | 61,17% |

A época anterior e a redução pela amostra foram suportadas. O incremento bruto
da época atual ficou inconclusivo, mas permanece na candidata reduzida para
observação prospetiva; não recebe força manual adicional.

### WTA — 4 114 jogos no holdout emparelhado

| Candidato | Log loss | Acerto |
|---|---:|---:|
| Carreira | 0,668966 | 60,82% |
| + época anterior | 0,663565 | 61,18% |
| + época atual | 0,661189 | 61,35% |
| + redução pela amostra | **0,641867** | **62,40%** |

Os três incrementos foram suportados no WTA.

## Auditoria por contexto

O valor abaixo é o log loss da candidata reduzida; menor é melhor.

| Circuito | Contexto | Jogos históricos | Holdout | Log loss | Ganho vs constante | Decisão |
|---|---|---:|---:|---:|---:|---|
| ATP | Hard outdoor | 10 558 | 2 008 | 0,640236 | 0,051495 | SHADOW |
| ATP | Hard indoor | 4 111 | 700 | 0,655767 | 0,037061 | SHADOW |
| ATP | Terra | 7 962 | 1 472 | 0,647869 | 0,044543 | SHADOW |
| ATP | Relva | 2 792 | 479 | 0,648162 | 0,044974 | SHADOW |
| WTA | Hard outdoor | 11 735 | 2 277 | 0,634769 | 0,058541 | SHADOW |
| WTA | Hard indoor | 1 357 | 226 | 0,695279 | 0,000097 | diagnóstico |
| WTA | Terra | 5 907 | 1 099 | 0,635836 | 0,058122 | SHADOW |
| WTA | Relva | 2 647 | 491 | 0,673052 | 0,020100 | SHADOW |

WTA indoor não demonstrou informação probabilística material contra a
referência. Continua visível, mas fica sem voto autónomo até existir evidência
prospetiva melhor. Isto não é empate nem dado ausente.

## Decisão fechada da família

- perfil: carreira + época anterior + época atual, reduzidas pela amostra;
- parâmetros definidos antes desta auditoria: dez pseudojogos na carreira e
  oito em cada época;
- equação separada por circuito e contexto;
- transição de piso apenas diagnóstica: o voto fixo foi rejeitado;
- velocidade apenas diagnóstica até existir histórico cronológico próprio;
- serviço e resposta permanecem na família própria;
- Challenger fica fora desta decisão;
- mercado, fair odd, PAPER e GREEN continuam desligados.

O holdout já foi consultado durante o desenvolvimento. O contrato fica
congelado para observação SHADOW e necessita de confirmação futura antes de
entrar na combinação final ou na fair odd.
