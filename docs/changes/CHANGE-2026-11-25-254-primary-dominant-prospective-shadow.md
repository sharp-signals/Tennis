# CHANGE-2026-11-25-254 — A/B prospetivo de domínio das famílias principais

## Objetivo

Testar prospectivamente, apenas no ATP e sem alterar a produção, se o modelo
subestima favoritos quando as cinco famílias concordam, a previsão continua
abaixo ou igual a 62,5% e o bloco das duas famílias principais é mais forte do
que o conjunto das três famílias secundárias.

## Contexto factual

O audit pós-seleção encontrou 46 casos ATP: o favorito venceu 33 (71,74%),
contra 60,20% previstos pela baseline. O ganho estatístico continuou
inconclusivo. No WTA, o mesmo padrão piorou a previsão e foi rejeitado.

## Hipótese congelada

- Universo: ATP apenas.
- As cinco famílias têm sinal direcional ativo no snapshot congelado e apontam
  para o favorito da baseline.
- A probabilidade do favorito na baseline é, no máximo, 62,5%.
- A magnitude realizada de `forma recente + força estrutural` é superior à
  magnitude realizada das três famílias secundárias.
- O candidato acrescenta `0,25889783` ao logit do favorito. Este valor é 50%
  do gap histórico observado (`0,51779565`), com shrinkage declarado antes da
  recolha prospetiva.

## Isolamento obrigatório

- A probabilidade e fair odd operacionais não mudam.
- O candidato não aparece nos relatórios, Telegram, PAPER ou GREEN.
- O mercado não entra no cálculo.
- O runtime e a fair odd principais não são alterados; o sidecar consome apenas
  os campos já congelados no ledger principal.
- Baseline e candidato ficam num ledger append-only separado.
- WTA não recebe esta variante.
- Um erro no sidecar desativa-o sem bloquear o Fenzobot principal.
- Nenhuma promoção é autorizada por este CHANGE.

## Avaliação futura

A comparação será emparelhada por jogo, usando log loss, Brier, calibração e
estabilidade cronológica. A hipótese só poderá regressar para decisão de
produto depois de evidência prospetiva suficiente; o audit histórico que a
originou não conta como confirmação.

## Rollback

Remover a recolha do wrapper `run_fenzobot_contextual_2026_11.py`. O release,
os relatórios e o ledger principal permanecem inalterados.
