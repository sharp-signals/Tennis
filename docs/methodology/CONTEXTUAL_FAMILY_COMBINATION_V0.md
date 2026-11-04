# Combinação das cinco famílias — contrato v0

## Objetivo

Combinar as probabilidades internas das cinco famílias numa primeira
probabilidade Fenzobot totalmente independente do mercado.

## Proteção contra leakage

1. Dentro do período de treino escolhem-se as regularizações das famílias.
2. As famílias são ajustadas no treino e produzem previsões para a validação,
   que não viram.
3. A validação é dividida cronologicamente para construir e regularizar a
   combinação.
4. As famílias são reajustadas em treino+validação e produzem previsões para o
   holdout congelado.
5. O combinador é avaliado uma única vez nesse holdout.

## Entradas do combinador

O segundo nível vê apenas:

- logit da probabilidade de cada família;
- indicador de família indisponível;
- indicador factual de `OBSERVED_NONE`, distinto de falta de dados.

Os componentes crus não voltam a entrar. Isto reduz duplicação e impede que o
mesmo resultado seja contado em várias famílias.

## Restrições

- coeficientes direcionais das famílias são não negativos: redundância reduz
  uma família até zero, mas nunca inverte artificialmente o seu significado;
- forma recente e força estrutural são exigidas para prontidão operacional;
- serviço/resposta não pode, sozinho, tornar um jogo operacionalmente pronto;
- ausência de H2H confirmada não é tratada como dado em falta;
- a calibração do intervalo de incerteza permanece uma fase posterior;
- odds de mercado continuam totalmente excluídas.

## Aprovação mínima

A combinação só fica `HOLDOUT_SUPPORTED` se superar no holdout:

1. a previsão constante; e
2. a melhor família individual.

Uma probabilidade central suportada ainda não é uma fair odd operacional. Falta
calibrar incerteza, limites de extrapolação e prontidão por cobertura.
