# Replay da força estrutural v3 — 3 de novembro de 2026

**Estado:** candidato SHADOW não promovido  
**Âmbito:** ATP e WTA  
**Challenger:** fora da decisão  
**Mercado:** não utilizado  
**Efeito em produção:** nenhum

## Alteração metodológica

A v3 deixou de transformar ranking, trajetória, inatividade e recuperação num
único sinal comprimido. O ranking atual conserva o log-ratio completo, sem
saturação. Os restantes elementos são apresentados à calibração como
modificadores separados, que podem receber peso ou ser anulados.

Exemplo: #10 contra #150 mantém toda a distância estrutural. Se o #10 regressa
de quatro meses de inatividade, essa inatividade aparece separadamente e não
apaga automaticamente a vantagem do ranking.

## Resultado global

| Circuito | Jogos | Log loss referência | Log loss v3 | Ganho v3 | Intervalo 95% | Decisão |
|---|---:|---:|---:|---:|---:|---|
| ATP | 5 143 | 0,626620 | 0,626967 | -0,000346 | [-0,000961; +0,000268] | inconclusivo |
| WTA | 4 815 | 0,622267 | 0,622294 | -0,000026 | [-0,001475; +0,001422] | inconclusivo |

A v3 é estatisticamente indistinguível da referência. Recuperou praticamente
todo o défice da v2, mas não demonstrou melhoria fora da amostra.

## O que a calibração aceitou

| Componente | ATP | WTA | Leitura |
|---|---:|---:|---|
| Ranking atual sem saturação | 0,663846 | 0,631855 | âncora estrutural confirmada |
| Trajetória do ranking | 0 | 0 | não acrescentou valor independente |
| Inatividade bilateral | 0,029014 | 0,113496 | ajuste pequeno; ainda não confirmado no holdout |
| Recuperação de ranking | 0 | 0 | não acrescentou valor independente |

Os coeficientes estão na escala transformada do modelo e não são percentagens.
Servem para comparar a utilização relativa dentro desta equação.

## Segmentos relevantes

- As diferenças extremas deixaram de apresentar a forte degradação da v2.
- Top-20 contra ranking 100+ ficou estatisticamente inconclusivo, sem prejuízo
  demonstrado.
- Inatividade superior a 90 dias mostrou ganho pequeno em ATP (+0,000293) e WTA
  (+0,002294), mas os intervalos de confiança ainda atravessam zero.
- Nenhum segmento demonstrou melhoria ou deterioração estatisticamente clara.

## Decisão

1. Preservar a arquitetura da v3 como base de investigação.
2. Não promover a v3: igualar a referência não é suficiente.
3. Manter ranking atual como âncora estrutural.
4. Não atribuir peso direto a trajetória ou recuperação nesta versão.
5. Manter inatividade como candidato SHADOW até existir prova fora da amostra.
6. Não alterar relatório, índice, fair odd, edge, PAPER ou GREEN.
7. Manter o bot automático parado.

## Próximo passo

Analisar se a força estrutural deve incorporar diferenças por patamar — por
exemplo top-10, top-20, top-50 e fora do top-100 — sem substituir o ranking
contínuo. Esses patamares devem ser testados como interações separadas e apenas
com treino/validação, repetindo depois o holdout cronológico.
