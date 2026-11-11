# CHANGE-2026-11-11-189 — contexto competitivo na forma e superfície

## Problema

Taxas semelhantes de forma ou de vitórias numa superfície podiam esconder
níveis competitivos muito diferentes. Uma boa sequência em Challenger não
deve ser equiparada a uma meia-final de Masters 1000.

## Alteração

- A forma recente mantém os sinais por nível já existentes e passa a auditar
  explicitamente uma descida recente do circuito principal para Challenger.
- A família de superfície mantém as percentagens ATP/WTA anteriores e acrescenta
  crédito de vitórias ponderado pela categoria: Challenger 100, ATP/WTA 250,
  500, Masters/WTA 1000 e Grand Slam/Finals 2000.
- Participar num torneio superior não dá crédito; apenas vitórias contam.
- A nova geração continua `SHADOW_ONLY`, independente do mercado e sem PAPER,
  GREEN ou notificações operacionais.

## Validação cronológica

- Replay: 26 681 jogos ATP e 24 493 WTA.
- Ganho de log-loss face à v7:
  - ATP: `-0.000413`, IC95% `[-0.001298, 0.000471]` — inconclusivo.
  - WTA: `+0.000477`, IC95% `[-0.000004, 0.000959]` — inconclusivo.
- O sinal autónomo de descida de circuito recebeu coeficiente zero no ATP e
  não é forçado; permanece auditável.
- Controlo Ruud–Shevchenko: Ruud 75,39%, fair odd central 1,33, sem usar o
  preço de mercado. O segmento histórico top-20 contra ranking 40–100 teve
  74,22% de vitórias em 834 casos.

## Estado

Experimental e não promovido. A melhoria é metodologicamente fundamentada,
mas o ganho global continua estatisticamente inconclusivo; deve acumular
observações prospetivas antes de qualquer utilização operacional.
