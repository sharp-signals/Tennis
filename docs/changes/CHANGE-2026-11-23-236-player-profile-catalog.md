# CHANGE-2026-11-23-236 — Catálogo pesquisável de jogadores

## Objetivo

Transformar as fichas JSON v2 numa base utilizável sem criar um separador por
jogador nem repetir leituras do histórico.

## Funcionamento

- seleciona jogadores com atividade factual nos últimos 730 dias;
- carrega uma vez o histórico e a cache de odds de cada circuito;
- gera uma ficha JSON por jogador sem consultar IDs individuais na API;
- cria um índice ATP/WTA pesquisável;
- cria páginas HTML simples para abrir cada ficha;
- mantém visível o alerta crítico quando existem menos de 20 jogos.

## Isolamento

- não altera a fair odd;
- não muda pesos ou famílias do modelo;
- o histórico de odds é lido em modo cache-only;
- a execução é manual através de
  `python -m src.generate_player_profile_catalog`.
- o workflow manual `Build Player Profile Catalog` permite gerar e publicar o
  catálogo no GitHub sem reativar os runs automáticos do Fenzobot.
