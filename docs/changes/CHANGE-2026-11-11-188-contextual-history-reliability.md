# CHANGE-2026-11-11-188 — Hierarquia competitiva e fiabilidade histórica

## Objetivo

Impedir que uma amostra mínima no circuito principal ou uma boa sequência em
Challenger seja tratada como evidência equivalente a forma ATP/WTA no nível do
jogo analisado, sem perder partidas já existentes no histórico.

## Causa confirmada

No caso de controlo Alexander Shevchenko–Casper Ruud, o modelo anterior via
apenas uma partida ATP recente de Shevchenko na família de forma e ignorava a
atividade Challenger para determinar continuidade competitiva. Isso produzia
simultaneamente:

- uma vantagem recente excessiva baseada numa única vitória ATP;
- um contexto de regresso incompleto, porque a atividade Challenger não era
  considerada na contagem;
- fair odd de Ruud próxima de 1,81, incompatível com a restante evidência.

## Alteração metodológica

- carregar o histórico ATP principal e Challenger numa única base factual;
- conservar todas as partidas para atividade, ranking e forma cronológica;
- separar forma recente do circuito principal e forma Challenger;
- distinguir no circuito principal torneios do nível do alvo ou superior de
  torneios ATP/WTA inferiores;
- exigir duas partidas principais para confiança total no sinal agregado;
- exigir quatro partidas nas subdivisões e no Challenger;
- usar a qualidade do adversário como ponte comum entre níveis;
- medir ainda o crédito de vitórias pela hierarquia objetiva de pontos da
  categoria: Challenger genérico 100, ATP/WTA 250, 500, Masters/1000 e Grand
  Slam 2000; uma derrota num evento superior não recebe penalização adicional;
- calcular esse crédito sobre todas as partidas dos últimos 90 dias, com
  decaimento temporal, para que uma campanha profunda conte pelas várias
  vitórias obtidas sem ser diluída por vitórias fáceis adicionais;
- manter piso, serviço e H2H principais sem contaminação automática por
  Challenger;
- não usar mercado, odds ou edge na previsão.

## Validação

- replay cronológico: 26.681 partidas ATP e 24.493 WTA;
- holdout ATP: 5.269 partidas;
- a diferença global de log-loss face ao modelo anterior foi -0,000957 no ATP,
  com intervalo de confiança `[-0,002457; 0,000543]`, que inclui zero; a mudança é, portanto,
  metodológica e de segurança, não uma alegação de melhoria estatística global;
- caso de controlo: 76.973 partidas históricas carregadas; Shevchenko com 4
  partidas recentes identificadas (1 ATP + 3 Challenger), 52 partidas de piso
  e 51 com serviço;
- antes do crédito por categoria, a fair odd do caso de controlo passou para
  aproximadamente 1,53 em Ruud; com a hierarquia completa passou para 1,46 em
  Ruud e 3,19 em Shevchenko;
- no mesmo controlo, a forma recente deixou de favorecer Shevchenko em 0,58
  p.p. e passou a favorecer Ruud em 4,16 p.p.;
- o lançamento permanece `PROSPECTIVE_SHADOW_ONLY`, sem PAPER/GREEN.

## Critérios de aceitação

1. Challenger é recolhido, mas não recebe peso idêntico ao circuito principal.
2. Uma única partida ATP não recebe confiança total.
3. O nível ATP/WTA do torneio é preservado no cálculo da forma.
4. A atividade Challenger impede falsos períodos de inatividade.
5. O contrato continua independente do mercado e auditável.
6. Histórico anterior permanece imutável e aceite como geração histórica.
