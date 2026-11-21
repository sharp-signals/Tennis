# CHANGE-2026-11-21-231 — atualização dinâmica das Finals

## Problema

O run `44954434212` reutilizou durante 3,6 horas uma cache do ATP Finals que
continha apenas a meia-final já iniciada. A final entretanto publicada não foi
consultada, pelo que o bot produziu zero observações, zero relatórios e nenhum
manifesto Telegram/email.

## Alteração

- a cache de fixtures do torneio mantém o TTL normal quando contém pelo menos
  um jogo futuro;
- uma cache vazia, malformada ou composta apenas por jogos já iniciados é
  atualizada imediatamente;
- o bloqueio de emparelhamentos provisórios e a verificação de identidade
  continuam inalterados.

## Preservado

- nenhuma odd de mercado cria ou altera a previsão;
- não são alterados pricing, famílias, pesos, fair odds, PAPER ou GREEN;
- a cache continua a poupar quota enquanto existir calendário futuro válido.

## Verificação

- regressão da meia-final já iniciada seguida de uma final publicada;
- regressão que confirma a reutilização da cache quando existe jogo futuro;
- testes de descoberta resiliente e CI completa.
