# Replay cronológico das cinco famílias — v0

## Objetivo

Construir uma matriz ex ante que permita medir cobertura e direção factual das
cinco famílias antes de escolher pesos ou uma função de probabilidade.

## Proteções contra leakage

- os lados A/B são definidos por ordem alfabética normalizada, nunca por
  vencedor/perdedor;
- cada data completa é avaliada antes de qualquer resultado dessa data entrar
  no histórico;
- a data individual da partida tem prioridade; a data inicial do torneio só é
  usada como fallback explícito quando a fonte não contém data do encontro;
- retiradas, walkovers e conclusões não competitivas são excluídas;
- todas as observações usam apenas datas anteriores ao alvo;
- treino, validação e holdout são separados cronologicamente, mantendo uma
  data inteira numa única partição;
- odds, mercado, RapidAPI e resultados PAPER não entram nas features.

## Conteúdo inicial

O replay preserva componentes crus, agrupados sem soma:

- **forma recente:** balanço de resultados, margem de games e força dos
  adversários nas vitórias/derrotas dos 90 dias anteriores;
- **força estrutural:** diferença logarítmica de ranking atual e mudança desde
  a última observação factual;
- **superfície:** forma recente e registo histórico no piso atual;
- **matchup/H2H:** histórico bilateral global e no mesmo piso;
- **serviço/resposta:** pontos de serviço e resposta, hold e break no piso,
  mais contexto recente.

Estes campos não são cinco scores. São candidatos factuais para avaliação.
Cada componente tem cobertura e acerto direcional reportados separadamente.

## O que esta fase não faz

- não escolhe pesos;
- não soma componentes correlacionados;
- não ajusta uma probabilidade;
- não produz fair odd ou edge;
- não altera o motor, o relatório, PAPER ou GREEN;
- não utiliza o mercado para escolher sinais.

O passo seguinte só poderá combinar componentes depois de observar resultados
em validação e confirmar novamente no holdout intocado.
