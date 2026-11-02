# Fenzobot — contrato metodológico do modelo contextual de fatores

**Estado:** DRAFT PARA REVISÃO HUMANA — não implementado

**CHANGE-ID:** CHANGE-2026-11-02-175

**Nível:** 3 — metodologia central, índice e futura probabilidade/fair odd

**Âmbito desta primeira versão:** arquitetura global e contrato detalhado da
família `forma_recente_ajustada`

## 1. Objetivo

Substituir o atual sistema de pesos-base quase fixos por um modelo em que cada
família de evidência decide primeiro se é aplicável ao jogo e só depois mede a
direção, a dimensão e a fiabilidade do sinal.

O modelo não deve perguntar apenas «quem lidera este fator?». Deve responder:

1. existe observação factual bilateral?
2. o fator é aplicável a este confronto?
3. qual é a dimensão material da diferença?
4. quão representativa e recente é a amostra?
5. a diferença continua relevante no piso, circuito e momento atuais?
6. a evidência já foi usada noutra família?
7. qual é a contribuição final, incluindo a possibilidade legítima de zero?

O mercado permanece totalmente fora da formação do índice, da probabilidade e
da fair odd. Só é consultado depois para comparação e cálculo experimental de
edge.

## 2. Diagnóstico do modelo atual

O motor atual possui mecanismos úteis — força da diferença, confiança de
amostra e caps por família — mas continua a partir de pesos-base fixos por
fator. Essa estrutura cria quatro limitações:

- o mesmo fator começa com importância semelhante em contextos muito
  diferentes;
- fatores correlacionados podem continuar a contar a mesma realidade por vias
  diferentes antes de atingirem o cap;
- pequenas diferenças podem ganhar influência apenas por existirem;
- «forma recente» é essencialmente win rate, enquanto qualidade das vitórias
  é uma peça separada e não existe uma peça equivalente para a qualidade das
  derrotas.

Exemplos como ranking #80 vs top 10, ranking #60 vs #40 ou H2H 1–0 servem para
explicar o problema, não para criar exceções com nomes ou thresholds ad hoc.
As regras têm de generalizar para qualquer jogador e qualquer torneio.

### 2.1 Inventário dos 23 fatores atuais

Este inventário descreve o destino metodológico proposto; não altera ainda o
código nem pressupõe que todos os fatores sobrevivam com contribuição própria.

| Fator atual | Peso-base atual | Família proposta | Questão a resolver |
|---|---:|---|---|
| `ranking` | 5 | força estrutural | escala não linear, patamar e representatividade atual |
| `ranking_evolucao` | 6,25 | força estrutural | separar trajetória real de oscilação curta |
| `nivel_adversario` | 7 | força/forma | impedir dupla contagem com qualidade de vitórias/derrotas |
| `forma_recente` | 7 | forma recente | deixar de ser apenas win rate simples |
| `qualidade_vitorias` | 8 | forma recente | ajustar por força à data, repetição e contexto |
| `sazonal` | 6 | forma/superfície | testar estabilidade e evitar narrativa por calendário |
| `servico_recente` | 5 | serviço/resposta | só bilateral, ajustado por adversário e condições |
| `servico_carreira` | 3,25 | serviço/resposta | baseline estrutural, não voto autónomo equivalente |
| `piso` | 8 | superfície/condições | distinguir afinidade estável de forma recente no piso |
| `velocidade_piso` | 10 | superfície/condições | ajustar todos os componentes do jogo, não apenas serviço |
| `indoor_outdoor` | 6 | superfície/condições | ativação contextual potencialmente forte |
| `mudanca_piso` | 5 | superfície/condições | modelar transferência e tempo de adaptação |
| `meteo` | 1 | superfície/condições | manter apenas com observação factual e efeito plausível |
| `h2h` | 6 | matchup/contexto | amostra, recência, evolução e consistência temporal |
| `h2h_piso` | 12 | matchup/contexto | não duplicar H2H global; um jogo tem sinal muito fraco |
| `matchup_maos` | 8 | matchup/contexto | efeito depende do histórico individual contra o perfil |
| `historico_torneio` | 6 | matchup/contexto | distinguir condições repetíveis de ruído do evento |
| `fadiga` | 3,75 | matchup/contexto | carga, descanso, duração e deslocação bilateral |
| `lesao` | 5 | matchup/contexto | só evidência factual; inatividade não prova lesão |
| `pressao_ronda` | 6 | matchup/contexto | ajustar por nível dos adversários e amostra |
| `recuperacao_sets` | 9 | matchup/contexto | evitar duplicar comeback e sets decisivos |
| `comeback_set1` | 7 | matchup/contexto | relevante sobretudo para dinâmica/live, validar no pré-live |
| `tiebreak` | 5 | matchup/contexto | alta variância; exigir shrinkage forte |

