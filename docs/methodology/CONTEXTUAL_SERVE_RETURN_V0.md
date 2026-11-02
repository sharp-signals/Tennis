# Serviço e resposta v0 — contexto secundário

**CHANGE-ID:** CHANGE-2026-11-02-175

**Estado:** observacional; sem ligação ao índice, pricing ou relatórios

## Decisão metodológica

Serviço e resposta não são tratados como pilar equivalente à forma recente.
Por decisão conjunta do utilizador e do Hugo, esta família nasce como contexto
secundário e o replay pode concluir que o seu impacto geral deve ser muito
baixo ou zero.

Não pode, isoladamente:

- criar um sinal ou candidato;
- contrariar famílias primárias fortes;
- compensar má forma recente ou derrotas adversariais relevantes;
- entrar duas vezes por existir uma leitura de carreira e outra recente.

## Estrutura

A carreira serve apenas de baseline. A janela recente representa eventual
desvio desse baseline, não uma segunda confirmação independente. São
preservadas, quando factuais:

- percentagem de pontos ganhos no serviço;
- pontos ganhos no primeiro serviço;
- percentagem de hold;
- pontos ganhos na resposta;
- percentagem de break;
- amostras de pontos e jogos de serviço/resposta;
- cobertura e mediana do ranking dos adversários;
- leituras globais e no piso atual;
- janela recente de 90 dias.

As percentagens são reconstruídas a partir dos totais de pontos/jogos, nunca
pela média simples das percentagens de cada partida.

## Limites atuais

A força dos adversários fica preservada, mas ainda não é usada para declarar
uma estatística «ajustada». O estado correto é
`FACTS_AVAILABLE_NOT_YET_CALIBRATED`. Ajuste por adversário, piso e matchup só
será aceite depois de replay cronológico.

Retiradas são excluídas das métricas comparáveis. O dia do cutoff e o futuro
também ficam excluídos. Dados em falta permanecem N/D, nunca zero.

## Utilização futura provável

Esta família tende a ser mais útil em matchups específicos — por exemplo,
servidor muito forte em hard indoor contra resposta comprovadamente fraca — do
que como vantagem geral autónoma. Mesmo nesses casos, deve permanecer abaixo
da forma recente e depender de amostra e contexto suficientes.
