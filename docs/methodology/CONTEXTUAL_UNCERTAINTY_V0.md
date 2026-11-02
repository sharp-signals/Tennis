# Incerteza e limites de segurança — contrato v0

## Objetivo

Transformar a probabilidade central market-free num intervalo auditável antes
de qualquer utilização como fair odd.

## Corte temporal adicional

O holdout da combinação é dividido por datas em duas metades:

- primeira metade: calibra intervalos;
- segunda metade: testa esses intervalos.

Uma data nunca fica nos dois lados.

## Método inicial

- probabilidades são agrupadas por quantis dentro do circuito;
- casos com forma+força estrutural disponíveis são separados dos degradados;
- a frequência real de vitórias em cada grupo recebe intervalo de Wilson a
  90%;
- cada probabilidade individual mantém a central dentro do intervalo;
- grupos pequenos recorrem a um bin global com amostra mínima de 80;
- os percentis 0,5% e 99,5% definem o suporte histórico inicial;
- fora desse suporte o caso é `EXTRAPOLATION` e não fica operacionalmente
  pronto.

Na avaliação, o intervalo de Wilson aprendido é comparado com o intervalo de
Wilson do grupo de teste. Exigir que o ponto observado caia exatamente dentro
do primeiro intervalo ignoraria a incerteza amostral do próprio teste.

## Estados

`READY_FOR_PROSPECTIVE_SHADOW` exige:

- forma recente e força estrutural observadas;
- probabilidade dentro do suporte histórico;
- bin de calibração com amostra suficiente.

Todos os restantes casos ficam `NOT_OPERATIONALLY_READY`. Serviço/resposta,
superfície ou H2H não conseguem substituir as duas famílias principais.

## Fair odd

A conversão é apenas matemática:

- central: `1 / probabilidade central`;
- limite inferior da odd: `1 / probabilidade superior`;
- limite superior da odd: `1 / probabilidade inferior`.

Nesta fase as odds ficam `SHADOW_ONLY_NOT_OPERATIONAL`. Não são comparadas com
o mercado e não criam PAPER.
