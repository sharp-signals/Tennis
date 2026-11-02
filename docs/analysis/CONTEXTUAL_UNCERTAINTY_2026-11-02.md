# Incerteza e fair odds SHADOW — 02/11/2026

## Resultado

O holdout foi dividido novamente por tempo: primeira metade para construir os
intervalos e segunda metade para os testar. Os intervalos de calibração foram
estatisticamente compatíveis com os intervalos observados nos 10 grupos de
teste de cada circuito.

| Universo | Teste | Prontos para SHADOW prospetivo | Intervalo mediano | P90 da largura |
|---|---:|---:|---:|---:|
| ATP | 2 604 | 86,87% | 7,89 p.p. | 16,75 p.p. |
| WTA | 2 402 | 81,93% | 8,29 p.p. | 17,64 p.p. |
| Challenger | 4 599 | 82,08% | 6,48 p.p. | 12,17 p.p. |

`Pronto para SHADOW` exige forma recente e força estrutural disponíveis, bin
com amostra suficiente e probabilidade dentro do suporte histórico. Não
significa autorização para PAPER.

## Suporte histórico inicial

| Universo | Probabilidade suportada |
|---|---:|
| ATP | 9,45%–90,54% |
| WTA | 12,70%–90,61% |
| Challenger | 18,40%–83,42% |

Foram identificadas 10 extrapolações ATP, 26 WTA e 43 Challenger na segunda
metade do teste. Esses casos ficam automaticamente bloqueados.

## Interpretação

- intervalos estreitos aparecem onde o histórico foi consistente e abundante;
- largura elevada torna visível a incerteza, em vez de produzir uma fair odd
  excessivamente precisa;
- grupos degradados podem ser estatisticamente compatíveis, mas continuam sem
  prontidão porque serviço, superfície ou H2H não substituem forma+estrutura;
- pequenas diferenças entre frequências pontuais foram avaliadas através da
  sobreposição dos intervalos de Wilson de ambos os períodos;
- a fair odd central e o intervalo já podem ser calculados matematicamente,
  mas mantêm estado `SHADOW_ONLY_NOT_OPERATIONAL`.

## Exemplo de leitura futura

Se a probabilidade central for 60% e o intervalo 54%–66%:

- fair odd central: 1,67;
- intervalo de fair odd: aproximadamente 1,52–1,85;
- só depois, e fora do motor de pricing, poderá ser comparado o preço atual do
  mercado com o limite conservador.

## Próximo passo

Executar o novo modelo prospetivamente em SHADOW, sem PAPER, preservando por
jogo:

- cinco saídas familiares;
- probabilidade central e intervalo;
- fair odd central e intervalo;
- estados de cobertura, extrapolação e prontidão;
- resultado posterior para monitorizar calibração.

Esta observação futura é necessária antes de substituir o modelo atual ou
reformular definitivamente o relatório.
