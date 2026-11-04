# Replay dos pontos como residual estrutural v5 — 3 de novembro de 2026

**Estado:** benefício não demonstrado  
**Âmbito:** ATP e WTA  
**Challenger:** fora da decisão  
**Mercado:** não utilizado  
**Efeito em produção:** nenhum

## Hipótese

Testar se os pontos ATP/WTA acrescentam informação depois de o modelo já
conhecer o ranking contínuo. Ranking e pontos entraram como componentes
separados; pontos em falta permaneceram nulos e nunca alteraram o ranking.

Exemplo: #20 com 2 800 pontos contra #25 com 1 600 pontos. A diferença de
pontos só deve permanecer se melhorar jogos futuros para além da diferença de
ranking já observada.

## Resultado

| Circuito | Jogos | Log loss referência | Log loss v5 | Ganho v5 | Intervalo 95% | Decisão |
|---|---:|---:|---:|---:|---:|---|
| ATP | 5 143 | 0,626620 | 0,626699 | -0,000079 | [-0,001092; +0,000935] | inconclusivo |
| WTA | 4 815 | 0,622267 | 0,622203 | +0,000064 | [-0,001706; +0,001833] | inconclusivo |

Não existe prova fora da amostra de que os pontos melhorem a força estrutural.

## Coeficientes observados

| Componente | ATP | WTA |
|---|---:|---:|
| Ranking contínuo | 0,399249 | 0,304738 |
| Pontos | 0,283391 | 0,369240 |
| Trajetória | 0 | 0 |
| Inatividade | 0,004355 | 0,085623 |
| Recuperação | 0 | 0 |

Os pontos receberam coeficiente no desenvolvimento, mas apenas redistribuíram
informação já presente no ranking. O holdout não confirmou benefício.

## Decisão final provisória da força estrutural

1. Ranking atual contínuo, sem saturação, é o único sinal estrutural confirmado.
2. Pontos não criam um segundo voto. Podem permanecer como contexto factual e
   ser futuramente estudados como fallback quando o ranking estiver ausente.
3. Patamares competitivos são explicação humana, não bónus matemático adicional.
4. Trajetória e recuperação não recebem contribuição própria nesta versão.
5. Inatividade permanece indicador de incerteza; o efeito direcional ainda não
   está comprovado.
6. Pico histórico nunca substitui o nível atual.
7. Esta decisão ainda precisa de validação temporal repetida/prospetiva antes de
   produção, porque o holdout atual já foi consultado durante as iterações.

## Próximo passo

Congelar esta família para desenvolvimento e avançar para a forma recente
ajustada: competitividade, qualidade de vitórias, qualidade de derrotas,
recência e transferência entre circuitos/contextos.
