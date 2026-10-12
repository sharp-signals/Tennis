# CHANGE-2026-10-12-106 — Histórico ATP de odds resiliente

## Implementation Brief

### Problema

O bloco ATP de desempenho por faixa de Moneyline devolvia zero linhas da
fonte externa e acabava por mostrar apenas a pequena amostra canónica do
próprio Fenzobot. A causa não era falta de histórico ATP: o fornecedor mudou
os downloads anuais para caminhos versionados publicados na sua página de
dados, enquanto o carregador continuava a pedir os antigos caminhos diretos,
que passaram a responder HTTP 403.

### Alteração

- O carregador descobre uma vez por execução os links anuais ATP e WTA
  publicados na página oficial, sem fixar no código o token do caminho atual.
- ATP e WTA passam a usar o mesmo contrato de descoberta e download HTTPS.
- O download envia a página oficial como referência e mantém a normalização
  atual das colunas de resultados, scores e odds.
- O backtest deixa de manter um segundo URL ATP obsoleto e reutiliza o mesmo
  resolvedor oficial do relatório.
- Cada ano válido continua a ser guardado em `data/history_cache`; o perfil de
  publicação do bot passa a preservar explicitamente essa cache. Assim, uma
  execução futura pode usar a cópia local se a fonte estiver temporariamente
  indisponível, tal como já acontecia com os ficheiros WTA versionados.
- Testes cobrem a descoberta dos dois tours, o uso do URL descoberto, o
  fallback local e a autorização explícita da cache na publicação.

### Evidência

Com o novo resolvedor, os dez ficheiros ATP de 2017–2026 fornecem 24 584
partidas. O ficheiro de 2025, por exemplo, contém 2644 partidas e as colunas
`B365W/B365L`, `PSW/PSL`, `AvgW/AvgL` e scores por set. Para Alex De Minaur,
a faixa 1.61–1.80 passa a ter 64 jogos com odds e score completos, em vez de
depender apenas do único snapshot canónico mostrado anteriormente. O mesmo
pedido pelo caminho direto antigo falhava antes da alteração.

### Preservado

- Não altera resultados históricos, pesos, índice Fenzobot, pricing, edge,
  PAPER, GREEN ou regras de handicap.
- Não estima odds ausentes nem converte ausência de dados em zero.
- O histórico externo continua descritivo; os snapshots canónicos e a regra
  ex ante permanecem separados.
