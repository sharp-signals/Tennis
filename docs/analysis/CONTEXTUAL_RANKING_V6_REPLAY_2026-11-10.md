# Ranking contextual v6 — replay cronológico

**Data:** 2026-11-10  
**Estado:** candidato SHADOW; não promovido  
**Mercado:** ausente da previsão  
**Âmbito de decisão:** ATP e WTA principais

## Hipótese testada

A versão v6 traduz os três problemas de ranking definidos pelo utilizador e
pelo Hugo sem transformar reputação passada num voto autónomo:

1. **distância atual:** diferenças próximas entram numa zona neutra e as
   separações competitivamente materiais permanecem contínuas;
2. **representatividade:** o ranking atual ganha confiança quando é compatível
   com o nível típico e estável observado nas semanas ativas anteriores;
3. **modo de chegada:** a persistência e dispersão semanal distinguem um nível
   sustentado de uma posição recente e instável.

Os pontos são uma segunda leitura dependente do nível atual. Trajetória,
regresso e inatividade continuam disponíveis para teste dentro da mesma
família, sem votos duplicados. Não existe no dataset atual uma decomposição
fiável dos pontos por torneio; por isso, a v6 não inventa uma métrica de
concentração.

## Dados e proteção cronológica

- ATP: 27 583 jogos; 98,43% de cobertura bilateral de ranking;
- WTA: 25 444 jogos; 97,94% de cobertura bilateral de ranking;
- uma observação de ranking por semana ativa e por jogador;
- apenas informação anterior ao jogo avaliado;
- comparação no mesmo holdout e nos mesmos alvos do perfil legado;
- sem preço de mercado, PAPER, GREEN, relatório público ou efeito operacional.

O “ranking típico” é a mediana geométrica das observações semanais disponíveis
nos 365/730 dias anteriores. É histórico observado em semanas com jogos, não
uma série oficial completa de rankings semanais; esta limitação fica explícita.

## Resultado agregado

| Universo | N | Log loss legado | Log loss v6 | Ganho v6 | Brier legado | Brier v6 | Accuracy legado | Accuracy v6 | ECE legado | ECE v6 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ATP | 5 192 | 0,626802 | 0,626640 | +0,000162 | 0,218736 | 0,218667 | 64,56% | 64,64% | 0,013912 | 0,017354 |
| WTA | 4 875 | 0,622489 | 0,621968 | +0,000521 | 0,216781 | 0,216555 | 64,27% | 64,47% | 0,021805 | 0,013246 |

Os dois ganhos de log loss são positivos, mas os intervalos de confiança a
95% atravessam zero. Logo, o veredicto é **INCONCLUSIVO** nos dois universos.
No WTA, a calibração também melhora; no ATP, o ECE piora ligeiramente e exige
cautela adicional.

## Segmentos

Nenhum segmento — diferenças próximas, moderadas, grandes ou extremas;
representatividade baixa, média, alta ou indisponível; inatividade; trajetória;
regresso — demonstrou ganho conclusivo. A zona neutra ficou essencialmente
empatada com o legado:

- ATP, rank gap < 1,5x: ganho -0,000024, N=1 228;
- WTA, rank gap < 1,5x: ganho -0,000625, N=1 085.

Os sinais de trajetória e regresso receberam coeficiente zero na solução
regularizada. Isto significa que, neste replay, não acrescentaram poder
preditivo independente depois do nível atual e dos pontos. Não significa que
tenham sido apagados do contrato factual.

## Decisão

A v6 fica registada como candidata SHADOW e disponível para observação
prospetiva, mas **não substitui `legacy_v0`**, não altera a equação ativa e não
entra na fair odd operacional. Uma promoção futura exige ganho repetido em
cortes temporais e ausência de degradação material de calibração, em especial
no ATP.

Artefacto completo:
`data/validation/contextual-family-equation-comparison-v6.json`.
