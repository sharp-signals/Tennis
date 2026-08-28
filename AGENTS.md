# AGENTS.md — Sharp Signals / Project Roland

Este ficheiro define as regras permanentes para qualquer agente/Codex que trabalhe neste repositório.

## 1. Papel do agente

O agente executa decisões e especificações do projeto. Não deve inventar silenciosamente regras de produto, alterar a metodologia ou expandir o scope por iniciativa própria.

Antes de alterar código:
1. ler `README.md`;
2. ler os contratos/documentos diretamente relevantes para a tarefa;
3. ler os testes existentes dos módulos afetados;
4. confirmar o scope recebido e identificar conflitos com o comportamento atual.

Se existir um `CHANGE-ID`, preservá-lo em branch, commit e relatório final sempre que possível.

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
Exemplos: definição do Fenzobot, pricing/calibração, arquitetura de dados, execução real, claims, metodologia central.

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
- Preferir uma branch por `CHANGE-ID`, por exemplo: `change/SS-2026-028-null-data`.
- Evitar que dois agentes trabalhem simultaneamente na mesma alteração/branch.
- Commits devem ser pequenos, coerentes e descritivos.
- Não apagar histórico operacional, snapshots ou PAPER ledger para “limpar” o repositório.

## 7. Testes e validação

Antes de concluir:
- correr os testes diretamente relacionados com os módulos alterados;
- correr a suite mais ampla quando a alteração tocar contratos partilhados, pricing, decisão pré-live, snapshots, PAPER, dados ou reporting;
- verificar explicitamente regressões em contratos existentes;
- não considerar “compila” ou “importa” como critério suficiente de conclusão.

Comandos de referência atuais:
- `python -m src.test_dry_run`
- `python -m pytest -q`

Se algum teste não puder ser executado por falta de credenciais, serviço externo ou ambiente, declarar isso claramente.

## 8. Módulos sensíveis

Alterações em `src/fetch_data.py`, `src/config.py`, `src/report_html.py`, `src/prelive_decision.py`, `src/pricing.py`, `src/calibration_store.py`, `src/paper_trading.py` ou respetivos contratos/testes podem afetar simultaneamente decisão, reporting, PAPER e validação histórica.

Tratar estes módulos como superfície de risco elevado e rever testes/contratos antes de editar.

## 9. Output obrigatório no fim de cada tarefa

Devolver um relatório curto com:
1. `CHANGE-ID` e objetivo;
2. ficheiros alterados;
3. comportamento alterado;
4. comportamento deliberadamente preservado;
5. testes executados e resultados;
6. riscos, limitações ou ambiguidades restantes;
7. commit/diff/PR, quando aplicável;
8. propostas fora do scope, separadas da implementação concluída.

## 10. Regra final

**O BRAIN decide; o Codex executa; o GitHub regista; os testes verificam; o Canon preserva a decisão.**
