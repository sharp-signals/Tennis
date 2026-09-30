# Market Memory / Market-Time Ledger

> `GREEN_STRONG_V1` reutiliza este ledger sem novas chamadas. Consulte [docs/GREEN_STRONG_VALIDATION.md](docs/GREEN_STRONG_VALIDATION.md). A entrada é a probabilidade congelada no pricing; closing só serve para avaliação posterior, nunca para classificar.

**CHANGE-ID:** `CHANGE-2026-09-03-024`

**Nível:** 3 — arquitetura central de dados

**Estado:** implementação aprovada; SHADOW analítico; sem alteração de decisão

## Objetivo e limites

O Market-Time Ledger conserva, de forma append-only, todas as observações
Moneyline estruturalmente válidas que já estejam nas respostas obtidas pelo
pipeline pré-live ou pelo Odds Monitor. Não descobre jogos, não amplia o
universo monitorizado e não faz chamadas externas.

- RapidAPI continua a ser a fonte operacional existente.
- The Odds API é apenas um comparador opcional e está `OFF` por defeito através
  de `THE_ODDS_API_ENABLED=0`. A existência de um secret não ativa chamadas.
- O ledger e a vista derivada não usam Claude/Anthropic.
- Pricing, thresholds, Fenzobot e estados SHADOW/PAPER/REAL não mudam.
- Market Memory e CLV são análise experimental, não claims de edge.

## Fonte de verdade

Cada observação é uma linha JSON canónica em:

```text
data/market_ledger/observations/YYYY-MM-DD.jsonl
```

O `observation_id` é SHA-256 do conteúdo normalizado. Um retry idêntico não
acrescenta duplicado. Uma nova captura, mesmo com odds iguais, é outra
observação. Nenhuma observação existente é atualizada ou substituída.

Cada linha inclui identidade do evento e jogadores, início UTC, captura UTC,
provider, endpoint, bookmaker, odds decimais originais, probabilidades brutas
e de-vig, overround, timestamp do provider quando disponível, frescura, ordem
dos jogadores, origem/pipeline e hash do payload ou fragmento canónico.

O ficheiro `data/market_ledger/derived/market-memory-v1.json` é uma vista
reconstruível e não é fonte de verdade.

## Rotação e arquivo

Por omissão ficam 45 dias de JSONL diário ativo. Dias fechados mais antigos
são comprimidos deterministicamente, após verificação byte-a-byte, para:

```text
data/market_ledger/archive/YYYY/MM/YYYY-MM-DD.jsonl.gz
```

Um arquivo existente nunca é sobrescrito. A origem só é removida depois de o
gzip ser verificado. O leitor consulta em conjunto ficheiros ativos e arquivos.
`MARKET_LEDGER_ACTIVE_DAYS` pode aumentar a retenção, mas não pode ser inferior
a um dia.

## Linkage determinístico

- `event_key`: `tour:match_id`, com fallback SHA-256 apenas quando o ID falta;
- snapshot: congela `entry_market_observation_id` e referências opcionais;
- PAPER: copia o mesmo ID na secção `pregame`;
- settlement: pode acrescentar `closing_market_observation_id` e métricas CLV;
- outcome: continua ligado ao snapshot/PAPER pelo `event_key`/`snapshot_key`.

Snapshots e `pregame` antigos nunca são reescritos. Sem ligação comprovável,
os campos permanecem `UNAVAILABLE`.

## Elegibilidade temporal e CLV

Uma observação pode ser conservada mas só é comparável para CLV quando:

1. foi capturada estritamente antes do início congelado;
2. a ordem dos jogadores está verificada;
3. o bookmaker está identificado;
4. a frescura não é `STALE`, `UNKNOWN` nem `UNAVAILABLE`;
5. provider, fonte, endpoint, mercado e bookmaker coincidem com a entrada.

Em `recent-odds`, o `addTime` permanece explicitamente
`unreliable_for_freshness`; a frescura operacional é a captura da resposta,
conforme o contrato pré-live já vigente. Nos restantes endpoints, a
classificação temporal do provider continua a ser respeitada.

A closing observation é a última cotação elegível depois da entrada e antes
do início. Não há closing sintética, best-price multi-bookmaker ou utilização
de dados live. Sem observação posterior comparável, CLV fica indisponível.

Para o lado PAPER selecionado:

```text
CLV probability (p.p.) = (P_close_de_vig - P_entry_de_vig) × 100
CLV price (%)           = (odd_entry / odd_close - 1) × 100
```

O campo legado `clv_pct` contém a métrica primária em pontos percentuais de
probabilidade. Valor positivo significa movimento do mercado para o lado da
entrada.

## Previsões derivadas

- `market_only_prediction`: lado com maior probabilidade de-vig na entrada;
- `market_plus_sharp_prediction`: lado com maior estimativa Sharp congelada no
  snapshot original, mantendo versão e fingerprint do pricing.

As métricas posteriores de accuracy, Brier e log loss permanecem SHADOW e são
separadas por disponibilidade. Não recalculam snapshots antigos.

## Falhas

O ledger é best effort. Qualquer erro de validação, disco, arquivo ou leitura:

- não altera a decisão pré-live;
- não bloqueia nem remove uma entrada PAPER existente;
- não impede settlement do resultado/PnL;
- marca Market Memory/CLV como `INELIGIBLE` ou `UNAVAILABLE`;
- fica visível em logs/status, sem preencher valores por inferência.

JSONL corrompido não é truncado, reparado ou substituído automaticamente.
