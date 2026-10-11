# Codex Fast Path

CHANGE-2026-10-11-103 reduz o tempo de desenvolvimento sem alterar os gates de
produto. A regra base é simples: **contexto e testes proporcionais durante o
loop; validação completa apenas no checkpoint final quando o risco a exige**.

## 1. Começar pelo delta

Numa continuação de uma PR/CHANGE, não reler o repositório inteiro.

Ler primeiro:

1. issue/Implementation Brief ativo;
2. `AGENTS.md`;
3. `git diff --name-only <base>...HEAD`;
4. os ficheiros efetivamente tocados;
5. os testes diretamente ligados a esses ficheiros;
6. contratos adicionais apenas quando o delta toca a respetiva fronteira.

`README.md` e documentação ampla são obrigatórios numa primeira entrada no
repo, numa alteração estrutural, ou quando o brief depende deles; não precisam
de ser relidos em cada microcorreção de uma PR já compreendida.

## 2. Planear a validação automaticamente

Exemplo:

```bash
python scripts/plan_validation.py \
  --level 2 \
  --base origin/main \
  --head HEAD
```

O output separa:

- comandos dirigidos para o loop de desenvolvimento;
- necessidade de full CI no checkpoint final;
- módulos/domínios sensíveis tocados.

Também pode trabalhar sem Git:

```bash
python scripts/plan_validation.py --level 1 \
  --file src/fetch_data.py \
  --file tests/test_data_transforms.py
```

## 3. Validation ladder

### Fase A — loop rápido

Depois de cada alteração lógica:

- correr apenas lint/testes dirigidos indicados pelo planner;
- corrigir o erro no teste mais próximo da mudança;
- não correr a suite completa depois de cada pequena edição.

### Fase B — checkpoint final

Quando o diff estabilizar:

- sincronizar com `main` se necessário;
- correr/aguardar a full PR CI **uma vez** quando o planner, CHANGE ou contrato a
  exigir;
- qualquer edição de código após essa CI invalida o checkpoint e exige nova
  validação final.

Level 2/3 e módulos sensíveis continuam sempre com full CI final. O fast path
reduz repetições; não elimina gates.

## 4. Main drift sem reiniciar trabalho

Para avaliar o avanço de `main`:

```bash
python scripts/plan_validation.py \
  --level 2 \
  --base <PR_BASE> \
  --head HEAD \
  --drift-from <PR_BASE> \
  --drift-to origin/main
```

Interpretação:

- `SYNC_NOW`: overlap no mesmo ficheiro ou domínio crítico;
- `FINAL_SYNC_ONLY`: drift apenas em dados/artefactos gerados e sem overlap;
- `REVIEW_ONCE_THEN_FINAL_SYNC`: drift independente; rever uma vez e não
  reiniciar toda a análise;
- `NO_SYNC_NEEDED`: sem drift relevante no intervalo analisado.

Antes do merge continua a ser necessário estar sincronizado quando a política
da PR/repo o exigir.

## 5. Concorrência

Evitar dois agentes a editar simultaneamente o mesmo hotspot:

- `src/main.py`
- `src/fetch_data.py`
- `src/config.py`
- `src/report_html.py`
- `src/prelive_decision.py`
- `src/pricing.py`
- `src/calibration_store.py`
- `src/paper_trading.py`
- `src/competition_evidence.py`
- `src/competition_registry.py`

Se `main` mudar um hotspot ou o mesmo domínio crítico, sincronizar antes de
continuar. Se mudar apenas dados independentes, não repetir a investigação nem
a suite completa durante o loop.

## 6. Output Codex mais curto

Durante iterações intermédias devolver apenas:

- head atual;
- ficheiros tocados;
- targeted tests e resultado;
- blocker concreto, se existir.

No checkpoint final acrescentar:

- base/head;
- full CI;
- riscos;
- preservações;
- estado MERGED/ACTIVE separado.

Isto evita repetir longos relatórios a cada microciclo.
