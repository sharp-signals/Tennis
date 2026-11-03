# Equações internas contextuais v1 — força estrutural e superfície

**CHANGE-ID:** CHANGE-2026-11-02-175  
**Estado:** candidato SHADOW; sem efeito no relatório, pricing ou PAPER

## Finalidade

Esta fase transforma factos já recolhidos em sinais internos reproduzíveis.
Não define ainda o peso final das famílias e não calcula fair odd. Os parâmetros
são hipóteses humanas transparentes que terão de passar replay cronológico.

## Força estrutural

O nível atual é a âncora. Ranking e pontos são tratados como duas leituras
dependentes da mesma realidade e, por isso, são combinados antes de qualquer
contribuição familiar.

- diferenças próximas como #40 contra #60 ficam numa zona praticamente neutra;
- separações como top 10 contra #200 crescem de forma não linear e limitada;
- trajetória de 6/12 meses pode ajustar, mas nunca substituir, o nível atual;
- um pico histórico não dá voto direto;
- um antigo top 30 agora #110 só recebe pequeno reconhecimento de recuperação
  quando existe trajetória recente positiva e atividade suficiente;
- inatividade reduz a confiança nessa recuperação.

Os valores da zona neutra, saturação e limites de ajuste ficam gravados na
própria saída para poderem ser auditados e recalibrados.

## Superfície e condições

A leitura começa pelo histórico bilateral no piso. As amostras são encolhidas
para 50% quando pequenas, evitando conclusões fortes com 10 ou 18 jogos.

Indoor/outdoor e velocidade são amostras sobrepostas ao piso. A equação escolhe
o contexto factual mais específico e usa-o apenas para modificar o baseline;
não soma piso + indoor + velocidade como três votos. A transição de piso é um
ajuste pequeno e limitado.

Esta primeira equação ainda não incorpora hold, break, resposta e recuperação
por condição. A saída marca expressamente essa extensão como pendente. Esses
dados só poderão entrar quando existir ownership que impeça reutilizá-los
também como voto completo na família serviço/resposta.

## Garantias

- mercado ausente;
- nenhuma alteração no motor atual;
- dados em falta não viram zero;
- sinais limitados entre -1 e +1;
- parâmetros expostos;
- testes de monotonicidade, regressos, amostra pequena, sobreposição de
  condições e transição.

## Próximo passo

As duas equações estão agora ligadas ao replay cronológico SHADOW sem substituir
as features anteriores. O comparador usa exatamente os mesmos alvos do holdout
para o perfil legado e o perfil contextual, separadamente em ATP, WTA e
Challenger. A direção dos novos sinais não pode ser invertida pela calibração.

O passo seguinte é executar o replay completo sobre a fonte histórica saudável,
registar cobertura, log loss, Brier e calibração, e rever os casos-limite. Só
depois se decide que curvas sobrevivem e com que incerteza.
