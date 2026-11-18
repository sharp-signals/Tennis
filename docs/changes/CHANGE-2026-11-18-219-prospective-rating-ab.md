# CHANGE-2026-11-18-219 — teste prospetivo A/B de rating cronológico

## Objetivo

Medir, fora da produção, se um rating cronológico independente melhora a
probabilidade e a fair odd face ao modelo contextual congelado.

## Hipóteses congeladas

- ATP: Elo global K=32 integrado na força estrutural, com nova estimação da
  combinação das famílias.
- WTA A: Elo global K=24 integrado na força estrutural.
- WTA B: Elo global K=24 e residual de superfície K=32, com retração após dez
  jogos no contexto exato.

## Garantias metodológicas

- Só entram partidas anteriores ao início do encontro analisado.
- Partidas do mesmo dia não se atualizam entre si.
- O mercado não entra nas previsões.
- As previsões ficam congeladas num ledger separado e append-only.
- O teste não cria relatórios, PAPER, GREEN, notificações ou decisões.
- Nenhuma promoção é autorizada por este change.

## Critério de decisão

O teste só pode sustentar uma alteração futura após liquidação prospetiva e
comparação emparelhada de log loss, Brier, calibração, estabilidade por faixa
de favoritismo e por universo. Um resultado historicamente promissor não é
suficiente.

## Ficheiros

- `src/contextual_chronological_rating.py`
- `src/contextual_rating_ab_v1.py`
- `scripts/build_contextual_rating_ab_v1.py`
- `scripts/run_contextual_shadow_v2.py`
- `scripts/run_fenzobot_contextual_2026_11.py`
- `data/models/contextual-rating-ab-v1.json`
- `data/contextual_rating_ab_observations-v1.jsonl`

## Rollback

Retirar os argumentos `comparison_*` do wrapper operacional. O modelo e o
ledger principais permanecem inalterados.