O novo componente `qualidade_derrotas` nasce dentro de
`forma_recente_ajustada`; não será inicialmente um 24.º voto autónomo. Vitórias,
derrotas e nível dos adversários serão componentes de uma única leitura de
performance ajustada.

## 3. Unidade de cálculo

O modelo deixa de somar diretamente «votos» independentes dos subfatores. Cada
família produz uma única contribuição líquida e auditável:

```text
contribuição_família =
    limite_família
  × aplicabilidade
  × magnitude
  × fiabilidade
  × atualidade
  × relevância_contextual
  × direção
```

Onde:

- `limite_família` define o máximo estrutural da família, a aprovar antes da
  implementação;
- `aplicabilidade` varia entre 0 e 1 e pode legitimamente ser zero;
- `magnitude` mede a dimensão material da diferença, não apenas quem lidera;
- `fiabilidade` reflete amostra, integridade, bilateralidade e qualidade da
  fonte;
- `atualidade` reduz observações antigas de acordo com a natureza do fator;
- `relevância_contextual` liga a observação ao piso, circuito, nível e formato
  do encontro atual;
- `direção` varia de -1 a +1 e permite vantagem, neutralidade ou sinal
  contraditório.

Estes termos têm de ser expostos no snapshot e no relatório. Um resultado não
pode depender de um multiplicador oculto.

## 4. Estados obrigatórios de qualquer subfator

Cada subfator deve terminar num destes estados distintos:

| Estado | Cobertura | Impacto |
|---|---:|---:|
| `OBSERVED_DIRECTIONAL` | conta | pode contribuir |
| `OBSERVED_NEUTRAL` | conta | zero |
| `OBSERVED_NONE` | conta quando a ausência é factual | zero |
| `NOT_APPLICABLE` | não penaliza cobertura aplicável | zero |
| `INSUFFICIENT_SAMPLE` | parcial/insuficiente | zero ou contribuição reduzida explicitamente |
| `MISSING_DATA` | não conta | zero e aumenta incerteza |
| `CONFLICTING_EVIDENCE` | conta | contribuição reduzida e conflito visível |

Exemplo: pesquisar H2H e confirmar que nunca se defrontaram é
`OBSERVED_NONE`, não `MISSING_DATA`. Conta como pesquisa concluída, mas não dá
vantagem a ninguém.

## 5. Famílias propostas

### 5.1 Força estrutural

Ranking atual, rating adversarial, nível habitual, pico relevante, trajetória
e contexto de regresso. Ranking não é uma escala linear:

- uma diferença numérica pequena dentro do mesmo patamar pode ter impacto
  praticamente nulo;
- uma separação clara entre patamares competitivos pode ser material;
- a posição atual deve ser contextualizada pela trajetória e pelo nível
  recente, sem substituir o ranking atual por reputação histórica;
- lesão, inatividade ou regresso podem explicar uma posição temporariamente
  pouco representativa, desde que exista evidência factual.

### 5.2 Forma recente ajustada

Resultados dos últimos 90 dias corrigidos pela qualidade dos adversários,
qualidade das vitórias e derrotas, recência, circuito, piso e competitividade.
É a primeira família a especificar em detalhe neste contrato.

