# Relatório vNext — contrato de apresentação

## Objetivo

Quando a calibração cronológica das cinco famílias estiver concluída, o
relatório deve deixar de apresentar uma parede de fatores e pontos. A primeira
leitura tem de responder, sem esconder incerteza, a três perguntas:

1. Qual é a estimativa independente do Fenzobot?
2. Porque chegou a essa estimativa?
3. Só depois: existe diferença utilizável face ao preço do mercado?

Este documento define a apresentação futura. Não altera o HTML atual, o
pricing, o PAPER ou as notificações.

## Camada 1 — decisão e pricing

Uma única caixa no topo deve mostrar:

- probabilidade Fenzobot central e intervalo calibrado;
- fair odd central e intervalo correspondente;
- qualidade e cobertura da evidência;
- preço de mercado observado, apresentado apenas depois da estimativa própria;
- edge central, edge conservador e estado de validação;
- decisão operacional em linguagem direta: candidato, observar ou sem entrada.

Índice, probabilidade e cobertura são conceitos diferentes e nunca podem
partilhar o mesmo rótulo. A ausência de dados deve alargar a incerteza; nunca
deve transformar-se em 50/50 nem permitir `100/100`.

## Camada 2 — as cinco famílias

O corpo principal deve conter apenas cinco linhas ou cartões:

1. **Forma recente ajustada** — família principal;
2. **Força estrutural** — contexto estrutural principal;
3. **Superfície e condições** — família contextual;
4. **Matchup e confronto direto** — contexto de matchup;
5. **Serviço e resposta** — contexto secundário.

Cada linha mostra apenas:

- direção observada, se existir;
- uma frase com a razão principal;
- qualidade/fiabilidade da evidência;
- estado factual: observado, sem ocorrência, amostra insuficiente, não
  aplicável, dados em falta ou conflito.

O relatório não deve mostrar 20–23 caixas como se fossem votos independentes.
Subcomponentes da mesma família não são somados visualmente nem apresentados
como vantagens autónomas.

## Camada 3 — detalhe auditável

Cada família pode ser expandida para revelar:

- componentes factuais;
- amostras, datas e cutoff pré-jogo;
- fontes e linhagem;
- exclusões e razão de cada exclusão;
- conflito interno e modificadores contextuais;
- transformação e coeficientes apenas depois de estes serem calibrados.

Esta camada serve auditoria e diagnóstico. Não deve poluir a leitura inicial.

## Estados que a interface deve distinguir

- **Dados observados, ainda sem transformação calibrada** não é empate.
- **Pesquisa concluída sem ocorrência**, como H2H inexistente, conta para
  cobertura factual mas não dá vantagem.
- **Dados em falta** aumentam a incerteza.
- **Amostra insuficiente** permanece visível e não é convertida em zero.
- **Evidência contraditória** não é anulada por média silenciosa.
- **Não aplicável** não penaliza a cobertura aplicável.

## Telegram e email

O resumo deve caber numa leitura curta:

- jogo e seleção potencial;
- fair odd e intervalo;
- preço observado e edge conservador;
- qualidade dos dados;
- duas razões principais;
- um risco ou conflito principal;
- ligação para a auditoria completa.

## Regra de implementação

Esta reformulação só entra no relatório depois de replay cronológico, calibração
fora da amostra e validação explícita. Até lá, o orquestrador produz apenas uma
vista observacional de cinco famílias, sem score, probabilidade ou fair odd.
