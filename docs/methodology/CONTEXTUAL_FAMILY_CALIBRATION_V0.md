# Equações internas das famílias — contrato v0

## Objetivo

Converter os componentes crus de cada família numa saída probabilística
própria, sem ainda combinar famílias ou produzir a fair odd final.

## Separação temporal

- **Treino:** estima os coeficientes candidatos;
- **Validação:** escolhe a regularização e, portanto, a complexidade;
- **Holdout:** é consultado uma vez para confirmar ou rejeitar a equação;
- ATP, WTA e Challenger são calibrados separadamente.

O holdout não pode ser usado para voltar atrás e escolher outro coeficiente.
Uma nova tentativa metodológica exige validação futura ou um novo corte
temporal declarado.

## Tratamento dos componentes

- extremos são limitados pelos percentis 1 e 99 calculados apenas no conjunto
  de desenvolvimento;
- cada componente é centrada pela mediana e escalada de forma robusta;
- valores em falta recebem imputação pela mediana **e um indicador explícito
  de ausência**; não são tratados como empate;
- regularização L1 pode reduzir componentes fracas exatamente a zero;
- uma pequena regularização L2 estabiliza componentes correlacionadas;
- o nível L1 é escolhido exclusivamente pela log loss de validação.

A fórmula simples `ranking atual vs. última observação de ranking` fica fora
da equação estrutural: já falhou no treino e na validação (aproximadamente
51–52% de direção). Os dados de trajetória continuam preservados para uma
formulação futura com âncoras de 30/90/180/365 dias.

## Forma da equação

Para cada família e circuito:

`logit(P(A vence | família observada)) = intercepto + soma(coeficiente × componente transformada)`

Esta probabilidade pertence apenas à família. Não é a probabilidade final do
Fenzobot e não pode ser comparada ainda com o mercado.

## Critério de suporte

Uma equação fica `HOLDOUT_SUPPORTED` apenas se superar a previsão constante
do conjunto de desenvolvimento tanto na validação como no holdout em log loss.
Caso contrário fica `NOT_SUPPORTED` e não avança para a combinação.

## Proibições

- zero odds ou probabilidades de mercado;
- zero ajuste manual de coeficientes após ver o holdout;
- zero efeito em pricing, relatórios, PAPER ou GREEN;
- zero combinação das cinco famílias nesta fase.
