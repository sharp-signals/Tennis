# CHANGE-2026-11-23-235 — Ficha de jogador: forma e contexto de odds

## Objetivo

Completar a ficha estruturada v2 com três blocos factuais, sem alterar a
equação de fair odd:

- qualidade de vitórias e derrotas nos últimos 90 dias;
- evolução anual, geral e por superfície;
- desempenho histórico por faixa de odd observada.

## Alterações

- As vitórias sobre adversários melhor classificados e as derrotas perante
  adversários pior classificados são registadas com amostra, janela e até
  cinco exemplos recentes.
- A evolução por época contém registo geral e separado em hard, clay e grass.
  Cada ponto da série inclui a sua própria avaliação de robustez da amostra.
- As faixas históricas de moneyline preservam número de jogos, vitórias,
  win rate, margem média de games e separação BO3/BO5 quando disponível.
- A geração individual usa exclusivamente a cache de odds já existente; não
  atualiza a fonte ATP pela rede.

## Limites metodológicos

- Todas as métricas novas ficam marcadas como `DESCRIPTIVE_ONLY`.
- Ausência de dados não é transformada em zero.
- Jogos na data de corte ou posteriores não entram nas séries nem na janela
  recente.
- A informação histórica de mercado não influencia a previsão independente.

## Verificação

- Testes unitários cobrem corte temporal, direção das diferenças de ranking,
  séries por piso, amostras por faixa de odds e isolamento do modelo.
