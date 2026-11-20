# CHANGE-2026-11-20-228 — replay de categoria, ronda e adversário

**Nível:** 3 — auditoria da metodologia probabilística

**Estado:** experiência em implementação
**Âmbito:** SHADOW contextual ATP/WTA; sem alteração do pricing operacional

## Hipótese

O crédito atual dá o mesmo valor de categoria a todas as vitórias do mesmo
torneio. Pretende-se verificar se a previsão fora da amostra melhora quando o
crédito também representa a fase alcançada e, numa variante única, a força do
adversário vencido.

## Baseline e candidatas

1. **Baseline:** categoria do torneio; qualidade do adversário permanece num
   fator separado.
2. **Categoria × ronda:** a vitória progride de `1/7` em R128 até `7/7` na
   final; round-robin vale `1/3`, correspondente a uma das três partidas do
   grupo. A qualidade do adversário permanece separada.
3. **Categoria × ronda × adversário:** termo conjunto contínuo. Esta variante
   remove simultaneamente o crédito de categoria e a qualidade do adversário
   separados, impedindo dupla contagem.

## Protocolo

- replay cronológico ex ante, separado em ATP e WTA;
- escolha de regularização apenas na validação;
- avaliação final no holdout;
- comparação da família e do pricing integrado com a hierarquia v18 congelada;
- mercado, odds e resultados futuros proibidos como inputs;
- dados ausentes permanecem ausentes e são contabilizados na cobertura.

## Critério de decisão

Uma candidata só pode avançar se o ganho emparelhado for suportado tanto na
família como na previsão integrada, em ATP e WTA. Resultado inconclusivo ou
rejeitado preserva integralmente a fórmula atual. Mesmo um resultado suportado
não autoriza promoção automática: exige decisão e CHANGE separado.

## Invariantes

- nenhuma fair odd ou snapshot existente é reescrito;
- SHADOW, PAPER e REAL permanecem isolados;
- `production_effect=false` e `promotion_authorized=false`;
- esta alteração acrescenta apenas o replay, testes e o ranking factual do
  adversário ao ledger de auditoria.

## Resultado cronológico

A avaliação usou 26.703 jogos ATP e 24.502 WTA. A candidata
`categoria × ronda` melhorou a família isolada nos dois universos, mas não o
pricing completo com a hierarquia v18 congelada:

- ATP: ganho de log loss da família `+0,004351`; ganho integrado `-0,001160`
  com intervalo de 95% `[-0,002980; +0,000660]`;
- WTA: ganho de log loss da família `+0,002484`; ganho integrado `-0,000738`
  com intervalo de 95% `[-0,001923; +0,000448]`.

A candidata conjunta `categoria × ronda × adversário` também ficou
inconclusiva e piorou pontualmente o log loss integrado em ambos os circuitos.

**Decisão:** não promover nenhuma candidata e preservar integralmente a fair
odd atual. O resultado prova que a fase acrescenta informação à família, mas
não prova que essa informação melhora a probabilidade final sob a hierarquia
atual. Qualquer trabalho seguinte deve estudar a integração/hierarquia numa
experiência separada, sem reutilizar estes mesmos resultados para escolher
novos thresholds e voltar a avaliar no mesmo holdout.
