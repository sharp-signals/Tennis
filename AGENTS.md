# AGENTS.md — Fenzobot / Fenzo Intelligence

Este ficheiro define as regras permanentes para qualquer agente/Codex que trabalhe neste repositório.

## 0. Identidade canónica

- **Fenzo Intelligence** é a estrutura/entidade deste projeto e é constituída por Hugo e Guerra.
- **Fenzobot** é o nome canónico deste projeto/produto.
- `Sharp Signals` e `Project Roland` são designações históricas **SUPERSEDED** como nomes ativos desde `CHANGE-2026-09-04-025`.
- Não reintroduzir essas designações como identidade atual em documentação, UI, relatórios ou comunicação futura.
- Não reescrever o histórico: commits, PRs, CHANGE-IDs, snapshots, relatórios e identificadores técnicos legacy mantêm os nomes originais quando necessários para audit trail ou compatibilidade.
- O owner/URL técnico `sharp-signals` do repositório é um identificador legacy de infraestrutura, não o nome canónico do projeto.

## 1. Papel do agente

O agente executa decisões e especificações do projeto. Não deve inventar silenciosamente regras de produto, alterar a metodologia ou expandir o scope por iniciativa própria.

Antes de alterar código, trabalhar **delta-first**:

1. numa primeira entrada no repo, alteração estrutural ou tarefa sem contexto, ler `README.md`;
2. numa continuação de PR/CHANGE já compreendida, começar pela issue/brief, `git diff --name-only <base>...HEAD` e ficheiros efetivamente tocados — não reler o repo inteiro;
3. ler contratos adicionais apenas quando o delta toca a respetiva fronteira;
4. ler os testes diretamente associados aos módulos alterados;
5. confirmar scope e conflitos com o comportamento atual.

Usar `python scripts/plan_validation.py` para obter o plano proporcional de validação e, quando necessário, a política de main drift.

Se existir um `CHANGE-ID`, preservá-lo em branch, commit e relatório final sempre que possível.

### 1.1 Context budget

- Não fazer scans amplos do repo por rotina depois de o CHANGE estar compreendido.
- Não reler documentação estável a cada microcorreção.
- Preferir `search -> ficheiro relevante -> teste relevante` a `ler tudo -> procurar depois`.
- Se surgir uma dependência material nova, expandir contexto apenas para essa fronteira.
- Em iterações de review, começar pelo delta desde o último head revisto.

## 2. Fonte de verdade e princípios do produto

- O Fenzobot é um motor determinístico de evidência; o índice Fenzobot não é, por si só, uma probabilidade.
- A camada de pricing/fair odds/expected edge é experimental enquanto não existir validação OOS suficiente.
- O lado operacional é escolhido pelo Fenzobot; uma camada LLM não pode recalcular nem contrariar silenciosamente o motor determinístico.
- `SHADOW`, `PAPER` e `REAL` são universos distintos e nunca devem ser misturados.
- Dados em falta permanecem em falta. Não inventar valores nem transformar ausência em zero.
- Zeros que representem ausência de amostra/dado devem ser tratados como nulos segundo os contratos existentes; zeros legítimos com amostra válida permanecem valores reais.
- Snapshots pré-jogo são ex ante e imutáveis. Dados/resultados posteriores podem liquidar campos próprios, mas nunca reescrever o estado conhecido antes do jogo.
- Não criar claims de performance, edge validado ou recomendação de aposta sem evidência correspondente.

## 3. Níveis de alteração

### Level 1 — baixo risco
Exemplos: UI, logging, documentação, testes, bugfix ou refactor sem mudança material de comportamento.

Pode ser executado autonomamente dentro do scope pedido, desde que passe os testes relevantes.

### Level 2 — comportamento do produto
Exemplos: pesos, fatores, edge, paper logic, tratamento de dados, critérios de relatório, reporting decisório, thresholds.

Exige `CHANGE-ID`/brief explícito. Não alterar nada fora desse brief sem reportar primeiro.

### Level 3 — estrutural/constitucional
Exemplos: definição do Fenzobot, identidade canónica, pricing/calibração, arquitetura de dados, execução real, claims, metodologia central.

Antes de qualquer alteração Level 3, ler `docs/governance/CONSTITUTION.md` e confirmar que a alteração e o respetivo registo seguem a Constituição.

## 4. Política de scope

- Implementar a alteração mínima e robusta que satisfaça o pedido.
- Não fazer grandes refactors se não forem necessários.
- Não adicionar features “úteis” que não tenham sido pedidas.
- Se detetar uma melhoria fora do scope, reportá-la como proposta separada.
- Se existir ambiguidade que possa alterar comportamento de produto, parar essa parte e pedir decisão; continuar apenas trabalho independente e seguro.

