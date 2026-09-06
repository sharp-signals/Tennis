# Sincronização do PAPER Trading 22Bet

## Seleção manual GUERRA_SELECTION_V1

O menu `Instalar colunas GREEN_STRONG_V1` acrescenta seis colunas opcionais sem modificar as 15 existentes: snapshot key, estratégia, timestamp, odd Moneyline de revisão, linha real de Handicap games e estado. É idempotente; o timestamp é gravado uma única vez ao introduzir um novo key.

Uma linha só entra no agregado da estratégia com correspondência exata a uma tag prospetiva e timestamp anterior ao início. Estados: `LINKED_EX_ANTE`, `SNAPSHOT_NOT_FOUND`, `NOT_GREEN_STRONG`, `SELECTION_AFTER_START`, `MISSING_SELECTION_TIMESTAMP` e `UNAVAILABLE`. Não há associação aproximada.

O JSON público contém somente agregados em `by_strategy.GUERRA_SELECTION_V1`; nunca nomes, keys, notas ou linhas. Ver [GREEN_STRONG_VALIDATION.md](GREEN_STRONG_VALIDATION.md).

Quando o selecionado é underdog, a metodologia usa duas rows com o mesmo key: Moneyline e Handicap games positivo. `selection_rate_pct` usa candidatos/keys únicos, enquanto `paper_entries` mostra as legs. `underdog_pair_completeness` separa pares completos, Moneyline-only, handicap-only e casos não reconhecidos, sem publicar os keys.

O fingerprint é semântico: inclui os agregados e estados de linkage derivados, mas exclui o timestamp de sincronização e a coluna `Validation Status` escrita pelo próprio script. Assim, uma alteração do índice GREEN_STRONG volta a publicar o resumo mesmo que as rows privadas não tenham mudado.

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
