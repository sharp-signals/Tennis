# CHANGE-2026-11-14-208 — referência contextual de handicap

## Objetivo

Não ocultar a referência de odd de uma linha de handicap apenas porque a
amostra relevante ainda é inferior a 30 jogos.

## Alteração

- mantém o limiar de 30 jogos para declarar a referência como pronta;
- quando existem jogos tanto em vitórias como em derrotas, calcula mesmo com
  amostra curta:
  - cobertura contextual central;
  - cobertura contextual conservadora;
  - preço mínimo central;
  - preço mínimo conservador;
- identifica explicitamente a referência de amostra curta como indicativa e
  não como preço de mercado validado;
- continua sem produzir referência quando falta por completo um dos estados
  necessários (vitórias ou derrotas).

O cálculo usa a probabilidade independente do Fenzobot. O limite inferior do
intervalo de probabilidade do jogador é usado na leitura conservadora. O
mercado não entra na construção destas referências.

## Verificação

- `pytest tests/test_contextual_shadow_handicap_v2.py tests/test_contextual_shadow_report_v2.py -q`
- `pytest tests/test_contextual_shadow_runtime_v2.py tests/test_contextual_shadow_market_v2.py tests/test_fenzobot_contextual_release.py -q`

