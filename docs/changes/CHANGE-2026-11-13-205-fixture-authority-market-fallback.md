# CHANGE-2026-11-13-205 — continuidade pré-jogo e fallback de mercado

## Objetivo

Impedir que um encontro já analisado desapareça dos relatórios apenas porque o
feed `upcoming` deixou de o devolver nos minutos anteriores ao início, e usar a
Moneyline pré-jogo do plano RapidAPI quando as duas fontes prioritárias não
conseguem produzir uma quote operacional.

## Regras

- A execução continua a construir primeiro os encontros devolvidos pelo feed
  atual.
- Pode transportar o snapshot mais recente de um encontro ainda não iniciado
  quando foi analisado nas últimas 36 horas e começa nas próximas 6 horas.
- O transporte nunca inclui jogos já iniciados ou snapshots históricos mais
  distantes; a publicação mantém o filtro existente de resultados liquidados.
- A captura de mercado mantém a ordem: The Odds API, RapidAPI `recent-odds` e,
  apenas depois, Moneyline embutida no feed pré-jogo da RapidAPI.
- O terceiro caminho só é aceite pelo contrato operacional já existente: par,
  orientação, `eventId`, captura atual e integridade têm de estar verificados.
- Como esse feed não identifica a casa, a cotação fica explicitamente rotulada
  como `RapidAPI pre-match feed (casa não identificada)`; não é atribuída a uma
  casa fictícia.

## Preservado

- Fair odd, famílias, pesos e probabilidades não são alterados.
- O mercado continua fora da previsão.
- SHADOW não cria PAPER, GREEN ou entrada automática.
- Relatórios cancelados ou já iniciados não são reintroduzidos.

