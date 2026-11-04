# Família contextual de forma recente v1

**CHANGE-ID:** CHANGE-2026-11-02-175  
**Estado:** contrato interno aprovado; ainda sem efeito em produção

## Papel

A forma recente ajustada é uma família principal. Descreve o nível competitivo
demonstrado antes do jogo-alvo e não utiliza odds, mercado ou resultados do
próprio dia.

## Componentes que avançam

1. **Resultados nos 90 dias anteriores.** É o núcleo factual da família.
2. **Competitividade pela margem de games.** Entra na mesma equação calibrada
   dos resultados; não é apresentado nem somado como segundo voto.
3. **Qualidade absoluta das vitórias.** Distingue vitórias contra oposição
   forte de vitórias contra oposição fraca, sem patamares arbitrários.

Os decaimentos confirmados são:

| Componente | ATP | WTA |
|---|---:|---:|
| Resultados | janela uniforme 90d | janela uniforme 90d |
| Competitividade | meia-vida 45d | meia-vida 90d |
| Qualidade das vitórias | meia-vida 60d | meia-vida 60d |

## Qualidade das derrotas

É preservada como diagnóstico, mas não recebe peso na versão v1.

- O modelo livre melhorava quando recompensava jogadores que tinham perdido
  contra oposição forte, mas essa formulação podia transformar derrota em
  crédito positivo autónomo e foi bloqueada.
- Uma penalização apenas por derrotas contra jogadores pior classificados
  recebeu coeficiente zero.
- Uma modulação limitada, que nunca atravessava zero, escolheu intensidade zero
  no ATP. No WTA escolheu 0,25 na validação, mas o holdout foi inconclusivo e a
  componente ajustada recebeu coeficiente zero.

Assim, uma derrota forte não vale pontos e uma derrota fraca pode continuar
visível no relatório/auditoria sem alterar ainda a probabilidade.

## Proteções

- ATP e WTA são calibrados separadamente.
- O jogo-alvo e todos os jogos do mesmo dia ficam fora do histórico anterior.
- Retiradas e conclusões não competitivas não entram.
- Forma no mesmo piso pertence à família de superfície e não é duplicada aqui.
- Dados ausentes alargam incerteza; não produzem voto neutro inventado.
- Challengers permanecem observacionais e não definem esta equação.
- O mercado só poderá entrar depois da probabilidade independente estar
  congelada, exclusivamente para comparação e cálculo posterior de edge.

## Estado operacional

Este contrato autoriza a família a avançar para o replay conjunto das famílias.
Não autoriza sozinho produção, PAPER, fair odds, relatórios nem reativação do
bot automático.
