# CHANGE-2026-10-04-079 — Cobertura pelo feed core de Moneyline RapidAPI

## Evidência da execução de 2026-10-04

O bot recebeu odds bilaterais no feed `ms-api/upcoming` para 40/40 jogos, mas
o endpoint premium `event/recent-odds/get/{eventId}` respondeu HTTP 403 para
26 jogos ATP. A indisponibilidade é do endpoint/entitlement, não da identidade
dos jogos: o event bridge verificou 34/40 `eventId`.

## Alteração

Nos tiers main-tour elegíveis, a Moneyline bilateral devolvida diretamente pelo
feed RapidAPI pré-jogo é agora o fallback operacional quando The Odds API não
tem preço para esse jogo. O endpoint `recent-odds` só é chamado se nem The Odds
nem o feed core trouxerem uma Moneyline válida.

O feed core tem de cumprir: resposta capturada na execução atual, evento e
ordem dos jogadores verificados, duas odds decimais válidas e Market Quote
Integrity disponível. Não são aceites resposta persistida, cache, lados
inferidos nem odds de evento não verificado.

## Transparência e limites

O feed core não informa a casa nem um timestamp da casa. A proveniência fica
marcada como `OBSERVED_AT_CAPTURE` e `NOT_EXPOSED_BY_PROVIDER_FEED`; pode
alimentar o preço/relatório desta execução, mas não é comparável para CLV nem
é apresentado como odd de uma bookmaker específica.

Challenger 125 conserva o modo experimental já aprovado e a regra de
meia-unidade; esta alteração não promove automaticamente esse tier a PAPER
normal.

## Resultado esperado

Tokyo, Shanghai e outros torneios elegíveis deixam de ficar pendentes só porque
a The Odds API adiou a competição ou porque `recent-odds` devolveu 403, desde
que o feed core traga a Moneyline bilateral do jogo.
