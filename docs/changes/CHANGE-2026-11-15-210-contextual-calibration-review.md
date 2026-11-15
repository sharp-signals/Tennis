# CHANGE-2026-11-15-210 — auditoria de calibração por consenso

## Implementation Brief

### Objetivo

Verificar, sem usar o mercado na previsão, se o modelo contextual comprime em
excesso favoritos apoiados por várias famílias; eliminar mensagens públicas
contraditórias e resolver a fase de grupos das Finals.

### Hipótese e baseline

- Hipótese: jogos com 5/5 famílias alinhadas podem estar sistematicamente
  subconfiantes.
- Baseline: release congelada `FENZOBOT_CONTEXTUAL_2026_11`, holdout cronológico
  já definido no contrato e calibrador selecionado apenas por log-loss.
- Métricas: probabilidade média, taxa real de vitória e diferença em pontos
  percentuais, separadas por ATP/WTA, consenso, intensidade das famílias
  principais e faixa de fair odd.

### Alterações autorizadas

1. Auditoria read-only do holdout, sem refit e sem odds de mercado.
2. Um edge matemático contrarian sem apoio familiar deixa de surgir no
   cabeçalho como `VALOR CONSERVADOR`.
3. A qualidade passa a dizer que 5/5 famílias foram calculadas sem prometer que
   todos os fatores internos têm dados.
4. `round_id=8` nas ATP/WTA Finals é apresentado como fase de grupos inferida
   pelo torneio.

### Preservado

- Pesos, probabilidades, fair odds, intervalos e previsões congeladas.
- Mercado fora da construção da fair odd.
- SHADOW sem PAPER, GREEN ou execução automática.

### Critério de decisão

Só será proposta uma nova curva de calibração se o replay cronológico mostrar
subconfiança material, estável e com amostra suficiente. Casos individuais ou
a proximidade ao mercado não autorizam alteração do modelo.

### Resultado do replay cronológico

O replay reproduziu exatamente os holdouts congelados usados pela release:

- ATP: 5 269 jogos; previsão média do favorito 64,77%, resultado real 65,33%
  (diferença +0,56 p.p.).
- WTA: 4 896 jogos; previsão média do favorito 64,90%, resultado real 66,52%
  (diferença +1,63 p.p.).
- ATP com 5/5 famílias alinhadas: 949 jogos; 74,62% previstos e 76,40% reais
  (+1,78 p.p.).
- WTA com 5/5 famílias alinhadas: 576 jogos; 75,00% previstos e 75,69% reais
  (+0,70 p.p.).

As diferenças por intensidade não são consistentes entre ATP e WTA. Há alguns
segmentos com aparente subconfiança, mas outros de intensidade adjacente mudam
de sinal. A amostra global não demonstra compressão suficiente para autorizar
uma correção transversal ou manual da fair odd.

### Decisão

`NO_RECALIBRATION`: preservar pesos, calibrador identidade, probabilidades e
fair odds. As discrepâncias dos relatórios analisados ficam registadas para
monitorização prospetiva fora da amostra. Foram aplicadas apenas correções de
linguagem, transparência e identificação da ronda, sem aproximar a previsão ao
mercado.
