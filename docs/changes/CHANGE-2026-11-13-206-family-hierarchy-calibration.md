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