### 5.3 Serviço e resposta ajustados

Hold, break, pontos ganhos no serviço e resposta, ajustados por adversário,
piso, condições e amostra. Não deve duplicar a mesma evidência quando os seus
efeitos alimentarem o matchup.

### 5.4 Superfície e condições

Superfície, velocidade, indoor/outdoor, transição de piso e adaptação. A
aplicabilidade pode variar fortemente: condições indoor específicas podem ser
muito importantes para certos perfis e quase neutras noutros.

### 5.5 Matchup e contexto competitivo

H2H contextual, lateralidade, interação de estilos, fadiga, condição física,
pressão da ronda, formato e histórico relevante no torneio. H2H deve considerar
amostra, recência, superfície, evolução dos jogadores e consistência da
direção; nunca é apenas o resultado agregado da carreira.

## 6. Contrato v0 da forma recente ajustada

### 6.1 Janela e corte temporal

- janela factual principal: 90 dias anteriores ao início previsto do jogo;
- só entram partidas terminadas e conhecidas antes do cutoff pré-jogo;
- a janela é temporal, não «últimos N jogos», embora o relatório possa mostrar
  adicionalmente os últimos dez para leitura humana;
- partidas da ronda imediatamente anterior entram se já estiverem terminadas
  e persistidas antes do cutoff;
- a função de decaimento dentro dos 90 dias será escolhida por replay
  cronológico; até lá não se fixa arbitrariamente uma meia-vida.

### 6.2 Evidência por partida

Para cada partida recente devem ser preservados, quando conhecidos:

- data e cutoff ex ante;
- resultado;
- adversário e identidade canónica;
- ranking/rating de ambos na data da partida, não apenas o ranking atual;
- trajetória conhecida nessa data;
- circuito, tier, ronda e formato;
- superfície, indoor/outdoor e velocidade quando factual;
- resultado em sets e games;
- condição de retirada, walkover ou abandono;
- fonte, integridade e campos em falta.

Walkovers não contam como vitória/derrota competitiva. Retiradas exigem regra
própria e não podem ser tratadas silenciosamente como uma partida normal.

A implementação isolada `build_recent_form_observations` concretiza este
contrato factual sem produzir score. Para ranking, preserva uma magnitude
contínua `log(ranking_adversário / ranking_jogador)`: positiva quando o jogador
estava melhor classificado e negativa quando enfrentava alguém melhor
classificado. A qualidade de vitória/derrota exposta nesta fase é apenas a
magnitude factual do desvio perante esse contexto de ranking; não é ainda uma
probabilidade, contribuição ou peso.

### 6.3 Qualidade das vitórias

Uma vitória tem valor contextual superior quando:

- ocorre contra adversário estruturalmente mais forte;
- contraria uma expectativa baseada apenas em dados ex ante independentes do
  mercado;
- acontece em contexto semelhante ao encontro atual;
- é recente e competitivamente válida;
- não é um evento isolado numa amostra contraditória.

Ganhar a vários adversários fortes tem mais valor do que uma vitória isolada.
Repetição no mesmo torneio pode representar forma real, mas não deve ser
contada como várias fontes independentes.

### 6.4 Qualidade das derrotas

Uma derrota não é automaticamente sinal negativo da mesma intensidade.

- perder com um adversário claramente mais forte pode ser quase neutro;
- perder com adversário de força semelhante é um sinal negativo moderado,
  dependente da competitividade;
- perder com adversário claramente inferior é um sinal negativo material;
- várias derrotas recentes abaixo da expectativa formam um padrão mais forte
  do que uma ocorrência isolada;
- derrota competitiva e derrota desequilibrada não são equivalentes;
- ranking nominal inferior não basta: deve ser contextualizado por rating,
  trajetória, pico recente, regresso e circuito.

