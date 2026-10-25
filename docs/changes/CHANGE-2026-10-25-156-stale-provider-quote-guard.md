# CHANGE-2026-10-25-156 — Guardar contra quotes repetidas sem hora do fornecedor

## Incidente

No encontro Cameron Norrie–Francisco Cerundolo, o feed RapidAPI devolveu
exatamente `2.14 / 1.70` em 24 de outubro às 17:33 UTC, em 25 de outubro às
06:33 UTC e novamente às 09:54 UTC. O hash factual do registo também permaneceu
idêntico. Como o feed do plano PRO não expõe timestamp da casa nem bookmaker,
o sistema confundia «resposta HTTP recebida agora» com «cotação atual».

## Causa-raiz

O contrato v5 verificava captura nesta execução, identidade bilateral e
validade da Moneyline. Não comparava, porém, a linhagem da quote com execuções
anteriores. A proteção de preço fresco por bookmaker criada antes do fallback
core foi parcialmente contornada quando o feed sem timestamp passou a poder
alimentar pricing nos torneios principais.

## Alteração prospetiva

- Cada evento do feed sem timestamp conserva uma linhagem mínima e persistente
  do par de odds, primeira observação e número de observações.
- Uma quote nova ou alterada continua utilizável.
- Se o mesmo par permanecer invariável em duas ou mais execuções durante seis
  horas ou mais, deixa de ser apresentado como preço atual e passa a
  `OBSERVATION_ONLY`, com razão `repeated_unverified_provider_quote`.
- O motor tenta então as fontes alternativas já existentes. Sem uma quote
  atual verificável, preserva o relatório factual mas não calcula edge nem
  cria PAPER a partir do preço duvidoso.
- A regra também impede que uma quote Challenger repetida além da janela seja
  promovida pela via experimental.

## Preservado

- The Odds API timestamped continua prioritária.
- Uma alteração real no preço reinicia imediatamente a linhagem.
- Não se reescrevem snapshots, relatórios, PAPER ou resultados históricos.
- Não se acrescentam chamadas externas nem se altera o plano RapidAPI.
- Pesos, índice Fenzobot, limiares de edge e estratégia permanecem iguais.

## Contrato e risco residual

O contrato de odds passa a `verified-direct-pre-match-v6`, com semântica
`provider-timestamp-or-bounded-quote-lineage-v3`. Uma cotação pode, de facto,
ficar seis horas sem mudar; como a fonte não fornece prova temporal, o sistema
prefere assinalar a incerteza a declarar essa cotação como atual. O limiar é
configurável por `RAPIDAPI_UNCHANGED_QUOTE_MAX_AGE_SECONDS`.
