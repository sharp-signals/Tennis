# Resultados dos testes de endpoints RapidAPI (28/07/2026)

Testes feitos na Playground para decidir o que vale a pena integrar.
IDs matchstat úteis descobertos: Sinner=47275, Alcaraz=68074,
De Minaur=39309, Zverev=24008, Djokovic=5992, Shelton=87562.

## ✅ singlesRanking — INTEGRAR (alto valor, baixo custo)
- Dá o ranking oficial atual (posição, pontos, data, id matchstat de cada
  jogador) — resolve o problema do nosso ranking derivado do histórico,
  que fica desatualizado para quem não joga há semanas (caso Alcaraz).
- **1 só pedido traz a lista inteira** (~centenas de jogadores) — não é
  por jogador. Buscar 1x, cachear, usar para todos os jogos.
- IMPORTANTE: rankings ATP/WTA só mudam à SEGUNDA-FEIRA. Cache semanal
  (7 dias), não diária — senão é desperdício de quota.
- Consistência confirmada: pontos do Sinner (13450) batem com o histórico.

## 📋 getPlayerPerformanceBreakdown — INTEGRAR NAS FICHAS (não no fluxo diário)
- Traz, partido por ANO (2015-2026):
  - `court`: por piso (1=Hard, 2=Clay, 3=I.hard/indoor, 4=Carpet, 5=Grass)
  - `rank`: vitórias/derrotas contra cada patamar (top1/5/10/20/50/100) —
    ISTO É NOVO e valioso: distingue quem ganha contra os melhores de quem
    só limpa rankings baixos (o "average opponent ranking" que faltava).
  - `level`: por nível de torneio (masters, grandSlam, mainTour, etc.)
  - `round`: por ronda.
- Custo: 1 pedido por jogador. Por isso → fichas (sob demanda), não fluxo
  diário de todos os jogos.

## 🎾 getPlayerSurfaceSummary — REDUNDANTE com o anterior
- Vitórias/derrotas por piso, partido por ano, com split indoor/outdoor
  (I.hard separado de Hard) — mais fino que o nosso compute_surface_stats
  atual (que junta tudo e não separa por ano).
- MAS: o getPlayerPerformanceBreakdown já traz o mesmo `court` por ano.
  Não vale a pena gastar 2 pedidos — usar o breakdown para ambos.

## Ainda por testar (quando houver quota/vontade)
- getH2HVsAllOppStats — stats de carreira vs todos, com "average opponent
  ranking". Ver se acrescenta ao que o breakdown já dá.
- getPlayerPastMatches — últimos jogos com detalhe (fadiga real / minutos?).

## Decisão de arquitetura sugerida
- **Fluxo diário (por jogo):** manter leve. Só acrescentar o ranking
  oficial (via singlesRanking cacheado semanalmente), que é barato e
  melhora todos os jogos.
- **Fichas de jogador (sob demanda):** enriquecer com o
  getPlayerPerformanceBreakdown — piso por ano (com indoor/outdoor) e,
  sobretudo, desempenho por nível de ranking do adversário. É aqui que
  o dado rico por jogador faz sentido, sem pressionar a quota diária.
