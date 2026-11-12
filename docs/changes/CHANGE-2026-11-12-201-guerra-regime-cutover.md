# CHANGE-2026-11-12-201 — separação do GUERRA LEGACY e CONTEXTUAL

## Problema

As seleções históricas de Guerra foram produzidas com pesos antigos e com uma
fair odd que não era independente do mercado. A projeção do Histórico &
Aprendizagem apresentava essas entradas sem identificar o regime e permitia que
fossem interpretadas como validação do modelo contextual novo.

## Alteração

- `GUERRA_SELECTION_V1` passa a ser apresentado explicitamente como
  `LEGACY / SUPERSEDED` e permanece preservado apenas para memória histórica.
- novas seleções são carimbadas como `GUERRA_CONTEXTUAL_V1`, com a versão
  `FENZOBOT_CONTEXTUAL_2026_11`;
- uma edição posterior nunca reclassifica uma linha LEGACY;
- o painel de decisão sobre pesos lê exclusivamente o regime contextual;
- as folhas antigas são migradas para nomes `GUERRA LEGACY — ...`;
- é criada `GUERRA CONTEXTUAL — estado`, sem qualquer mistura de entradas
  antigas;
- a análise contextual por família fica indisponível até existir uma ligação
  própria por observação e versão do modelo, sem reconstrução artificial.

## Garantias

- nenhum registo histórico é apagado;
- nenhuma seleção LEGACY entra na validação do modelo novo;
- o cutover é exclusivamente prospetivo;
- Challenger continua num universo separado.

## Verificação

- testes unitários dos dois Apps Scripts;
- testes da projeção XLSX e dos nomes das folhas em CI;
- `git diff --check`.
