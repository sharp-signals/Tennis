# Contrato operacional pré-live do Fenzobot

Versão: `fenzobot-prelive-v1` (29 de agosto de 2026; CHANGE-2026-08-29-008).

## Fonte de decisão

O jogador é escolhido exclusivamente pelo índice ponderado Fenzobot. O
Sharp/Market-Residual Pricing só estima probabilidade, fair odd e edge desse
lado; não substitui o motor de seleção.

## Estados

- `EDGE_POSITIVE`: edge do lado Fenzobot estritamente superior a zero;
  registo automático em PAPER.
- `EDGE_NEGATIVE`: edge inferior a zero; excluído.
- `EDGE_ZERO`: edge exatamente igual a zero; excluído.
- `PRICING_UNAVAILABLE`: dados factuais válidos, mas sem um par de odds
  recente e verificável; mostra a análise factual, sem edge e sem PAPER.
- `REPORT_NULL`: dados factuais essenciais insuficientes; sem veredicto e sem
  PAPER. Não é usado apenas porque falta um preço de mercado.

Se ambos os lados tiverem edge positivo, o caso é tratado como anomalia,
registado como `REPORT_NULL` e não produz decisão automática.

## Validade e cobertura

A cobertura é a soma dos pesos-base dos fatores bilateralmente disponíveis a
dividir pela soma dos pesos-base configurados. Um dado ausente não vale zero,
não favorece qualquer jogador e fica fora do denominador efetivo usado pelo
índice; os fatores válidos são renormalizados pelo motor existente.

Um relatório é nulo quando ocorre pelo menos uma destas condições:

1. ranking ausente para qualquer jogador;
2. nenhuma métrica bilateral de serviço/resposta com amostra positiva;
3. nenhum bloco bilateral utilizável para o Mapa de Ações;
4. índice Fenzobot não calculável;
5. cobertura ponderada inferior a 45%.

O valor de 45% não é um limiar novo: reutiliza `PRICING_MIN_QUALITY`, que já
era o mínimo de qualidade do pricing. Os estados de cobertura são
`suficiente` (100%), `reduzida` (válida mas incompleta) e `insuficiente`
(relatório nulo). Estes critérios devem ser validados com dados liquidados e
versionados quando forem alterados.

Zeros com amostra explicitamente igual a zero são sentinelas de ausência e
passam a `N/D`. Um zero com amostra positiva continua a ser um resultado real.

Uma fixture só entra no pipeline se estiver inequivocamente pré-live. Estados
de live, em curso, suspenso, interrompido, retomado ou terminado são excluídos;
na ausência de um estado fiável, qualquer score/relógio de jogo disponível é
tratado de forma conservadora como evidência de início. A exclusão acontece
antes do enriquecimento, do relatório, do snapshot e do PAPER.

Quando o pricing usa a camada Extend, o `eventId` também tem de ser validado
contra os dois participantes, a ordem do fornecedor e o estado/data do evento.
Um evento terminado, em curso, com jogadores diferentes ou horário incompatível
é excluído pelo mesmo gate. As chaves `od1`/`od2` são então mapeadas pela ordem
confirmada pelo fornecedor, nunca pela ordem do fixture local.

## Mercados

A carteira suporta uma entrada por mercado e pode guardar Moneyline e
Handicap separadamente. No pipeline atual só Moneyline possui odds e pricing
próprios. Handicap não entra automaticamente até existir uma fonte real de
odd/linha e uma regra de edge já aprovada; não foi inventada uma regra.

Pricing, edge e PAPER preferem um par Moneyline do endpoint dedicado de odds,
com os dois lados na mesma casa, bookmaker identificável e timestamp do
fornecedor com no máximo 15 minutos. Quando esse endpoint devolver uma hora
ausente ou desatualizada, podem usar o par exato do feed *upcoming* observado
na própria execução, desde que a fixture/evento já tenha passado o gate de
identidade e pré-live. Este fallback não declara bookmaker nem timestamp do
fornecedor; snapshot, PAPER e relatório preservam explicitamente o tipo de
captura. A referência de handicap no relatório é apenas uma tabela interna
de contexto por faixa de Moneyline; nunca é uma linha observada, uma odd, um
edge ou uma entrada PAPER.

As métricas de diferencial de games usam apenas resultados históricos
completos e legíveis, separam BO3 de BO5 e rejeitam retiros, walkovers e
scores parciais. ATP Grand Slam é classificado como BO5; os restantes casos
mantêm BO3 salvo indicação explícita da fonte. Cruzamentos históricos entre
Moneyline e margem só são exibidos se as colunas de odds existirem de facto no
dataset.

## Persistência e universos históricos

- `data/calibration_snapshots.json`: primeira fotografia pré-jogo por partida,
  imutável; a liquidação só preenche `outcome`.
- `data/paper_trades.json`: carteira PAPER append-only, uma entrada por
  partida/mercado; a liquidação só preenche `settlement`.
- `data/paper_integrity_exclusions.json`: ledger de anulações factuais; não
  apaga PAPER histórico, mas exclui uma entrada comprovadamente inválida de
  monitorização, liquidação e métricas.
- relatórios HTML: nome versionado com `report_id`; uma execução posterior não
  substitui o ficheiro original.
- `PAPER`, histórico reconstruído/backtest e `REAL` são apresentados
  separadamente. Campos sem fonte (por exemplo CLV, REAL e buckets de edge sem
  limites aprovados) aparecem como `N/D`.

Os registos PAPER anteriores referidos informalmente não têm uma carteira
identificável no histórico Git nem campos suficientes nos snapshots atuais.
Não foram fabricados nem reclassificados. A sua importação exige a fonte
original ou confirmação humana dos mercados, odds e decisões pré-jogo.
