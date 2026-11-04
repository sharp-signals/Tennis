# Auditoria segmentada da força estrutural v2 — 3 de novembro de 2026

**Estado:** auditoria cronológica read-only concluída  
**Âmbito:** ATP e WTA  
**Challenger:** não incluído na decisão  
**Mercado:** não utilizado  
**Efeito em produção:** nenhum

## Pergunta

A v2 aproximou-se da referência histórica, mas continuou ligeiramente pior.
Esta auditoria identifica onde ocorre a perda antes de se desenhar uma v3.
Todos os segmentos usam apenas informação disponível antes do jogo. Os modelos
foram comparados nos mesmos alvos do holdout.

Um ganho positivo significa que a v2 teve menor log loss. O intervalo de 95%
mede a incerteza da diferença emparelhada; se atravessar zero, o resultado é
inconclusivo.

## ATP

| Segmento | Jogos | Ganho v2 | Intervalo 95% | Leitura |
|---|---:|---:|---:|---|
| Global | 5 143 | -0,002647 | [-0,004532; -0,000761] | referência melhor |
| Diferença próxima, abaixo de 1,5x | 1 216 | -0,000572 | [-0,001659; +0,000515] | inconclusivo |
| Diferença moderada, 1,5x–3x | 1 646 | +0,000827 | [-0,001235; +0,002889] | inconclusivo |
| Diferença grande, 3x–8x | 1 431 | +0,000195 | [-0,002278; +0,002668] | inconclusivo |
| Diferença extrema, 8x ou mais | 850 | -0,017125 | [-0,026789; -0,007461] | referência melhor |
| Top-20 contra ranking 100+ | 337 | -0,020569 | [-0,035928; -0,005210] | referência melhor |
| Ranking em movimento material | 4 217 | -0,002725 | [-0,004797; -0,000653] | referência melhor |
| Regresso de ranking suportado | 2 643 | -0,001444 | [-0,004023; +0,001136] | inconclusivo |
| Inatividade superior a 90 dias | 623 | -0,001971 | [-0,007708; +0,003766] | inconclusivo |

## WTA

| Segmento | Jogos | Ganho v2 | Intervalo 95% | Leitura |
|---|---:|---:|---:|---|
| Global | 4 815 | -0,003345 | [-0,005268; -0,001421] | referência melhor |
| Diferença próxima, abaixo de 1,5x | 1 070 | -0,000936 | [-0,001902; +0,000029] | inconclusivo |
| Diferença moderada, 1,5x–3x | 1 668 | -0,000731 | [-0,002405; +0,000942] | inconclusivo |
| Diferença grande, 3x–8x | 1 304 | +0,001669 | [-0,000634; +0,003972] | inconclusivo |
| Diferença extrema, 8x ou mais | 773 | -0,020774 | [-0,031357; -0,010192] | referência melhor |
| Top-20 contra ranking 100+ | 288 | -0,018618 | [-0,038460; +0,001224] | inconclusivo |
| Ranking em movimento material | 4 039 | -0,003321 | [-0,005466; -0,001175] | referência melhor |
| Regresso de ranking suportado | 2 449 | -0,002330 | [-0,004629; -0,000031] | referência melhor |
| Inatividade superior a 90 dias | 699 | -0,003191 | [-0,009175; +0,002793] | inconclusivo |

## Conclusões

1. A v2 não falha principalmente nas diferenças próximas ou moderadas. Nesses
   segmentos não existe diferença estatística clara.
2. A saturação da curva em rácios extremos elimina informação útil. A futura
   equação não deve tratar 8x, 12x e 20x como a mesma distância estrutural.
3. Trajetória/inatividade não devem multiplicar e reduzir automaticamente o
   nível atual. O desconto aplicado pela v2 perde informação nos dois circuitos.
4. O reconhecimento de recuperação não demonstrou ganho; no WTA existe sinal de
   prejuízo. Não deve ser incorporado diretamente no nível base.
5. Não há evidência para parâmetros diferentes ATP/WTA nesta fase: a causa
   principal repete-se nos dois circuitos.

## Contrato recomendado para a v3

- conservar o log-ratio contínuo do ranking atual, sem saturação prematura;
- manter o nível atual como âncora estrutural;
- expor trajetória, inatividade e recuperação como modificadores separados;
- permitir que treino/validação aceitem ou anulem cada modificador;
- não escolher parâmetros no holdout;
- só promover se superar a referência global sem degradar materialmente os
  segmentos extremos;
- manter Challenger fora desta decisão e numa avaliação observacional própria.

## Estado operacional

Nenhuma equação foi promovida. Relatório, índice, fair odd, edge, PAPER e GREEN
permanecem inalterados. O bot automático continua parado.
