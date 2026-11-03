# Replay dos patamares de ranking v4 — 3 de novembro de 2026

**Estado:** hipótese rejeitada  
**Âmbito:** ATP e WTA  
**Challenger:** fora da decisão  
**Mercado:** não utilizado  
**Efeito em produção:** nenhum

## Hipótese

Testar se patamares como top-10, top-20, top-50, top-100 e top-200 acrescentam
informação depois de já estar presente a diferença contínua de ranking.

Patamares adjacentes ficaram neutros. Assim, #40 contra #60 não recebia um
segundo voto. Apenas separações de pelo menos dois patamares criavam contexto
adicional; por exemplo, #15 contra #110.

## Resultado

| Circuito | Jogos | Log loss referência | Log loss v4 | Ganho v4 | Intervalo 95% | Decisão |
|---|---:|---:|---:|---:|---:|---|
| ATP | 5 143 | 0,626620 | 0,627439 | -0,000819 | [-0,001501; -0,000137] | rejeitar |
| WTA | 4 815 | 0,622267 | 0,622205 | +0,000062 | [-0,001486; +0,001610] | inconclusivo |

No ATP, a degradação é pequena mas estatisticamente clara. No WTA não existe
evidência de ganho ou perda.

## Interpretação simples

O ranking contínuo já contém a informação essencial dos patamares. Num jogo
#15 contra #110, o log-ratio já representa uma separação estrutural grande.
Adicionar também um bónus top-20 contra 100+ começa a contar duas vezes a mesma
vantagem, sobretudo no ATP.

Isto não significa que top-10 ou top-20 sejam conceitos irrelevantes para a
leitura humana. Significa apenas que não devem criar um segundo voto matemático
independente dentro da família estrutural quando o ranking contínuo já existe.

## Coeficientes observados

| Componente | ATP | WTA |
|---|---:|---:|
| Ranking contínuo | 0,612367 | 0,559997 |
| Patamar adicional | 0,067003 | 0,094446 |
| Trajetória | 0 | 0 |
| Inatividade | 0,027253 | 0,111811 |
| Recuperação | 0 | 0 |

O patamar recebeu peso no desenvolvimento, mas não generalizou no holdout ATP.
É precisamente o tipo de falso ganho que a separação cronológica pretende
detetar.

## Decisão

1. Não promover a v4.
2. Não acrescentar patamares como segundo voto à força estrutural.
3. Conservar a arquitetura v3 como base de investigação: ranking contínuo sem
   saturação e modificadores separados.
4. Patamares podem ser mostrados como contexto explicativo no futuro, mas não
   alterar a probabilidade sem nova evidência.
5. Não alterar relatório, fair odd, edge, PAPER ou GREEN.
6. Manter o bot automático parado.
