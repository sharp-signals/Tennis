# CHANGE-2026-10-11-100 — Excluir Laver por encontro, preservando fatores reconstruíveis

Estado: IMPLEMENTED / AWAITING BRAIN REVIEW  
Issue: #223  
Base: `8ba904a4c4704e9a750be7985068896965a44c03`

> Nota de governação: o identificador CHANGE-2026-10-11-100 já foi usado no
> `main` pelo trabalho Challenger 125 integrado através da PR #222. Este
> registo usa um nome de ficheiro Laver-only para preservar ambos os históricos
> sem sobrescrever o CHANGE já publicado. A Issue #223 permanece a autoridade
> funcional desta implementação.

## Contrato

A alteração acrescenta um modo independente e exclusivamente prospetivo:

- versão: `laver-only-performance-v1`;
- hash: `competition_evidence.LAVER_ONLY_CONFIG_HASH`, derivado por SHA-256
  de uma especificação JSON canónica e imutável;
- âmbito: ATP;
- Laver Cup: peso zero por encontro nas amostras de desempenho;
- Davis Cup: mantém o tratamento produtivo anterior; a regra Davis 0,50 da
  política combinada não é ativada por este modo;
- seleção: a amostra é selecionada primeiro e só depois a Laver é removida;
  nunca há preenchimento N+1;
- carga/fadiga: factos brutos, sem ponderação;
- WTA: fora do âmbito e inalterada;
- histórico já persistido: imutável.

O modo permanece OFF. A política combinada
`davis-laver-performance-v1` também permanece OFF salvo configuração externa
explícita; os dois modos são mutuamente exclusivos porque partilham uma única
seleção de versão.

## Reconstrução e separabilidade

| Família | Fonte com o modo ativo | Estado |
|---|---|---|
| Forma, época, piso, H2H, indoor/outdoor, sazonal, qualidade de vitórias, serviço local e velocidade de piso | linhas de encontros selecionadas, com proveniência por encontro | preservada/recalculada |
| Tie-break | sets reconstruídos e ligados ao encontro de origem | preservada/recalculada |
| Sets decisivos | score + formato do encontro | preservada/recalculada |
| Recuperação após perder o 1.º set | score/sets do encontro, separado BO3/BO5 | preservada/recalculada |
| Pressão de ronda | ronda factual de cada encontro | preservada/recalculada |
| Matchup de mão | mão do adversário por encontro; cache de perfil só depois do filtro | preservada/recalculada quando a mão é resolvida |
| Nível do adversário | ranking factual do adversário em cada encontro | preservada/recalculada quando existe ranking |
| Histórico no torneio | ID factual; fallback apenas por nome normalizado exato | preservada/recalculada |
| Carga/fadiga | jogos/sets e datas brutos | preservada sem ponderação |
| Agregados opacos RapidAPI e margens históricas sem competição por encontro | continuam visíveis como factos, mas não reentram na decisão | bloqueio local explícito |

A matriz `factor_impact_matrix` mantém cada família separada: uma ausência
pontual não desativa globalmente as sete famílias reconstruíveis. O relatório e
o Mapa de Ações usam as fontes locais filtradas quando o modo está ativo e não
voltam a preferir agregados do fornecedor, fallbacks ou caches não versionadas.

## Ativação (não executada)

Após aprovação BRAIN, definir simultaneamente:

1. `FENZOBOT_COMPETITION_EVIDENCE_VERSION=laver-only-performance-v1`;
2. `FENZOBOT_COMPETITION_EVIDENCE_EFFECTIVE_FROM_UTC=<T0 UTC futuro>`.

O runtime valida versão e hash próprios, limita a ATP e aplica o cutover pela
identidade canónica. Não executar backfill, regeneração histórica ou pipeline
operacional para ativar/testar esta política.

## Limitações honestas

- Linhas sem identidade factual da competição, com sentinelas ou com conflito
  ID/nome falham fechadas; não recebem peso inventado.
- Um agregado sem linhas por encontro não pode provar exclusão integral. Fica
  fora do consumidor decisório enquanto a política estiver ativa.
- Matchup de mão, ranking do adversário e histórico no torneio só são
  reconstruídos quando os metadados factuais necessários existem.
- Margens/diferenciais de games ainda não carregam proveniência por competição;
  o pricing de handicap existente é preservado, mas essa família não é
  promovida pelo modo Laver-only.

## Preservação histórica

A PR não altera ficheiros em `data/`, `docs/relatorios/`, snapshots, PAPER,
settlement ou agregados publicados. Os testes usam DataFrames e stores
temporários; não executam rede, LLM, pipeline produtiva ou backfill.
