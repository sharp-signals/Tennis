# CHANGE-2026-11-23-233 — base pesquisável de jogadores v2

## Objetivo

Criar a fundação factual para um ficheiro separado de jogadores, sem um
separador por atleta e sem introduzir uma segunda equação de fair odd.

## Primeiro bloco

- contrato JSON versionado por jogador;
- índice único pesquisável ATP/WTA;
- proveniência, amostra e papel no modelo em cada métrica;
- alerta crítico quando a ficha tem menos de 20 jogos;
- ausência e não aplicabilidade nunca são convertidas em zero;
- métricas iniciais: ranking observado, forma simples, piso de carreira e
  serviço recente;
- todas as métricas iniciais permanecem `DESCRIPTIVE_ONLY` até serem ligadas
  exatamente aos fatores ativos ou aprovadas por replay cronológico.

## Próximos blocos

1. ranking anual e representativo;
2. forma e qualidade ajustadas ao nível competitivo;
3. desempenho por tier, piso/condição, BO3/BO5 e patamar do adversário;
4. contexto histórico de odds;
5. ficha visual dinâmica e comparador de dois jogadores;
6. geração em lote ATP/WTA e sincronização do ficheiro separado.

## Limites

Este bloco não altera probabilidades, fair odds, famílias, PAPER, GREEN nem
runs operacionais.
