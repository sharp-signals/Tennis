# CHANGE-2026-11-19-225 — Governação interna da forma recente

## Problema

No confronto Medvedev–Tiafoe, os resultados recentes favorecem claramente
Medvedev, mas o ajuste estatístico atribui coeficiente zero a esse fator. Os
modificadores de qualidade das vitórias passam então a decidir sozinhos a
família e fazem a forma recente votar por Tiafoe, levando a fair odd de
Medvedev para cerca de 1.90.

## Escopo

- separar a evidência-base da forma recente dos seus modificadores;
- impedir que modificadores invertam uma base recente material;
- garantir um contributo mínimo dos resultados recentes, escolhido por replay;
- preservar simetria A/B, hierarquia entre famílias e independência do mercado;
- preservar o reforço unânime, sem permitir que uma família secundária isolada
  ultrapasse a família principal mais forte;
- selecionar os parâmetros cronologicamente e validar ATP e WTA em separado.

## Critérios de aceitação

- resultados e competitividade recentes constituem a base da família;
- qualidade das vitórias e contexto de nível apenas ajustam a base;
- um modificador contrário não apaga nem inverte uma base material;
- ausência de dados continua sem votar;
- consenso das cinco famílias reforça a magnitude; conflitos mantêm os limites
  estritos da hierarquia;
- `P(A,B) = 1 - P(B,A)` e evidência neutra continua em 50%;
- a alteração melhora ou não degrada materialmente o holdout ATP/WTA;
- o perfil Medvedev–Tiafoe deixa de classificar a forma recente a favor de
  Tiafoe;
- o mercado permanece totalmente fora da construção da fair odd.

## Validação

1. testes unitários da governação interna e da simetria;
2. seleção cronológica dos parâmetros em validação;
3. comparação com v16 no holdout ATP/WTA;
4. replay dirigido ao perfil Medvedev–Tiafoe;
5. checkpoint CI completo antes da entrega.
