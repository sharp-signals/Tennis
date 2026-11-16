# CHANGE-2026-11-16-212 — hierarquia sensível a consenso e conflito

## Nível e objetivo

Alteração **Level 3**, limitada ao pricing contextual SHADOW. Corrige a
regressão da geração 11 que comprimia evidência secundária mesmo quando as cinco
famílias apontavam para o mesmo jogador. Mantém a fair odd independente do
mercado e não cria PAPER, GREEN ou execução real.

## Causa-raiz confirmada

A regra v9 aplicava sempre dois limites por encontro: cada secundária ficava
abaixo da média realizada das principais e o bloco secundário abaixo do bloco
principal. Em Medvedev–Cobolli, as cinco famílias favoreciam Medvedev, mas uma
força estrutural quase neutra reduziu superfície de `+5,781 p.p.` para
`+0,925 p.p.` e serviço/resposta de `+7,356 p.p.` para `+1,170 p.p.`. A
probabilidade caiu de `63,8%` na geração 10 para `51,9%` na geração 11, sem
alteração factual equivalente.

## Regra v10

- Se as duas famílias principais não se opõem e todas as famílias secundárias
  ativas apontam para o mesmo lado, o consenso unânime é preservado. As
  principais autorizam a direção; as secundárias apenas refinam a magnitude.
- Se as principais divergem, ou qualquer secundária aponta no sentido oposto,
  mantém-se o bloqueio rígido v9: secundária individual abaixo da média das
  principais e bloco secundário abaixo do bloco principal.
- Sem contribuição principal, o bloco secundário continua impedido de criar
  sozinho uma previsão.
- Não existem exceções por jogador, jogo, ranking ou odd de mercado.

## Leitura visual

O antigo rótulo único `ligeiro` abrangia qualquer impacto abaixo de `3 p.p.`.
Passa a distinguir `residual` (`<0,5 p.p.`), `muito ligeiro`
(`[0,5; 1,5[ p.p.`) e `ligeiro` (`[1,5; 3[ p.p.`). Esta alteração é apenas
semântica/visual e não muda probabilidades.

## Replay cronológico

Foram reutilizados os caches validados com 26 691 jogos ATP e 24 498 WTA,
sem chamadas externas. A avaliação final permaneceu no holdout cronológico:

- ATP: 5 279 jogos; ganho de log-loss contra a v8 `-0,000691`, intervalo 95%
  `[-0,001554; +0,000173]` — inconclusivo, sem degradação demonstrada.
- WTA: 4 846 jogos; ganho `-0,000012`, intervalo 95%
  `[-0,000972; +0,000949]` — inconclusivo, essencialmente neutro.
- O calibrador posterior foi estimado apenas no desenvolvimento e a incerteza
  foi reconstruída para a combinação v10.

## Casos de regressão verificados

- Medvedev–Cobolli, com as mesmas probabilidades familiares observadas:
  `51,9% / 1,93` na geração 11 para `64,7% / 1,55` na geração 12.
- Fils–Jodar mantém leitura equilibrada (`48,2% / 2,07`) porque as duas
  famílias principais divergem; não recebe reforço artificial.

## Preservado

- Observações históricas não são reescritas.
- Mercado continua totalmente fora da previsão e da fair odd.
- Equações internas e fontes factuais das cinco famílias não são alteradas.
- A release permanece experimental, SHADOW e reversível.