Assim, «perdeu para ranking inferior» é uma observação inicial. A penalização
final depende de quão inferior era realmente o adversário naquele momento e da
qualidade da evidência disponível.

### 6.5 Transferência entre circuitos

ATP principal e Challenger não são contextos equivalentes.

- boa forma em Challenger pode transferir parcialmente para ATP 250/500, mas
  com desconto de contexto;
- boa forma ATP é evidência relevante ao descer para Challenger, sem garantir
  adaptação imediata;
- resultados ITF/qualifying/main draw exigem coeficientes de transferência
  explícitos e auditáveis;
- o próprio Challenger mantém família e calibração separadas quando a
  cobertura ou o regime competitivo o justificar.

### 6.6 Piso e condições

A forma global de 90 dias é decomposta em:

- componente geral recente;
- componente no mesmo piso;
- componente em condições próximas, quando a classificação de velocidade e
  indoor/outdoor for factual;
- penalização de transferência quando a forma vem de contexto materialmente
  diferente.

Estas componentes pertencem à mesma família de forma e não podem voltar a ser
somadas integralmente como sinais independentes na família de superfície.

### 6.7 Amostra e robustez

A fiabilidade deve aumentar com o número de partidas válidas e a diversidade
de adversários, mas não linearmente. Deve também diminuir com:

- identidades ou rankings históricos não resolvidos;
- concentração excessiva num único torneio ou adversário;
- mistura de circuitos sem transferência modelada;
- muitas retiradas ou partidas incompletas;
- fontes contraditórias.

Uma amostra pequena pode gerar uma direção fraca e visível, nunca falsa
certeza.

### 6.8 Saída da família

A família deve devolver, por jogador e para o confronto:

```json
{
  "window_days": 90,
  "cutoff_utc": "...",
  "matches_observed": 0,
  "matches_usable": 0,
  "raw_win_rate": null,
  "opponent_adjusted_performance": null,
  "quality_wins_component": null,
  "quality_losses_component": null,
  "surface_transfer_component": null,
  "circuit_transfer_component": null,
  "recency_component": null,
  "direction": null,
  "magnitude": null,
  "reliability": null,
  "applicability": null,
  "family_contribution": null,
  "reason_codes": [],
  "source_lineage": []
}
```

Os campos nulos permanecem nulos. A saída não pode inferir dados inexistentes.

## 7. H2H: regra estrutural preliminar

H2H pertence ao matchup, não à força estrutural. A sua contribuição deve ser
função de:

- número de encontros utilizáveis;
- recência;
- coincidência de piso e condições;
- evolução relativa desde cada encontro;
- formato e circuito;
- domínio ou competitividade dos resultados;
- consistência temporal da direção.

Um único encontro pode ter contribuição muito baixa se for recente e no mesmo
piso. Um único encontro antigo ou num contexto diferente deve aproximar-se de
zero. Ausência factual de H2H é cobertura sem impacto.

## 8. Separação entre índice, probabilidade e mercado

- o índice descreve o balanço de evidência observada; não é automaticamente
  uma probabilidade;
- a transformação do vetor de famílias em probabilidade precisa de calibração
  cronológica própria;
- missing data reduz fiabilidade e alarga a faixa, não empurra o resultado para
  qualquer jogador;
- um índice visual `100/100` fica proibido como consequência de normalizar
  apenas fatores ativos; a apresentação deve preservar espaço para evidência
  não observada e incerteza;
- o mercado só entra após a fair probability/fair odd estar congelada.

## 9. Proteção contra dupla contagem

Antes de implementar qualquer fator, deve existir uma matriz de dependências.
Exemplos a auditar:

- forma recente, qualidade de vitórias, qualidade de derrotas e nível de
  adversário;
- piso, velocidade, indoor/outdoor e serviço/resposta por condição;
- H2H, H2H no piso e matchup de estilos;
- recuperação após primeiro set, sets decisivos e resiliência;
- ranking, evolução do ranking e rating adversarial.

