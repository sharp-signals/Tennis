# CHANGE-2026-11-19-226 — Governação do consenso por circuito

## Problema

A v17 limitava cada família secundária à contribuição da família principal
mais forte, mesmo quando as duas famílias principais e todas as famílias
secundárias apontavam para o mesmo jogador. No controlo Medvedev–Tiafoe, a
força estrutural realizada era apenas `0.063501`; superfície, H2H e
serviço/resposta eram por isso reduzidos artificialmente a esse mesmo valor,
apesar das contribuições ajustadas de `0.240779`, `0.170123` e `0.222535`.
O consenso de cinco famílias acabava comprimido para 56.9% e fair odd 1.76.

O primeiro candidato sem essa compressão melhorou ligeiramente o ATP, mas
piorou de forma estatisticamente significativa o WTA. Uma política igual para
os dois circuitos não é, portanto, autorizada pela evidência.

## Escopo

- preservar no ATP as contribuições ajustadas quando ambas as famílias
  principais estão ativas, alinhadas e todas as famílias disponíveis concordam;
- manter os limites rígidos da hierarquia em qualquer conflito e proibir uma
  previsão assente apenas em famílias secundárias;
- manter no WTA a política v17, porque o candidato foi rejeitado no holdout;
- calibrar novamente a incerteza por circuito sem introduzir o mercado;
- exportar primeiro o novo release e só depois congelar o A/B sobre o mesmo
  fingerprint;
- preservar o estado `SHADOW_ONLY`, sem PAPER, GREEN ou promoção automática.

Esta alteração sucede à regra absoluta do CHANGE-2026-11-19-224 apenas no caso
estreito de consenso unânime ATP. Em conflito, a proibição de domínio
secundário permanece integralmente em vigor.

## Critérios de aceitação

- ATP: consenso unânime com ambas as famílias principais ativas conserva as
  contribuições estatísticas ajustadas;
- ATP: conflito entre famílias continua sujeito aos limites rígidos;
- ATP: o controlo Medvedev–Tiafoe deixa de ser comprimido pela família principal
  mais fraca, sem ajuste manual por jogador ou encontro;
- WTA: a previsão final reproduz exatamente a v17 quando o candidato é
  rejeitado;
- ausência de dados nunca vota e evidência apenas secundária não cria previsão;
- `P(A,B) = 1 - P(B,A)` e evidência neutra permanece 50%/50%;
- fair odds continuam independentes do mercado;
- release e A/B partilham exatamente o mesmo fingerprint;
- replay cronológico, testes direcionados e full CI final ficam registados.

## Evidência e decisão

- ATP, candidato v18 vs v17: ganho de log-loss `+0.000087`, IC95%
  `[-0.000296, +0.000470]`; não rejeitado e estimativa pontual não negativa;
- WTA, candidato sem limite: rejeitado no holdout; fallback v17 aplicado;
- WTA após fallback: ganho/perda `0.000000`, IC95% `[0.000000, 0.000000]`;
- controlo Medvedev–Tiafoe com as contribuições congeladas da execução
  `44625234479`: aproximadamente 67.3% e fair odd 1.49, contra 56.9% e 1.76
  sob a compressão v17.

## Validação

1. replay cronológico local ATP e WTA sem chamadas à RapidAPI;
2. calibração independente dos intervalos de probabilidade;
3. regressões de consenso, conflito, ausência, simetria e neutralidade;
4. testes de runtime, relatório, publicação, release e A/B;
5. full CI Level 3 antes do merge.
