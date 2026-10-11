# CHANGE-2026-10-11-101 — Cobertura histórica dos handicaps

## Problema

O relatório de Alex De Minaur vs Karen Khachanov mostrava apenas três jogos
BO3 analisáveis no bloco de handicap, apesar de o mesmo relatório conhecer 100
jogos recentes e 52 partidas com odds históricas. O número não representava a
carreira do jogador: resultava de uma rota isolada de dados e de comparações
literais da grafia escolhida para o nome.

## Alteração

- A correspondência do jogador no histórico passa a incluir todas as grafias
  equivalentes após normalização conservadora de acentos, caixa e pontuação.
- O perfil de margem de games combina o histórico longo com os `past-matches`
  recentes já recolhidos por ID de jogador; não cria chamadas externas novas.
- Jogos presentes nas duas fontes são deduplicados por data e adversário, com
  prioridade para o registo recente identificado por ID.
- Só entram resultados completos e scores convencionais. Retires, W/O,
  partidas futuras e scores incompatíveis com o vencedor declarado continuam
  excluídos.
- O formato BO3/BO5 é usado quando declarado; na ausência desse campo, só é
  inferido quando o score completo demonstra duas ou três vitórias em sets.
- O payload preserva uma contagem auditável dos jogos vindos do histórico
  longo e da fonte recente.

## Evidência de regressão

Na fonte real, a comparação literal encontrava 3 linhas para `Alex De Minaur`,
enquanto a comparação normalizada encontra 545 partidas nas grafias
`Alex De Minaur` e `Alex de Minaur`. Depois de exigir scores completos e juntar
a cache recente com deduplicação, o perfil contém 413 jogos BO3 (259 vitórias e
154 derrotas) e 107 BO5, em vez dos três apresentados pelo relatório anterior.

## Preservado

- Não altera pesos, índice Fenzobot, pricing Moneyline, edge, PAPER, GREEN ou
  snapshots históricos.
- Não transforma partidas incompletas em margens estimadas.
- Não mistura BO3 e BO5 e não altera a regra visual das linhas de handicap.
