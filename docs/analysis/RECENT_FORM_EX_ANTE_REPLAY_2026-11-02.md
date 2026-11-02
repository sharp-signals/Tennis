# Replay ex ante da forma recente — 02/11/2026

**CHANGE-ID:** CHANGE-2026-11-02-175

**Estado:** observacional; não integrado no motor

## Pergunta

Antes de escolher pesos, que componentes factuais da forma dos 90 dias
anteriores mostraram direção útil fora da amostra?

## Método

- Fonte operacional TennisMyLife: dez épocas ATP, WTA e Challenger.
- Zero RapidAPI, zero odds e zero mercado.
- Para cada partida, só foram usadas partidas de datas anteriores.
- Quando a fonte só tem precisão diária, todo o dia do jogo fica excluído do
  histórico anterior; partidas do mesmo dia nunca se veem entre si.
- Retiradas, walkovers e outros finais não normais não entram como resultado
  competitivo normal.
- Divisão cronológica por volume, mantendo cada data inteira num único bloco:
  aproximadamente 60% treino/exploração, 20% validação para escolher o
  decaimento e 20% holdout intocado.
- Candidatos de decaimento: uniforme em 90 dias e meias-vidas de 21, 30, 45,
  60 e 90 dias.
- Empates contam como meio acerto. A métrica é apenas direção histórica, não
  probabilidade nem fair odd.

## Amostra

| Universo | Alvos | Treino | Validação | Holdout |
|---|---:|---:|---:|---:|
| ATP | 26 622 | 16 002 | 5 410 | 5 210 |
| WTA | 24 431 | 14 666 | 4 931 | 4 834 |
| Challenger | 47 067 | 28 375 | 9 399 | 9 293 |

## Resultados no holdout

| Universo | Sinal | Decaimento escolhido na validação | Cobertura | Direção correta |
|---|---|---|---:|---:|
| ATP | balanço de resultados | uniforme 90d | 84,9% | 60,18% |
| ATP | qualidade simplista por surpresa de ranking | 21d | 84,9% | 43,51% |
| ATP | balanço no mesmo piso | 30d | 69,6% | 57,40% |
| WTA | balanço de resultados | uniforme 90d | 83,0% | 60,95% |
| WTA | qualidade simplista por surpresa de ranking | 21d | 82,9% | 47,48% |
| WTA | balanço no mesmo piso | 45d | 64,8% | 61,32% |
| Challenger | balanço de resultados | 90d | 80,4% | 57,72% |
| Challenger | qualidade simplista por surpresa de ranking | 21d | 80,2% | 49,19% |
| Challenger | balanço no mesmo piso | 90d | 65,3% | 58,04% |

## Decisões

1. **A janela de 90 dias fica suportada.** Descontar agressivamente partidas
   antigas não melhorou de forma consistente. ATP e WTA preferiram ponderação
   uniforme; Challenger preferiu uma meia-vida longa de 90 dias.
2. **Forma no mesmo piso acrescenta sinal**, sobretudo no WTA. Continua a ser
   uma componente da família de forma, não um segundo voto independente.
3. **A definição simplista de qualidade é rejeitada.** Somar vitórias-surpresa
   e subtrair derrotas-surpresa por razão relativa de ranking foi
   antipreditivo no ATP e WTA e praticamente neutro nos Challengers.
4. O resultado confirma que “qualidade das vitórias/derrotas” não pode ser
   reduzida a ter vencido alguém melhor classificado. A próxima formulação deve
   considerar força absoluta do adversário à data, expectativa estrutural,
   competitividade do resultado, repetição do padrão e contexto do circuito.
5. Nenhum destes números altera pesos, índice, probabilidade, fair odd, edge,
   PAPER ou relatórios.

## Limitação temporal da fonte

Nas épocas antigas, `tourney_date` representa frequentemente o início do
torneio; em 2026 a fonte oferece maior granularidade diária. A política de
excluir toda a mesma data é conservadora e evita leakage, mas pode omitir no
replay antigo resultados de rondas anteriores do mesmo evento. Antes de uma
calibração final deve ser procurada data individual de partida; enquanto não
existir, a aproximação não pode ser escondida.

## Próximo ensaio

Construir `qualidade_adversarial_v2` sem integração no motor:

- força absoluta do adversário à data;
- vitória/derrota relativamente à expectativa estrutural independente do
  mercado;
- margem competitiva em sets/games;
- repetição de vitórias fortes e derrotas fracas;
- transferência explícita ATP ↔ Challenger;
- replay e holdout separados para ATP, WTA e Challenger.
