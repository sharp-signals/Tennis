# Contrato operacional pré-live do Fenzobot

Versão de decisão: `fenzobot-prelive-v1` (30 de agosto de 2026;
CHANGE-2026-08-30-011). Contrato de source de odds operacional:
`rapidapi-bilateral-prelive-v2` (CHANGE-2026-09-30-068).

## Fonte de decisão

O jogador é escolhido exclusivamente pelo índice ponderado Fenzobot. O
Sharp/Market-Residual Pricing só estima probabilidade, fair odd e edge desse
lado; não substitui o motor de seleção.

## Estados

- `EDGE_POSITIVE`: edge do lado Fenzobot estritamente superior a zero e
  cobertura ponderada de pelo menos 60%; registo automático em PAPER.
- `EDGE_POSITIVE_COVERAGE_INSUFFICIENT`: edge positivo, mas cobertura abaixo
  de 60%; mantém o relatório factual, sem registo PAPER.
- `EDGE_NEGATIVE`: edge inferior a zero; excluído.
- `EDGE_ZERO`: edge exatamente igual a zero; excluído.
- `PRICING_UNAVAILABLE`: dados factuais válidos, mas sem um par de odds
  operacional e estruturalmente verificável; mostra a análise factual, sem
  edge e sem PAPER.
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

A fonte RapidAPI operacional para pricing, edge e PAPER é a Moneyline bilateral
pré-live do feed regular `upcoming`, quando o mesmo registo do fornecedor prova
os dois jogadores, a orientação e o `eventId`. O plano regular expõe esta
Moneyline, mas não a casa nem timestamp de formação: o relatório preserva
`bookmaker = N/D` e `OBSERVED_AT_CAPTURE_UNVERIFIED_AGE`; não a chama consenso,
melhor odd, 22Bet ou closing/CLV comparável.

`recent-odds`, movimentos, arbitragem e comparação de bookmakers pertencem a
endpoints premium. Podem complementar observação SHADOW quando habilitados,
mas uma recusa de acesso nunca bloqueia o relatório, pricing, edge ou PAPER
baseado no par bilateral regular validado.

Desde `CHANGE-2026-09-10-036`, cada candidato passa também pelo Market Quote
Integrity Gate. Pares incompletos, não finitos, iguais/inferiores a 1.0 e o
padrão-limite `min <= 1.01` com `max >= 10.0` são rejeitados. O preço
operacional exige um par bilateral verificável: pode ser um bookmaker factual
com os dois lados, ou o feed pré-jogo normal do fornecedor quando este não
expõe bookmaker. Esta última hipótese fica sempre marcada como `casa não
indicada`, nunca como consenso. Com três ou mais candidatos factuais,
candidatos a mais de 15 p.p. da mediana de-vig são rejeitados; dispersão final
superior a 15 p.p. bloqueia o mercado. A seleção usa proximidade à mediana,
depois overround e nome. Um único bookmaker válido fica identificado como
`SINGLE_BOOKMAKER_OPERATIONAL`; nunca é descrito como consenso. Identidade e
integridade estrutural continuam obrigatórias e falham fechadas.

Só `operational_pricing_eligible is True` autoriza um papel operacional. A
ausência da flag equivale a rejeição. Pricing, snapshot, PAPER e Market-Time
Ledger preservam a versão/fingerprint determinística do contrato. O boundary
é prospetivo: começa na primeira observação pós-merge que transporte a
fingerprint; histórico anterior permanece `LEGACY / PRE-CONTRACT-FINGERPRINT`
e não é reclassificado.

## Identidade canónica prospetiva

`CHANGE-2026-09-21-049` acrescenta o contrato `MATCH_INSTANCE_ID_V2` sem
alterar `rapidapi-recent-gated-v1` nem a fingerprint
`d8679462537d9f461ca7`. Uma instância singles nova só pode receber uma key
opaca `mi2_<uuid4-hex>` quando existirem `tour`, `tournament_id`, os dois
player IDs factuais e um discriminador forte: `event_id` com validation basis
explícita `PLAYER_IDS`/`STRUCTURAL_MATCH_ID`, ou `round_id` factual. O estado
genérico `VERIFIED` e a basis `EXACT_NAMES` podem continuar válidos para o
contrato de pricing, mas nunca são prova forte para identity v2. O ID é mintado
uma vez e nunca é recalculado a
partir de hora, nomes, round, orientação A/B ou identificadores do provider.

Os estados são `CANONICAL_STRONG`, `CANONICAL_RESOLVED`,
`IDENTITY_PROVISIONAL`, `IDENTITY_INSUFFICIENT` e `IDENTITY_CONFLICT`.
`EVENT_ID` é alias forte apenas quando estrutura e jogadores são coerentes;
`MATCH_ID` é alias fraco, reutilizável e nunca minta sozinho. Nomes+hora nunca
autorizam snapshot ou PAPER. Provisional, insufficient e conflict podem gerar
relatório factual e observação de Ledger, mas não memória operacional,
snapshot canónico nem PAPER. Doubles são explicitamente unsupported nesta
versão.

`round_id` factual é guardado na instância e resolvido apenas dentro de
`tour+tournament_id+canonical player IDs`. Esta evidence forte é consultada
antes do alias fraco `MATCH_ID`: um match ID reutilizado nunca pode prevalecer
sobre round ou EVENT_ID incompatível.

O boundary é a primeira observação de produção pós-merge com schema v2. O
registry começa vazio, preserva CHANGE-ID, runtime SHA/run ID e instante da
primeira observação quando disponíveis — mesmo quando essa observação é
provisional/insufficient/conflict — e não recebe backfill. Objetos legacy
continuam no caminho CHANGE-047. Settlement v2 exige resolução bilateral para
a mesma instância; ambiguidade não liquida. Auto merge/split exige outro
CHANGE.

