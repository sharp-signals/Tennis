# Replay dos quatro contextos de piso

**Data:** 03/11/2026

**Estado:** exploratório, sem promoção operacional

## Candidatos comparados

1. carreira no contexto exato;
2. carreira + época anterior;
3. carreira + época anterior + época atual;
4. os três anteriores com redução para 50% conforme a amostra.

Hard outdoor e hard indoor são contextos distintos. A fonte ATP omitia o piso
em 2021–2025. Antes do replay, recuperou-se apenas metadata factual através de
nomes de torneio exatos cujo contexto observado era único. Não foram usados
resultado, odds, ranking ou score para resolver o piso.

## WTA

Foram comparados 4 114 alvos no holdout comum.

| Candidato | Log loss | Acerto |
|---|---:|---:|
| Carreira | 0,668966 | 60,82% |
| + época anterior | 0,663565 | 61,18% |
| + época atual | 0,661189 | 61,35% |
| + redução pela amostra | 0,641867 | 62,40% |

Os três incrementos foram suportados no holdout emparelhado. A redução pela
amostra produziu o maior ganho. Isto sustenta usar carreira, época anterior e
época atual no WTA, sem tratar percentagens de poucos jogos como certezas.

## ATP

O histórico tem 22 842 partidas. Dessas, 3 481 já traziam o contexto, 13 844
foram recuperadas por identidade exata e não ambígua do torneio e 5 517
continuam deliberadamente por resolver. O replay passou a ter 17 325 alvos com
contexto exato e 3 257 jogos no holdout emparelhado.

| Candidato | Log loss | Acerto |
|---|---:|---:|
| Carreira bruta | 0,674001 | 59,93% |
| + época anterior | 0,666695 | 61,01% |
| + época atual | 0,668986 | 60,45% |
| + redução pela amostra | 0,659517 | 60,06% |

A conclusão anterior de que as épocas não acrescentavam valor estava
contaminada pela ausência de metadata de piso. Com a recuperação, carreira,
época anterior e época atual permanecem ativas. A versão reduzida pela amostra
tem o melhor log loss. A época anterior melhora a exatidão para 61,01%; incluir
a época atual melhora o log loss face à carreira isolada, mas não face ao perfil
carreira + época anterior. A escolha final exige validação prospetiva.

## Decisão provisória

- WTA: carreira + época anterior + época atual, sempre reduzidas pela amostra,
  é o candidato principal para validação futura.
- ATP: carreira e épocas voltam a ser candidatas legítimas. O candidato com
  redução pela amostra lidera em log loss, mas ainda não é promovido.
- As 5 517 linhas ATP não resolvidas continuam excluídas do contexto exato; não
  são convertidas em hard outdoor por defeito.
- A família continua aberta: falta testar adaptação às mudanças de piso e
  segmentar os resultados por hard outdoor, indoor, terra e relva.

O holdout foi consultado durante o desenvolvimento desta família. Estes
resultados orientam o desenho, mas exigem confirmação em dados futuros antes de
qualquer efeito na fair odd.
