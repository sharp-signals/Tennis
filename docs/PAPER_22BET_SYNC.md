# Sincronização do PAPER Trading 22Bet

CHANGE-2026-09-06-023

A Sheet `Track_Record_Tennis_22Bet` é o registo operacional manual. O relatório do Fenzobot lê apenas o resumo publicado em `data/manual_paper_22bet.json`; nunca lê a Sheet privada durante uma execução do bot.

## Configuração única

1. Na Sheet, abrir **Extensões → Apps Script**.
2. Substituir o conteúdo de `Código.gs` pelo conteúdo de `scripts/google_apps_script/sync_paper_22bet.gs` deste repositório e guardar.
3. Em Apps Script, abrir **Definições do projeto → Propriedades do script** e criar:
   - `GITHUB_TOKEN`: token fine-grained do GitHub com permissão `Contents: Read and write` apenas para `sharp-signals/Tennis`.
   - `GITHUB_REPOSITORY`: `sharp-signals/Tennis`.
   - `GITHUB_BRANCH`: `main` (opcional; este é o valor por omissão).
4. Executar uma vez `syncPaperTradingToGitHub` e aceitar as permissões Google/GitHub.
5. Executar uma vez `installPaperTradingSync`. O Apps Script verifica a Sheet a cada 30 minutos e só cria commit quando os dados mudaram.

## Dados publicados

O JSON contém apenas métricas agregadas: entradas, liquidações, W–L, pendentes, unidades, ROI, odd média e segmentação por mercado e favorito/underdog. Não publica jogos individuais, notas nem dados pessoais.

## Uso no relatório

O Histórico do Sistema apresenta quatro blocos que não se misturam:

1. PAPER 22Bet — registo manual oficial.
2. Sinais PAPER do sistema — carteira técnica automática.
3. Reconstruído/backtest — precisão histórica do motor.
4. REAL — apostas reais, quando existirem.
