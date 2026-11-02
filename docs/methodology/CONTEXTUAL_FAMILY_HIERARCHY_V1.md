# Hierarquia contextual das famílias v1

**CHANGE-ID:** CHANGE-2026-11-02-175  
**Estado:** contrato metodológico executável; ainda sem promoção a produção

## Decisão central

O Fenzobot deixa de tratar as cinco famílias como cinco pesos fixos que o
histórico pode ordenar livremente. A lógica de ténis define o papel de cada
família; o histórico apenas afina as curvas, a dimensão do efeito e a
incerteza dentro desses limites.

Isto não significa dar percentagens arbitrárias a cada família. A hierarquia é
ordinal e contextual: primeiro pergunta-se se a família é aplicável ao jogo,
depois mede-se a diferença, a amostra e a fiabilidade. Uma família pode valer
zero num jogo e ser muito relevante noutro.

## Hierarquia aprovada

| Nível | Família | Papel prático |
|---:|---|---|
| 1 | Forma recente ajustada | Pilar principal: forma de 90 dias, competitividade, qualidade de vitórias e derrotas, recência e transferência entre circuitos. |
| 1 | Força estrutural | Pilar de contexto: ranking/pontos por patamar, trajetória, nível histórico recente e inatividade. Não é reputação nem escala linear. |
| 2 | Superfície e condições | Amplificador contextual: piso, indoor/outdoor, velocidade de hard, transição e performance completa nesse contexto. |
| 3 | Matchup e H2H | Modificador opcional e limitado: amostra, recência, mesmo piso/condições, evolução e interação de estilos. |
| 4 | Serviço e resposta | Modificador secundário e limitado. Só ganha relevância em matchups específicos com amostra bilateral suficiente. |

Os dois níveis 1 não são uma ordem rígida entre si. A forma recente responde
«como está a competir agora»; a força estrutural responde «qual é o seu nível
competitivo representativo». Devem dialogar e qualquer conflito fica visível.

## Conteúdo interno

### Forma recente ajustada

- resultados nos 90 dias anteriores ao cutoff;
- margem/competitividade em sets e games;
- força absoluta dos adversários nas vitórias;
- derrotas contra adversários fortes, equivalentes ou claramente inferiores;
- repetição do padrão, recência e concentração num único torneio;
- transferência ATP, Challenger, qualifying e ITF sem os considerar contextos
  equivalentes.

Uma vitória Challenger pode transferir parcialmente para ATP 250/500. Uma má
sequência ATP continua relevante ao descer para Challenger, mas não determina
automaticamente o resultado.

### Força estrutural

- ranking e pontos atuais;
- diferença entre patamares competitivos, com curva não linear;
- trajetória de 6/12 meses e último nível observado;
- melhor nível recente factual, sem transformar pico antigo em força atual;
- inatividade/regresso quando factual.

Um #40 contra #60 tende a ter pouco efeito só pelo ranking. Um top 10 contra
#80 pode ter efeito material. Um antigo #30 agora #110 exige trajetória e
inatividade; não recebe automaticamente estatuto de #30.

### Superfície e condições

- superfície física;
- indoor/outdoor explícito;
- velocidade apenas quando hard está classificado;
- transição recente e tempo de adaptação;
- vitórias, hold, break, resposta, recuperação e qualidade de oposição nesse
  contexto.

Esta família não é sinónimo de ases ou serviço. Indoor rápido pode ser muito
relevante, mas só com contexto factual, amostra e perfil compatível. Os seus
subcomponentes formam uma única contribuição para impedir dupla contagem.

### Matchup e H2H

- zero confrontos confirmados conta como pesquisa feita, mas impacto zero;
- um único H2H global tem impacto mínimo;
- um único H2H recente e no mesmo piso pode ter impacto pequeno;
- 2–0 recente ou 4–1 consistente pode ser mais material;
- confrontos antigos, noutro piso/circuito ou antes de grande evolução dos
  jogadores recebem forte desconto;
- lateralidade e estilos só contam com evidência individual, não narrativa.

Nunca pode liderar sozinho a probabilidade.

### Serviço e resposta

- hold, break, pontos de serviço e pontos de resposta;
- baseline de carreira e desvio recente sem contar como duas confirmações;
- ajuste por piso, condições, adversários e interação de estilos;
- ativação material apenas quando o matchup torna estes dados relevantes.

Não pode compensar má forma forte, criar candidato sozinho nem ficar acima das
famílias principais por um coeficiente global aprendido.

## Dados em falta e certeza

- dados em falta não são empate, zero nem voto para o adversário;
- aumentam a incerteza e alargam a faixa de fair odd;
- ausência factual (`OBSERVED_NONE`) é cobertura concluída sem impacto;
- um índice visual 100/100 apenas por normalizar os fatores disponíveis fica
  proibido;
- a fair probability é sempre independente do mercado; a odd observada entra
  somente depois para calcular edge.

## Handicaps

Os handicaps continuam no produto, mas não reutilizam cegamente a
probabilidade moneyline. Cada linha precisa da sua probabilidade e intervalo.
Nos negativos preservam-se cobertura total e cobertura quando o jogador vence;
nos positivos destaca-se a cobertura total. O preço de entrada é uma etapa
posterior ao modelo do encontro.

## Resultado da auditoria ao SHADOW atual

O combinador existente é útil como benchmark, mas não cumpre esta metodologia:

1. aprende coeficientes globais fixos para as cinco famílias;
2. ainda não executa os gates contextuais acima;
3. em universos observados, serviço/resposta chegou a receber mais coeficiente
   do que forma recente;
4. a força estrutural usa no replay essencialmente o ranking atual, apesar de
   o módulo factual já guardar trajetória e inatividade;
5. superfície ainda não integra no replay indoor/outdoor, velocidade e
   transição de forma completa.

Por isso, o modelo permanece SHADOW e não deve orientar novas entradas. A
próxima fase é construir as equações internas condicionais de cada família e
só depois repetir o replay e a calibração.
