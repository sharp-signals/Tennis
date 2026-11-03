# Replay cronológico do H2H contextual — 2026-11-03

**CHANGE-ID:** CHANGE-2026-11-02-175  
**Estado:** auditoria read-only; sem efeito no índice, fair odd, relatório ou PAPER

## Pergunta

O confronto direto deve contribuir para a família de matchup? Em particular,
um H2H no mesmo contexto de piso acrescenta informação estável ao H2H global?

O replay usa apenas encontros anteriores ao alvo, adiciona os resultados de
cada dia só depois de avaliar todos os jogos desse dia e não consulta odds.
Validação e holdout são cronológicos. Zero confrontos confirmados é
`OBSERVED_NONE`: pesquisa concluída, cobertura factual e impacto nulo.

## Holdout

| Circuito | H2H anterior | Alvos | Acerto do líder global | Acerto no mesmo contexto | Acerto recente no mesmo contexto |
|---|---:|---:|---:|---:|---:|
| ATP | 1 | 807 | 58,2% | 57,4% (265) | 58,3% (187) |
| ATP | 2–3 | 557 | 62,3% (387 sinais) | 57,6% (236) | 57,3% (185) |
| ATP | 4+ | 258 | 66,0% (215 sinais) | 65,5% (142) | 63,4% (112) |
| WTA | 1 | 883 | 57,1% | 57,3% (377) | 56,2% (242) |
| WTA | 2–3 | 680 | 62,3% (483 sinais) | 59,3% (364) | 61,4% (246) |
| WTA | 4+ | 347 | 60,8% (283 sinais) | 63,3% (226) | 58,3% (163) |

Os parênteses indicam a quantidade de sinais não empatados quando ela difere
do número de alvos.

## Decisão metodológica

1. **Um único H2H não pode ser um voto material.** O acerto de 57–58% é
   compatível com um modificador muito pequeno, sujeito a forte shrinkage.
2. **Repetição interessa.** As bandas 2–3 e 4+ preservam sinal no holdout,
   embora a intensidade não seja monotónica em ambos os circuitos.
3. **Mesmo piso não é uma segunda confirmação independente.** Não melhora de
   forma estável o líder global e não será somado como outro peso.
4. **Contexto é modificador, não voto.** Recência, piso, circuito, formato e
   evolução dos jogadores devem ajustar a aplicabilidade do mesmo histórico.
5. **A família continuará limitada.** H2H nunca poderá liderar sozinho a
   probabilidade nem compensar forma recente forte em sentido contrário.

## Comparação das equações candidatas

Foram comparados candidatos limitados e monotónicos:

- balanço global com shrinkage;
- modificador pequeno pelo mesmo contexto;
- modificador pequeno pelo mesmo contexto nos 730 dias anteriores.

| Circuito | Candidato | Log loss validação | Log loss holdout | Baseline holdout |
|---|---|---:|---:|---:|
| ATP | global shrunk | 0,674268 | 0,673667 | 0,692329 |
| ATP | mesmo contexto | 0,674276 | 0,673579 | 0,692329 |
| ATP | recente + contexto | 0,674166 | 0,673562 | 0,692329 |
| WTA | global shrunk | 0,683980 | 0,678776 | 0,693167 |
| WTA | mesmo contexto | 0,684083 | 0,678799 | 0,693167 |
| WTA | recente + contexto | 0,684005 | 0,678809 | 0,693167 |

No ATP, a melhoria do candidato contextual sobre o global foi apenas
`0,000102` na validação e `0,000105` no holdout. No WTA, o global foi o melhor.
Esta diferença é demasiado pequena e inconsistente para justificar maior
complexidade.

## Equação escolhida para SHADOW

Foi escolhida a estrutura global com prior simétrico de dois jogos:

`(vitórias_A - vitórias_B) / (total + 2)`

A escolha privilegia estabilidade entre circuitos e impede que as mesmas
partidas sejam contabilizadas uma vez no H2H global e novamente no H2H de
piso. Contexto e recência continuam visíveis, mas não votam automaticamente.

Esta é apenas uma família SHADOW isolada. A equação não está autorizada a
alterar índice, probabilidade, fair odd, relatório, PAPER ou produção.

## Artefacto

`data/validation/contextual-h2h-audit-2026-11-03.json`

`data/validation/contextual-h2h-equation-comparison-2026-11-03.json`