Subfatores podem ser mostrados separadamente no relatório, mas a contribuição
agregada da família não pode contar a mesma partida ou estatística várias
vezes como evidência independente.

## 10. Processo de construção e validação

Cada família seguirá o mesmo ciclo:

1. inventário de inputs e cobertura real;
2. contrato de estados e reason codes;
3. equação determinística isolada;
4. testes sintéticos de monotonicidade e limites;
5. replay histórico ex ante;
6. holdout cronológico ATP, WTA e Challenger;
7. comparação com baseline simples e mercado de-vig;
8. revisão humana dos casos-limite;
9. aprovação antes de integrar a família seguinte.

O histórico pode calibrar suavemente curvas e limites, mas não deve descobrir
centenas de parâmetros livres nem otimizar diretamente o ROI passado.

## 11. Critérios de aceitação da forma recente

A primeira implementação só poderá ser integrada se demonstrar que:

- uma derrota contra adversário claramente mais forte penaliza menos do que
  uma derrota comparável contra adversário claramente inferior;
- duas derrotas iguais em ranking nominal podem ter impacto diferente quando
  trajetória e força histórica diferem;
- uma sequência de derrotas abaixo da expectativa pesa mais do que um caso
  isolado;
- uma vitória Challenger não recebe automaticamente o mesmo valor de uma
  vitória ATP principal;
- recência aumenta relevância sem apagar completamente o restante da janela;
- mudanças de piso/circuito aplicam transferência, não equivalência total;
- dados em falta nunca são convertidos em derrota, empate ou zero;
- o cálculo é reproduzível com o mesmo cutoff e a mesma versão;
- nenhuma odd de mercado participa no cálculo.

## 12. Decisões ainda por aprovar

Este contrato fixa a arquitetura e a janela de 90 dias. Permanecem em aberto,
para replay e decisão humana:

- limites máximos das cinco famílias;
- curva exata de ranking/rating e patamares competitivos;
- função de decaimento dentro dos 90 dias;
- coeficientes de transferência entre ATP, Challenger, qualifying e ITF;
- tratamento quantitativo de retiradas;
- medida de competitividade por sets/games;
- transformação calibrada do vetor de famílias em probabilidade.

Nenhum destes valores será escolhido apenas por conveniência de implementação.

## 13. Auditoria factual inicial — 2 de novembro de 2026

Foi executada uma auditoria read-only com cutoff em
`2026-11-02T12:00:00Z`, janela de 90 dias e exclusão integral do dia do cutoff
por as fontes terem precisão diária.

### 13.1 Fonte operacional primária

| Universo | Partidas | Resultado | Ranking bilateral | Score completo | Contexto completo |
|---|---:|---:|---:|---:|---:|
| ATP principal | 823 | 100,0% | 98,3% | 97,0% | 95,3% |
| WTA principal | 644 | 100,0% | 99,1% | 96,3% | 95,3% |
| Challenger | 1 911 | 100,0% | 99,2% | 95,1% | 94,2% |

`Contexto completo` exige identidade/resultado, rankings bilaterais, piso,
circuito, tier, ronda e score completo. A cobertura demonstra que é viável
construir qualidade de vitórias e derrotas sem inventar dados na grande maioria
dos casos.

### 13.2 Fallbacks locais

- ATP e Challenger Valuebetennis têm resultado, piso, ronda e circuito, mas
  não expõem rankings históricos no esquema atual;
- o cache local WTA tennis-data termina em 3 de agosto de 2026 e, por isso, não
  tem partidas dentro da janela iniciada em 4 de agosto;
- um fallback não pode herdar a classificação de qualidade calculada pela
  fonte primária se os factos necessários não estiverem presentes.

Consequência metodológica: em falha da fonte primária, o sistema pode mostrar
forma bruta quando factual, mas `qualidade_vitorias`, `qualidade_derrotas` e
performance ajustada ao adversário ficam N/D ou usam apenas um enriquecimento
ex ante com proveniência explícita. Nunca são reconstruídas por reputação ou
ranking atual.
