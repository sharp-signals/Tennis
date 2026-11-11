# CHANGE-2026-11-10-185 — robustez contextual e relatório auditável

## Objetivo

Corrigir, num único bloco, a leitura enganadora em que uma família — sobretudo
força estrutural — podia ser suficiente para declarar um favorito. Tornar o
relatório privado da `FENZOBOT_CONTEXTUAL_2026_11` visual, auditável e útil para
revisão humana, sem ligar esta release ao bot operacional.

## Correções metodológicas

1. Cada previsão passa por uma análise `leave-one-family-out`: são recalculados
   cinco cenários, retirando uma família de cada vez.
2. Se a retirada de uma única família inverter o lado favorito, a estimativa
   central é preservada, mas o favoritismo fica **não confirmado** com o motivo
   `SINGLE_FAMILY_DEPENDENCE`.
3. Um favorito não confirmado não formula Moneyline nem handicap no relatório.
4. O intervalo histórico deixa de usar o centro empírico do bin como se fosse
   uma segunda previsão. A largura empírica é centrada na probabilidade real do
   jogo e alargada para incluir todos os cenários sem uma família.
5. Cada família expõe os valores, ausências, coeficientes e contributos logit
   exatos usados pela equação congelada. A força estrutural expõe também ranking
   atual, pontos, ranking representativo, melhor ranking observado e contexto de
   regresso/inatividade quando disponíveis.

Isto trata regressos após lesão e rankings momentaneamente pouco
representativos como um problema estrutural geral. Não existe exceção por nome
de jogador e a probabilidade central não é arbitrariamente corrigida.

## Evidência factual adicionada ao relatório

- Snapshot Moneyline pré-jogo, append-only, com win rate geral e na faixa exata
  da odd observada, separado por BO3/BO5 e com corte cronológico estrito.
- Três linhas de handicap em destaque e todas as restantes meias linhas
  relevantes disponíveis numa secção expansível.
- Cada linha mostra cobertura total, quando vence, quando perde, amostra e
  estado/preço calculado pela própria linha.

O mercado continua a ser capturado apenas depois da previsão e nunca altera a
probabilidade, fair odd ou contributos das famílias.

## Versionamento e preservação

- `runtime_generation`: 4.
- Contrato do relatório global: `fenzobot-contextual-2026-11-report.2`.
- Observações anteriores permanecem imutáveis e auditáveis.
- O auditor aceita exclusivamente a geração 3/fingerprint histórico declarado
  no contrato; fingerprints desconhecidos continuam a falhar fechados.
- A nova geração cria uma coorte identificável por novo fingerprint.
- O novo ledger de Moneyline é permitido apenas como output gerado:
  `data/contextual_shadow_moneyline_evidence-fenzobot-contextual-2026-11.jsonl`.

## Isolamento

- `SHADOW_PREVIEW_ONLY`.
- Sem PAPER, GREEN, Telegram, email ou publicação operacional.
- Sem promoção automática.
- Sem alteração dos pesos treinados ou da probabilidade devido ao mercado.

## Validação exigida

- Export determinístico da release e fingerprint.
- Intervalo contém a previsão central e todos os cenários leave-one-family-out.
- Rastreabilidade de subfatores presente nas cinco famílias.
- Evidência Moneyline exclui o próprio jogo e partidas futuras.
- Todas as linhas de handicap são preservadas; três ficam destacadas.
- Dependência de família fica visível e impede formulação de mercados.
- Suite completa de testes e revisão dos mesmos jogos de controlo após merge.
