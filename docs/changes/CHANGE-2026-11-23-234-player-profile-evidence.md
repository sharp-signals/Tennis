# CHANGE-2026-11-23-234 — evidência alargada das fichas de jogador

## Objetivo

Enriquecer a ficha v2 apenas com informação já disponível no histórico
canónico, preservando a separação entre apresentação factual e pricing.

## Evidência adicionada

- ranking atual e pontos atuais;
- ranking típico nos últimos 365 e 730 dias;
- melhor ranking observado e persistência no patamar atual;
- contexto factual de regresso após hiato;
- evolução anual com ranking inicial, final, melhor e típico;
- registos cumulativos contra Top 3, Top 10, Top 20, Top 50 e Top 100;
- registo exclusivo contra adversários fora do Top 100;
- registos por Grand Slam, Masters/WTA 1000, Finals, 500, 250,
  circuito principal sem categoria detalhada, WTA 125 e Challenger;
- registos BO3 e BO5;
- carreira indoor e outdoor.

Cada métrica conserva a amostra, proveniência e avaliação de robustez. As
categorias sem observações ficam `NOT_APPLICABLE`, nunca a zero.

## Papel no modelo

Só os inputs de ranking que correspondem ao contrato estrutural existente são
marcados `MODEL_ACTIVE`. Todos os cortes analíticos novos permanecem
`DESCRIPTIVE_ONLY`; não alteram probabilidades nem fair odds.

## Fora deste bloco

- qualidade recente detalhada das vitórias e derrotas;
- histórico por faixas de odds;
- ficha visual e comparador;
- geração em lote ATP/WTA;
- qualquer promoção de novos fatores para o modelo.
