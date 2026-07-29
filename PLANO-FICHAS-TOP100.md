# Plano: fichas do top 100 construídas aos poucos

> Decidido 28/07/2026. Objetivo: ter uma ficha rica por jogador para o
> top 100 ATP (e depois WTA), construída de forma incremental sem
> estourar a quota de 50 pedidos/dia da RapidAPI (plano free).
> Ritmo escolhido: CONSERVADOR — ~10 fichas/dia (top 100 em ~10 dias).

## Princípio central
As fichas NÃO mudam de dia para dia (stats de carreira são estáveis).
Logo: construir uma vez, guardar no repositório, e só ATUALIZAR cada
jogador de vez em quando. Não é "gerar 100/dia", é "gerar 10/dia até
estar completo, depois manutenção barata".

## Peças a construir

### 1. Buscar e cachear o ranking oficial
- Novo: `fetch_singles_ranking(tour)` em fetch_data.py, via endpoint
  `singlesRanking` (1 pedido traz a lista toda, com id matchstat + posição).
- Cache SEMANAL (7 dias) — rankings só mudam à segunda-feira.
- Dá a lista ordenada de quem são os top 100 e os seus IDs.

### 2. Enriquecer a ficha com getH2HVsAllOppStats
- Novo: `fetch_player_career_stats(tour, player_id)` em fetch_data.py.
- Traz stats de carreira ricas (serviço, resposta, 1º set, set decisivo,
  avgTime, estilo) — ver RESULTADOS-TESTES-ENDPOINTS.md.
- player_profile.py passa a incluir estes dados (além do que já tira do
  histórico Sackmann/TennisMyLife).
- Cruzar por ID (não por nome) — sem ambiguidade.

### 3. Gestor de progresso (o "quem falta")
- Ficheiro em data/ (ex: data/profile_build_state.json) que regista:
  - que jogadores (por id) já têm ficha e a data em que foi gerada.
- Todos os dias, escolher os próximos ~10 jogadores do top 100 SEM ficha
  (ou com ficha mais velha que X dias) e gerar só esses.
- Guardar o progresso (commit) para continuar no dia seguinte.

### 4. Orçamento de quota
- ORÇAMENTO_FICHAS_POR_DIA = 10 (conservador).
- Correr DEPOIS do bot principal, e só se sobrar quota suficiente.
- Idealmente, um contador de pedidos usados na execução para nunca passar
  um limite seguro (ex: parar se já se usaram 40 dos 50 no total do dia).

### 5. Workflow separado
- Novo `.github/workflows/build-profiles.yml`, agendado 1x/dia (a uma
  hora diferente do bot principal, ex: a meio da tarde), com commit das
  fichas geradas e do estado de progresso.
- Alternativa mais simples: correr no fim do workflow principal, mas
  separar é mais seguro (não atrasa nem arrisca o relatório diário).

## Fase de manutenção (depois do top 100 completo)
- Re-gerar a ficha de um jogador só quando:
  - ele jogou um jogo novo desde a última geração, OU
  - a ficha tem mais de N dias (ex: 30).
- Isto é um punhado de fichas por dia, não 100.

## Prioridade de construção
1. Primeiro os jogadores dos torneios ATIVOS que seguимos (Washington
   tem ~32-64, não 200) — dá valor imediato.
2. Depois alargar ao resto do top 100 por ordem de ranking.
3. Só depois pensar em WTA (mesma lógica) ou top 200.

## Notas de custo/quota
- getH2HVsAllOppStats: 1 pedido/jogador. 10/dia = 10 pedidos.
- singlesRanking: 1 pedido/semana (cacheado).
- Bot principal: ~20 pedidos/dia em dias cheios.
- Total em dia cheio: ~30/50. Folga confortável.

## Decisões ainda em aberto (para a sessão de implementação)
- Guardar as stats ricas em JSON estruturado (data/player_stats/) além do
  markdown? Facilitaria reutilização futura sem re-pedir à API.
- Incluir o getPlayerPerformanceBreakdown também (desempenho vs níveis de
  ranking do adversário)? É +1 pedido/jogador (20/dia em vez de 10).
