# CHANGE-2026-11-13-206 — hierarquia contextual e confiança H2H

## Objetivo

Calibrar historicamente a concordância entre `Forma recente ajustada` e
`Força estrutural`, mantendo-as como famílias principais, e impedir que um
único confronto direto produza um voto direcional.

## Regras

- Não existe ajuste manual para Fritz, Tirante ou qualquer jogador.
- A interação só existe quando as duas famílias principais apontam para o
  mesmo lado; a intensidade usa a mais fraca das duas evidências.
- O coeficiente da interação é aprendido cronologicamente e nunca pode ser
  superior ao coeficiente de qualquer família principal.
- Um H2H é factual, mas tem confiança direcional zero.
- A confiança H2H cresce depois do segundo jogo e fica completa a partir do
  quarto; o modelo continua a aplicar o shrinkage já existente.
- Mercado, odds e resultado futuro continuam excluídos da previsão.

## Gate de promoção

O candidato só pode substituir a combinação v8 depois de replay cronológico
ATP/WTA, comparação emparelhada fora da amostra, calibração de incerteza e
testes completos. Até essa decisão, `production_effect=false`.

## Resultado do replay cronológico

O replay usou 26 691 jogos ATP e 24 498 jogos WTA, com o período final
reservado exclusivamente para avaliação fora da amostra.

- O reforço global da concordância das famílias principais ficou
  inconclusivo e ligeiramente abaixo da v8 em ATP e WTA.
- Neutralizar o voto direcional de um único H2H piorou significativamente
  ambos os circuitos. A redução progressiva também foi rejeitada.
- Foram testados limiares de concordância forte, escolhidos no período de
  desenvolvimento. Nenhum demonstrou ganho estatisticamente confirmado no
  período final.
- Melhor variante ATP: `threshold_030`, ganho de log-loss `-0.000090`,
  intervalo de 95% `[-0.000356, 0.000175]` — inconclusivo.
- Melhor resultado observado WTA: `threshold_050`, ganho `+0.000051`,
  intervalo de 95% `[-0.000116, 0.000218]` — inconclusivo. O limiar escolhido
  apenas no desenvolvimento foi `threshold_015` e não melhorou o holdout.

## Decisão

O candidato não é promovido. A combinação v8 e a calibração de fair odds de
produção permanecem inalteradas. O relatório pode continuar a mostrar o H2H
único como facto, mas o replay não suporta retirar por decreto o pequeno efeito
que o modelo já lhe atribui. Não existe ajuste manual para Fritz ou Tirante.
