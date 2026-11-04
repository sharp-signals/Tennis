# Combinação contextual de famílias v2

## Objetivo

Combinar as famílias já validadas sem transformar o histórico numa máquina de
inventar pesos e sem permitir que um detalhe secundário domine a leitura de um
jogo. Esta versão é exclusivamente **SHADOW**. Não altera relatórios, PAPER,
GREEN, índice, probabilidade ou fair odd de produção.

## Hierarquia aprovada

1. **Forma recente e força estrutural** formam a opinião principal.
2. **Superfície e condições** ajustam essa opinião ao contexto do encontro.
3. **H2H** é um modificador opcional e limitado.
4. **Serviço e resposta** são informação secundária e limitada.

Os coeficientes não são percentagens escolhidas manualmente. São aprendidos em
ordem cronológica e depois projetados para as seguintes regras:

- a superfície não pode superar a média da força das duas famílias principais;
- o H2H não pode superar a superfície;
- serviço/resposta não pode superar o H2H;
- a soma dos três modificadores não pode superar a soma das duas famílias
  principais;
- sem força nas famílias principais, os modificadores ficam a zero.

## Dados em falta

Ausência de dados, ausência factual de H2H e estado meramente diagnóstico são
registados. Porém, todos têm coeficiente **zero** na estimativa central. No
bloco futuro de calibração, poderão alargar a incerteza; nunca podem favorecer
um jogador.

## Validação

Cada família é ajustada no passado. A regularização é escolhida numa janela
posterior e o resultado é medido num holdout cronológico ainda mais recente.
São comparados:

- combinação hierárquica;
- apenas forma recente + força estrutural;
- combinação não negativa livre;
- referência constante sem informação dos jogadores.

A hierarquia só é aceite se melhorar as famílias principais. O mercado e as
odds não entram em nenhuma destas fases.

## Limites

- Não é ainda uma fair odd.
- Não é autorização de entrada.
- O holdout foi consultado durante o desenvolvimento; por isso a validação
  prospetiva continua obrigatória antes de qualquer promoção.
- WTA hard indoor permanece diagnóstico por falta de sustentação histórica
  suficiente no bloco de superfície.
