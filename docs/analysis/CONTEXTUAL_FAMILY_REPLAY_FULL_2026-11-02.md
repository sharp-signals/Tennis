# Replay cronológico completo das cinco famílias — 02/11/2026

## Estado

Execução observacional concluída. Não foram ajustados pesos, probabilidades,
fair odds ou edges e não houve alteração de produção.

## Fonte

TennisMyLife atualizada em 02/11/2026, sem chamadas pagas:

| Universo | Linhas da fonte | Ranking bilateral | Alvos do replay |
|---|---:|---:|---:|
| ATP | 27 530 | 98,43% | 26 625 |
| WTA | 25 384 | 97,93% | 24 431 |
| Challenger | 49 108 | 99,44% | 47 070 |

Os lados A/B foram definidos alfabeticamente. Cada data foi avaliada antes de
os resultados desse dia entrarem no histórico. O mercado não foi usado.

## Holdout intocado — acerto direcional

O acerto abaixo mede apenas se a componente apontou para o vencedor. Não é uma
probabilidade nem mede rentabilidade.

| Componente | ATP | WTA | Challenger |
|---|---:|---:|---:|
| Ranking atual | **64,61%** | **64,11%** | **62,06%** |
| Mudança desde último ranking | 50,97% | 53,21% | 51,35% |
| Resultado recente 90d | 60,16% | 60,95% | 57,56% |
| Margem recente de games 90d | **60,39%** | **61,80%** | **58,35%** |
| Força dos vencidos 90d | 56,63% | 58,63% | 54,02% |
| Força dos adversários nas derrotas 90d | 56,75% | 60,10% | 55,07% |
| Registo histórico no piso | **60,86%** | **63,03%** | **60,49%** |
| Forma recente no mesmo piso | 57,66% | 60,70% | 57,85% |
| H2H global, quando existe | 60,05% | 59,16% | 56,34% |
| H2H no mesmo piso, quando existe | 58,79% | 59,30% | 56,55% |
| Pontos de serviço ganhos no piso | 58,14% | 61,74% | 57,57% |
| Pontos de resposta ganhos no piso | 58,38% | 55,64% | 56,66% |
| Hold no piso | 57,68% | 62,12% | 57,30% |
| Break no piso | 58,75% | 55,86% | 55,99% |

## Cobertura das famílias no holdout

| Família | ATP | WTA | Challenger |
|---|---:|---:|---:|
| Forma recente | 84,94% | 83,02% | 80,36% |
| Força estrutural | 98,64% | 99,61% | 99,34% |
| Superfície/condições | 93,65% | 94,31% | 92,94% |
| Matchup/H2H | 44,18% | 42,78% | 20,52% |
| Serviço/resposta | 93,63% | 95,66% | 94,74% |

## Decisões metodológicas provisórias

1. **Ranking atual permanece uma âncora estrutural**, mas não deve ser aplicado
   linearmente nem sozinho. Foi a componente individual mais forte nos três
   universos.
2. **Mudança desde a última observação de ranking é rejeitada na forma atual.**
   Ficou praticamente aleatória e não deve receber peso apenas por parecer
   intuitiva.
3. **Forma recente deve combinar resultado e competitividade.** A margem de
   games foi ligeiramente mais estável do que o simples W/L.
4. **Qualidade das derrotas tem sinal real sobretudo no WTA**, mas qualidade
   adversarial isolada é modesta e deve funcionar dentro da forma, não como
   voto independente.
5. **Registo no piso é forte e estável**, justificando uma família própria de
   superfície/condições.
6. **H2H é contextual e de cobertura limitada.** Não pode ser obrigatório nem
   extrapolado quando não existe. O valor mais baixo nos Challengers reforça a
   prudência específica desse circuito.
7. **Serviço/resposta permanece secundário.** No WTA, hold e pontos de serviço
   mostraram sinal relevante; métricas de resposta isoladas foram mais fracas.
   Como estas métricas estão correlacionadas com ranking, piso e forma, ainda
   não podem ser somadas diretamente.
8. **ATP, WTA e Challenger precisam de calibrações distintas.** A hierarquia
   geral repete-se, mas a intensidade das componentes não é igual.

## Limitação antes da calibração

Grande parte do histórico antigo fornece data de início do torneio, não hora
individual. Excluir toda a mesma data evita leakage, mas pode omitir uma ronda
anterior do mesmo evento. A calibração pode avançar de forma conservadora, mas
esta limitação deve acompanhar os resultados e ser testada novamente nos dados
recentes com data individual.

## Próximo passo autorizado pelos dados

Construir uma equação separada dentro de cada família, por universo, com:

- treino apenas para estimar coeficientes;
- validação para escolher regularização e complexidade;
- holdout ainda intocado para a avaliação final;
- componentes fracas sujeitas a redução até zero;
- valores em falta explicitamente modelados, nunca convertidos em empate;
- zero utilização das odds de mercado.

Só depois serão combinadas as cinco saídas familiares e calibradas para uma
probabilidade e fair odd.
