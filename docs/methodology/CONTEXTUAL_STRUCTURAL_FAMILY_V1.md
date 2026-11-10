# Força estrutural contextual v1 — decisão de desenvolvimento

**Estado:** congelada para desenvolvimento; ainda sem promoção operacional  
**Mercado:** proibido  
**Âmbito principal:** ATP e WTA

## Sinal quantitativo

A contribuição estrutural parte do log-ratio contínuo do ranking atual:

```text
log(ranking_b / ranking_a)
```

O sinal não satura artificialmente. Uma diferença #10–#200 continua maior do
que #10–#80. A transformação final em probabilidade pertence à calibração e
não a uma tabela arbitrária de pontos.

## Elementos que não criam votos adicionais

- patamares top-10/top-20/top-50;
- pontos ATP/WTA;
- trajetória de ranking;
- melhor ranking histórico;
- recuperação presumida.

Podem ser mostrados como contexto factual, mas os replays não demonstraram
ganho independente depois de conhecido o ranking atual.

## Inatividade

Inatividade é um marcador de representatividade e incerteza. Ainda não existe
prova suficiente para lhe atribuir uma correção direcional fixa. Deve alargar a
incerteza ou gerar reason code, nunca apagar automaticamente uma diferença de
ranking.

## Exemplos

- #40 contra #60: diferença estrutural pequena, sem bónus de patamar;
- #10 contra #150: diferença estrutural forte e integral;
- #10 regressado após quatro meses: vantagem de ranking preservada, com alerta
  separado de inatividade;
- antigo #30 agora #110: tratado como #110 até existir outra família factual
  que demonstre forma atual; o pico antigo não oferece vantagem automática.

## Dados em falta

Ranking em falta não é empate nem 50/50. A família fica indisponível e aumenta
a incerteza global. Pontos poderão ser testados posteriormente como fallback
de cobertura, mas não foram aprovados como substituição nesta versão.

## Evidência

As experiências v1–v5 estão registadas em `docs/analysis/`. A arquitetura v3
removeu a degradação da v2; patamares e pontos não melhoraram o benchmark fora
da amostra. A validação final exigirá cortes temporais repetidos e observação
prospetiva nova.

### Candidato v6

A v6 acrescenta uma leitura semanal da representatividade do ranking atual:
nível típico, persistência no patamar atual e dispersão nas semanas ativas.
Este histórico não substitui o ranking atual nem oferece bónus de reputação;
serve apenas para distinguir um nível sustentado de uma posição instável.

No replay de 2026-11-10, a v6 melhorou ligeiramente log loss em ATP e WTA, mas
sem significância por intervalo de confiança. A calibração melhorou no WTA e
piorou ligeiramente no ATP. Por isso, a v6 permanece SHADOW e `legacy_v0`
continua ativo. Ver
`docs/analysis/CONTEXTUAL_RANKING_V6_REPLAY_2026-11-10.md`.
