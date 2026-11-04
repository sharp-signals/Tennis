# Probabilidade e incerteza contextual v2

## Finalidade

Converter a combinação hierárquica das famílias numa probabilidade central
calibrada e numa faixa empírica de incerteza, sempre antes de consultar o
mercado. Esta versão permanece **SHADOW**.

## Probabilidade central

A probabilidade produzida pela combinação hierárquica é comparada com uma
correção Platt simples e monotónica. A escolha é feita numa janela cronológica
anterior através de log loss. Se a correção não melhorar, preserva-se a
probabilidade original.

Não são testadas dezenas de curvas nem escolhido o melhor resultado no
holdout final.

## Intervalos

O holdout da combinação é novamente dividido por data:

1. primeira metade para construir bins de probabilidade e intervalos Wilson a
   90%;
2. segunda metade para testar cobertura, largura e extrapolação.

Os grupos distinguem:

- famílias principais completas e famílias secundárias completas;
- famílias principais completas com lacunas secundárias;
- pelo menos uma família principal indisponível.

Uma lacuna nunca altera a probabilidade central. Nos casos degradados, a faixa
usa a união entre o intervalo do grupo e o intervalo global correspondente;
assim a falta de dados não cria falsa precisão.

## Fair odd

- fair odd central = `1 / probabilidade calibrada`;
- limite inferior da odd = `1 / limite superior da probabilidade`;
- limite superior da odd = `1 / limite inferior da probabilidade`.

Esta transformação é matemática. Não autoriza uma aposta e não utiliza a odd
do bookmaker. A comparação com o mercado pertence a uma etapa posterior.

## Bloqueios

Um caso não fica pronto para observação prospetiva quando:

- falta forma recente ou força estrutural;
- a probabilidade fica fora do suporte histórico;
- o bin de calibração não possui a amostra mínima.

Cada bloqueio recebe um `reason_code` explícito.
