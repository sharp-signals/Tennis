# Runtime prospetivo contextual v2

## Objetivo

Recolher previsões futuras do novo modelo hierárquico sem alterar qualquer
decisão operacional. O runtime começa uma coorte nova e não reclassifica
retrospetivamente as observações v1.

## Âmbito

- ATP e WTA apenas;
- Challenger permanece fora até existir calibração própria;
- identidade canónica obrigatória para persistência;
- primeira observação por jogo, versão e fingerprint é preservada;
- armazenamento em `data/contextual_shadow_observations-v2.jsonl`;
- histórico v1 permanece intacto e deixa de receber novos registos.

## Conteúdo de cada observação

- identidade canónica, jogadores, circuito e data;
- versão e fingerprint imutáveis do modelo;
- cinco probabilidades familiares e respetivas contribuições;
- cobertura das famílias e contexto de superfície;
- probabilidade central de ambos os jogadores;
- intervalo probabilístico a 90%;
- fair odd central e intervalo para ambos os jogadores;
- grupo de qualidade, extrapolação, amostra do bin e `reason_codes`;
- estado de prontidão SHADOW.

## Isolamento

O runtime é executado depois da decisão atual. A saída declara e testa:

- `market_used=false`;
- `edge_calculated=false`;
- `production_effect=false`;
- `paper_eligible=false`;
- `green_eligible=false`.

Não existe painel visual v2 no relatório nesta fase. O objetivo é recolher uma
coorte prospetiva limpa antes de decidir sobre promoção ou redesenho visual.

## Ativação controlada

O runtime falha fechado. Sem configuração explícita, o payload recebe
`DISABLED / ACTIVATION_NOT_CONFIGURED` e nenhuma observação é persistida.

O único valor que permite observação é:

`CONTEXTUAL_SHADOW_V2_MODE=observe`

Qualquer outro valor permanece desativado. Mesmo em `observe`, continuam
obrigatoriamente falsos mercado, edge, efeito em produção, PAPER e GREEN.

O auditor read-only `scripts/audit_contextual_shadow_v2.py` verifica identidade,
deduplicação, versão, fingerprint, isolamento, probabilidades, intervalos e fair
odds. Ausência de observações é `WAITING_FOR_DATA`; violações de contrato fazem
o comando terminar com erro.

## Execução SHADOW-only

`scripts/run_contextual_shadow_v2.py` é um ponto de entrada separado do bot.
Faz somente descoberta factual, construção das cinco famílias, probabilidade,
fair odd, persistência v2 e auditoria. Não consulta preços de mercado e não
gera HTML, dashboard, Telegram, email, PAPER, GREEN ou settlement.

O workflow `Contextual Shadow V2 Observation` é exclusivamente manual, sem
cron. Partilha a fila `tennis-data-writers` para impedir escritas concorrentes.
O resumo de cada execução é guardado em
`data/validation/contextual-shadow-v2-latest.json`.

## Persistência

O identificador da observação deriva de:

`identidade canónica + model_version + configuration_fingerprint`.

Um rerun com a mesma versão não duplica nem substitui a primeira previsão. Uma
futura versão metodologicamente diferente recebe outro fingerprint e constitui
uma coorte distinta.