`data/match_identity/` é publicado pelo workflow em runs bem-sucedidas e
falhadas. Se o append do audit JSONL falhar no processo, a projeção do registry
é revertida antes do resultado fail-closed; permanece apenas o risco de crash
da máquina no intervalo exato entre operações locais persistidas.

A The Odds API fornece apenas uma comparação independente de mercado quando
estiver explicitamente ativada; desde o `CHANGE-2026-09-03-024` está `OFF` por
defeito. Não substitui, não faz média e não bloqueia o preço
operacional RapidAPI; a ausência desse comparador não invalida um par RapidAPI
válido. Snapshot e PAPER guardam fonte, instante UTC e tipo de captura do
preço que efetivamente alimentou o pricing.

## Exceção Challenger 125 — observação experimental

Desde `CHANGE-2026-10-04-073`, quando não existir uma quote operacional com
timestamp de bookmaker, o Challenger 125 pode usar **apenas para o relatório
experimental** a Moneyline bilateral do feed pré-jogo RapidAPI. Os dois
jogadores, a orientação e o `eventId` têm de estar verificados no mesmo
registo. A origem fica marcada como `OBSERVED_AT_CAPTURE_UNVERIFIED_AGE` e
`casa não indicada`: não afirma que seja 22Bet, melhor odd, consenso ou preço
fresco do bookmaker. Esta exceção não satisfaz o gate operacional, não entra
em PAPER/GREEN e não altera o contrato normal de ATP/WTA.
A referência de handicap no relatório é apenas uma tabela interna
de contexto por faixa de Moneyline; nunca é uma linha observada, uma odd, um
edge ou uma entrada PAPER.

As métricas de diferencial de games usam apenas resultados históricos
completos e legíveis, separam BO3 de BO5 e rejeitam retiros, walkovers e
scores parciais. ATP Grand Slam é classificado como BO5; os restantes casos
mantêm BO3 salvo indicação explícita da fonte. Cruzamentos históricos entre
Moneyline e margem só são exibidos se as colunas de odds existirem de facto no
dataset.

No Mapa de Ações, o cartão **Handicap para avaliar em PAPER** começa pela zona
interna indicada pela Moneyline pré-live para o jogador selecionado pela
decisão. Se esse jogador for o underdog, a zona do favorito é espelhada (por
exemplo, favorito `-4 / -4.5` corresponde a underdog `+4 / +4.5`). Para cada
linha, expõe `cobre / devolve / falha` em contagem e percentagem, incluindo
separadamente o que ocorre nas vitórias e derrotas. Quando existem odds
históricas reais, acrescenta a mesma leitura apenas para a faixa de Moneyline
comparável e o mesmo formato (BO3 ou BO5). O cartão indica a linha mais
protegida a procurar primeiro, mas não cria linha capturada, odd, edge nem uma
entrada PAPER automática de handicap.

O cartão de Moneyline acrescenta, quando disponível, a percentagem histórica
de vitórias na faixa de odds comparável e no mesmo formato. Para super favoritos
com Moneyline até `1.45`, o Mapa inclui um cenário live após perda do primeiro
set, com taxa de recuperação, amostra e Moneyline de referência. Estar break
abaixo durante o primeiro set é apenas um gatilho de observação até existir
histórico ponto-a-ponto; não é apresentada uma taxa de recuperação inventada.
Mensagens técnicas sobre LLM deliberadamente desativado não são exibidas no
Mapa de Ações.

Em jogos BO5, cenários de recuperação após perder o primeiro set e de set
decisivo usam exclusivamente amostras BO5 explícitas; estatísticas genéricas
ou BO3 não são usadas como substituto. Sem scores BO5 com odds históricas na
faixa atual, o cartão de handicap declara que não existe validação PAPER por
preço e proíbe concluir que há valor de handicap a partir da amostra geral.

## Persistência e universos históricos

- `data/calibration_snapshots.json`: primeira fotografia pré-jogo por partida,
  imutável; a liquidação só preenche `outcome`.
- `data/paper_trades.json`: carteira PAPER append-only, uma entrada por
  partida/mercado; a liquidação só preenche `settlement`.
- `data/paper_integrity_exclusions.json`: ledger de anulações factuais; não
  apaga PAPER histórico, mas exclui uma entrada comprovadamente inválida de
  monitorização, liquidação e métricas.
- `data/market_ledger/`: observações Moneyline já recolhidas, em JSONL diário
  append-only, ligadas por `event_key`/`observation_id`; falhas desta camada não
  alteram decisão, PAPER ou settlement. Quotes apenas observadas, sem idade
  temporal verificável, deixam closing/CLV como N/D.
- `data/match_identity/registry-v2.json`: projeção corrente do resolver
  mint-once; `events-v2.jsonl` é audit trail append-only. IDs canónicos são
  internos e não são publicados no HTML, Telegram ou email.
- relatórios HTML: nome versionado com `report_id`; uma execução posterior não
  substitui o ficheiro original.
- `PAPER`, histórico reconstruído/backtest e `REAL` são apresentados
  separadamente. Campos sem fonte (por exemplo CLV, REAL e buckets de edge sem
  limites aprovados) aparecem como `N/D`.

Os registos PAPER anteriores referidos informalmente não têm uma carteira
identificável no histórico Git nem campos suficientes nos snapshots atuais.
Não foram fabricados nem reclassificados. A sua importação exige a fonte
original ou confirmação humana dos mercados, odds e decisões pré-jogo.
