# Replay dos quatro contextos de piso

**Data:** 03/11/2026

**Estado:** exploratório, sem promoção operacional

## Candidatos comparados

1. carreira no contexto exato;
2. carreira + época anterior;
3. carreira + época anterior + época atual;
4. os três anteriores com redução para 50% conforme a amostra.

Hard outdoor e hard indoor são contextos distintos. Jogos cujo recinto não
estava identificado foram excluídos deste teste, sem imputação.

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

O histórico tinha 22 842 partidas, mas apenas 3 481 com contexto exato de piso
identificado. O holdout emparelhado ficou em 601 jogos.

| Candidato | Log loss | Acerto |
|---|---:|---:|
| Carreira bruta | 0,690023 | 55,91% |
| + época anterior | 0,690023 | 55,91% |
| + época atual | 0,690023 | 55,91% |
| + redução pela amostra | 0,683506 | 55,57% |

A redução pela amostra melhorou o log loss de forma suportada. Os componentes
anuais brutos foram reduzidos a coeficiente zero; a fonte cronológica ATP ainda
é demasiado curta para confirmar evolução anual. Isso não prova irrelevância:
os agregados atuais têm cobertura ampla, mas não podem ser usados no replay
passado sem fuga temporal.

## Decisão provisória

- WTA: carreira + época anterior + época atual, sempre reduzidas pela amostra,
  é o candidato principal para validação futura.
- ATP: carreira no contexto exato, reduzida pela amostra, é o único componente
  confirmado neste replay. Épocas ficam visíveis e armazenadas, mas sem voto
  até existir validação cronológica suficiente.
- A família continua aberta: falta testar adaptação às mudanças de piso e
  segmentar os resultados por hard outdoor, indoor, terra e relva.

O holdout foi consultado durante o desenvolvimento desta família. Estes
resultados orientam o desenho, mas exigem confirmação em dados futuros antes de
qualquer efeito na fair odd.
