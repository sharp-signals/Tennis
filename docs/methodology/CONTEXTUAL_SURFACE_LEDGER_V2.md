# Base factual de superfície e condições v2

**Data:** 03/11/2026

**Estado:** recolha e auditoria SHADOW; ainda sem equação, peso ou fair odd

## Quatro contextos obrigatórios

1. hard outdoor;
2. hard indoor;
3. terra batida;
4. relva.

Hard sem indicação factual de indoor/outdoor fica por resolver. Não é assumido
como outdoor.

## Informação guardada por jogador e contexto

- carreira: vitórias, derrotas, jogos e percentagem de vitórias;
- época atual;
- época anterior;
- diferença bruta, em pontos percentuais, entre as duas épocas;
- fonte e regra de sobreposição.

A diferença anual é apenas factual. Não se transforma automaticamente em voto:
2–0 numa época não prova evolução sobre 20–10 noutra época.

## Duas origens, duas funções

- O agregado do fornecedor dá carreira e anos para o relatório presente.
- O histórico jogo a jogo reconstrói apenas o que existia antes de cada jogo e
  serve para replay e calibração sem fuga de futuro.

As duas origens nunca são somadas. Quando cobrem as mesmas partidas, uma célula
seleciona uma origem e preserva a proveniência.

## Cobertura local observada

| Circuito | Perfis ricos | Quatro contextos de carreira |
|---|---:|---:|
| ATP | 350 | 255 |
| WTA | 263 | 218 |

Perfis com carreira e pelo menos dez jogos:

| Circuito | Hard outdoor | Hard indoor | Terra | Relva |
|---|---:|---:|---:|---:|
| ATP | 340 | 275 | 330 | 174 |
| WTA | 259 | 223 | 247 | 159 |

Jogadores com pelo menos cinco jogos na época atual e cinco na anterior:

| Circuito | Hard outdoor | Hard indoor | Terra | Relva |
|---|---:|---:|---:|---:|
| ATP | 287 | 95 | 247 | 63 |
| WTA | 232 | 55 | 172 | 60 |

Conclusão: carreira por piso tem cobertura forte. A evolução anual é robusta
para hard outdoor e terra, mas muito mais limitada em indoor e relva. A futura
equação tem de reduzir a confiança de acordo com a amostra.

## Transição de piso

A métrica anterior marcava transição quando, nos últimos 35 dias, o piso
dominante era diferente do piso seguinte e o jogador ainda não tinha jogado no
novo piso. Aplicava depois um ajuste fixo. Essa formulação foi rejeitada.

O conceito continua em aberto. A próxima versão deve estudar separadamente:

- par de transição, por exemplo terra→relva ou hard outdoor→indoor;
- dias desde a mudança;
- número de jogos já disputados no novo contexto;
- desempenho do jogador após mudanças equivalentes;
- prior do circuito quando não existe amostra individual.

Não existe efeito na produção, PAPER, relatório, probabilidade ou fair odd.