## 5. Política de modelos e compute

Usar o modelo e o nível de reasoning mais leves que consigam executar a tarefa com segurança e qualidade suficiente.

Princípio:
- tarefas mecânicas/simples → modelo rápido e compute baixo;
- tarefas intermédias → modelo/compute normal;
- arquitetura, Level 2/3, data integrity, debugging difícil, segurança ou risco elevado de regressão → modelo mais forte e compute superior.

Objetivo: reduzir latência e consumo de compute sem degradar a qualidade.

Nunca sacrificar qualidade, correção ou segurança para poupar compute. Se uma tarefa inicialmente simples revelar dependências, ambiguidade ou risco material, escalar para um modelo/nível de reasoning mais forte antes de concluir, quando a superfície Codex o permitir.

Quando a seleção automática de modelo não estiver disponível, sinalizar no output final que nível de complexidade/compute seria apropriado para a tarefa seguinte.

## 6. Git e branches

- Não desenvolver diretamente em `main` para mudanças materiais.
- Preferir uma branch por `CHANGE-ID`, por exemplo: `change/CHANGE-2026-09-04-025-canonical-identity-fenzobot`.
- Evitar que dois agentes trabalhem simultaneamente na mesma alteração/branch.
- Evitar edição concorrente dos mesmos hotspots; quando inevitável, sincronizar antes de continuar.
- Commits devem ser pequenos, coerentes e descritivos.
- Não apagar histórico operacional, snapshots ou PAPER ledger para “limpar” o repositório.

### 6.1 Main drift

Não reiniciar automaticamente o ciclo só porque `main` avançou.

Avaliar primeiro o drift com `scripts/plan_validation.py`:

- mesmo ficheiro ou mesmo domínio crítico -> `SYNC_NOW`;
- apenas dados/artefactos gerados independentes -> `FINAL_SYNC_ONLY`;
- código independente -> rever o delta uma vez e continuar, deixando o sync final para o checkpoint;
- antes do merge, cumprir sempre a política de sincronização da PR/repo.

Uma full CI verde só é invalidada por alteração posterior de código relevante, sync com impacto material ou mudança de contrato — não por drift independente já classificado.

## 7. Testes e validação

Usar uma **validation ladder** em duas fases.

### Fase A — loop rápido

Durante desenvolvimento:
- correr apenas lint e testes diretamente ligados ao delta;
- corrigir primeiro no teste mais próximo da mudança;
- não correr a full suite depois de cada pequena edição;
- usar o output de `python scripts/plan_validation.py --level <1|2|3> ...`.

### Fase B — checkpoint final

Quando o diff estabilizar:
- fazer o sync necessário com `main`;
- correr/aguardar a full PR CI uma vez quando o CHANGE, nível de risco ou hotspot o exigir;
- Level 2/3 têm sempre full CI final;
- alterações em módulos sensíveis têm sempre full CI final;
- Level 1 docs/tests isolados podem usar validação proporcional, salvo requisito explícito do brief;
- qualquer edição de código material depois do checkpoint exige nova validação final.

A full CI final verifica o conjunto; o loop dirigido reduz latência e repetição.

Continuam obrigatórias regressões explícitas nos contratos existentes. “Compila” ou “importa” nunca é critério suficiente.

Se algum teste não puder ser executado por falta de credenciais, serviço externo ou ambiente, declarar isso claramente.

## 8. Módulos sensíveis

Alterações em `src/main.py`, `src/fetch_data.py`, `src/config.py`, `src/report_html.py`, `src/prelive_decision.py`, `src/pricing.py`, `src/calibration_store.py`, `src/paper_trading.py`, `src/competition_evidence.py`, `src/competition_registry.py` ou respetivos contratos/testes podem afetar simultaneamente decisão, reporting, PAPER e validação histórica.

Tratar estes módulos como superfície de risco elevado. Usar testes dirigidos durante o loop e full CI no checkpoint final.

## 9. Output obrigatório no fim de cada tarefa

Durante iterações intermédias, devolver apenas:
- head atual;
- ficheiros tocados;
- targeted tests executados;
- blocker concreto, se existir.

No checkpoint final, devolver um relatório curto com:
1. `CHANGE-ID` e objetivo;
2. base/head e ficheiros alterados;
3. comportamento alterado;
4. comportamento deliberadamente preservado;
5. targeted tests e full CI final, quando exigida;
6. riscos, limitações ou ambiguidades restantes;
7. commit/diff/PR;
8. propostas fora do scope, separadas da implementação concluída.

Não repetir o mesmo relatório longo a cada microciclo de review.

## 10. Regra final

**O BRAIN decide; o Codex executa; o GitHub regista; os testes verificam; o Fenzobot — Project Canon preserva a decisão.**
