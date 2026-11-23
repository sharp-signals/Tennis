# CHANGE-2026-11-23-241 — Serviço e resposta completos na ficha

## Problema

A ficha mostrava apenas pontos ganhos no primeiro serviço e break points
salvos. A leitura não representava a resposta nem o contexto por piso e
condição, embora esses dados existam no histórico canónico.

## Alteração

- acrescenta uma tabela factual com pontos de serviço ganhos, primeiro serviço
  ganho, pontos de resposta ganhos, hold e break;
- separa carreira geral, últimos 90 dias, hard outdoor, indoor, clay e grass;
- completa os indicadores recentes dos últimos 20 jogos com aces, duplas
  faltas, primeiro serviço dentro, primeiro serviço ganho e break points
  salvos.

## Limite metodológico

Todas estas métricas permanecem `DESCRIPTIVE_ONLY`. A alteração melhora a
explicação da ficha e não modifica os pesos, a equação ou a fair odd.
