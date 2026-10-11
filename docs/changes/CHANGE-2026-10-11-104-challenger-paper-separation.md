# CHANGE-2026-10-11-104 — Challenger PAPER separado e edge mínimo 2%

Estado: **IMPLEMENTADO / AGUARDA MERGE E ATIVAÇÃO DO APPS SCRIPT**
Level: **2 — comportamento do produto**

## Decisão

O universo Challenger 125 continua experimental, manual e separado do PAPER
ATP/WTA principal. O limiar mínimo de edge para candidatura passa de 4%/3%
para **2%**, tanto com cobertura parcial como suficiente. Mantêm-se:

- cobertura ponderada mínima de 50%;
- índice Fenzobot mínimo de 70;
- pelo menos 10 jogos recentes por jogador;
- preço Moneyline válido;
- stake manual fixa de 0,5u;
- bloqueio de PAPER técnico e GREEN.

## Sheet PAPER

O Apps Script passa a preparar uma operação explícita e idempotente:

1. `Challenger · Entradas` recebe apenas o registo manual experimental;
2. `Tour = ATP`, `Nível = Challenger`, `Selected At UTC` e `Stake (u) = 0,5`
   são aplicados automaticamente;
3. a aba principal `Apostas` não recebe as novas entradas Challenger; antigas
   linhas Challenger continuam a ser reconhecidas e excluídas dos totais;
4. edge inferior a 2% recebe `INVALID_CHALLENGER_EDGE` e não entra nas
   métricas;
5. a aba `Challenger · Gráficos` mostra KPIs e gráficos próprios por mercado,
   favorito/underdog, edge, índice e cobertura.

O JSON público continua agregado e não publica jogadores, jogos, snapshot
keys, notas ou linhas individuais.

## Ativação externa

Depois do merge, substituir o conteúdo do projeto Apps Script PAPER pelo
ficheiro canónico `scripts/google_apps_script/sync_paper_22bet.gs`, guardar e
executar uma vez `installChallengerPaperWorkspace`. O trigger existente de
`syncPaperTradingToGitHub` passa depois a atualizar a aba Challenger e o resumo
agregado automaticamente.
