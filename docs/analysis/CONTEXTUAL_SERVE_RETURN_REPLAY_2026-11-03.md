# Serviço e resposta — replay cronológico de 2026-11-03

**CHANGE-ID:** CHANGE-2026-11-02-175  
**Estado:** família SHADOW secundária; sem produção, fair odd ou PAPER

## Objetivo

Medir se serviço e resposta acrescentam informação futura sem repetir ranking,
forma recente ou superfície. Foram usados apenas totais anteriores ao jogo;
percentagens nunca foram calculadas pela média simples de partidas.

## Estruturas comparadas

1. pontos de serviço e resposta no piso, sem shrinkage;
2. os mesmos pontos reduzidos conforme a amostra;
3. hold e break reduzidos conforme a amostra;
4. baseline reduzida de pontos mais desvio recente de 90 dias.

Pontos e hold/break foram comparados como alternativas, nunca somados.

## Resultado isolado no holdout

| Circuito | Estrutura | Cobertura | Acerto | Log loss | Baseline |
|---|---|---:|---:|---:|---:|
| ATP | pontos + desvio recente | 92,36% | 62,80% | 0,642800 | 0,692512 |
| WTA | pontos no piso, reduzidos | 94,21% | 63,75% | 0,639577 | 0,691536 |

No ATP, a validação escolheu a baseline com desvio recente e o ganho também se
manteve no holdout. No WTA, o desvio recente ganhou marginalmente na validação,
mas perdeu `0,000036` de log loss face à baseline simples no holdout. Foi por
isso rejeitado no WTA.

## Valor depois das famílias principais

O teste seguinte deu ao modelo forma recente ajustada, ranking estrutural e
superfície exata antes de acrescentar serviço/resposta.

| Circuito | Log loss base | Com serviço/resposta | Ganho | Acerto final |
|---|---:|---:|---:|---:|
| ATP | 0,617938 | 0,616440 | +0,001498 | 66,11% |
| WTA | 0,615032 | 0,610970 | +0,004062 | 66,04% |

O ganho é real nos dois circuitos, mas muito inferior ao desempenho isolado da
família. Isto confirma que grande parte da informação já estava refletida nas
famílias principais e que serviço/resposta deve permanecer secundário.

## Contrato fechado

- baseline: pontos de serviço ganhos e pontos de resposta ganhos no piso;
- amostra reduzida com prior de 1 000 pontos;
- ATP: desvio recente de 90 dias permitido, reduzido com prior de 500 pontos;
- WTA: desvio recente apenas informativo;
- hold e break apenas informativos, pois são reflexos downstream dos pontos;
- componentes alinhadas podem reforçar-se dentro da equação da família;
- componentes em conflito compensam-se, não são dois votos narrativos;
- a família nunca cria entrada sozinha nem contraria as famílias principais.

## Fonte e cobertura

TennisMyLife, 2017–2026, com estatísticas ponto a ponto e cache local de última
cópia válida. Challenger não decidiu a equação.

## Artefactos

- `data/validation/contextual-serve-return-equation-comparison-2026-11-03.json`;
- `data/models/contextual-serve-return-family-v1.json`.
