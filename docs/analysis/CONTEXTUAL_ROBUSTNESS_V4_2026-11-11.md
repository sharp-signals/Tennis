# Fenzobot — robustez contextual v4

## Resultado

A primeira tentativa de ranking v7 substituía demasiada informação da v6 e
foi rejeitada no WTA. Não foi promovida. A formulação final preserva toda a
base v6 nos casos normais e acrescenta três interações que só ficam ativas
quando existe um regresso comprovado após hiato longo:

- contração específica do ranking atual;
- contração específica dos pontos atuais;
- fricção entre o nível atual e o nível típico pré-hiato.

O nível antigo é contexto calibrado, nunca restauração automática de força.

## Replay cronológico pareado

| Circuito | Holdout | Ganho log-loss vs v6 | IC 95% | Decisão |
|---|---:|---:|---:|---|
| ATP | 5 269 | +0,001167 | +0,000331 a +0,002003 | suportado |
| WTA | 4 896 | +0,001621 | +0,000342 a +0,002900 | suportado |

O mercado não entrou no treino, na probabilidade ou na escolha da versão.

## Leitura de robustez

O teste leave-one-family-out deixa de ser binário. Uma inversão marginal perto
de 50/50 é apresentada como sensibilidade; uma dependência material reduz a
confiança; só uma dependência crítica bloqueia a formulação de mercados. Os
limiares são regras de governação da leitura e não coeficientes do modelo.

## Cobertura e relatório

Cada família passa a ser `SOLID`, `PARTIAL`, `OBSERVED_NEUTRAL` ou
`UNAVAILABLE`. A vista principal usa impacto em pontos percentuais e linguagem
ligeira/moderada/forte/muito forte. Logits e features ficam apenas no detalhe
técnico expansível.

## Isolamento

Release SHADOW apenas. Não cria PAPER, GREEN, Telegram, email ou decisão
operacional. As gerações anteriores permanecem imutáveis e auditáveis.
