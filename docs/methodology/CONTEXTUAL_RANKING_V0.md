# Ranking contextual v0 — contrato factual

**CHANGE-ID:** CHANGE-2026-11-02-175

**Estado:** observacional; sem ligação ao índice, pricing ou relatórios

## Problema atual

O motor em produção considera o ranking relevante quando existe uma diferença
de pelo menos cinco posições ou quinze por cento nos pontos. Depois converte
essa decisão diretamente em força. Estes limites fixos não distinguem de forma
suficiente situações competitivamente diferentes e misturam observação com
decisão.

## Objetivo desta fase

Preservar os factos necessários para que a curva futura seja calibrada por
replay, sem escolher já patamares ou pesos:

- ranking e pontos atuais;
- diferença absoluta e razão logarítmica bilateral;
- melhor ranking realmente observado no histórico disponível;
- melhor ranking observado nos últimos 365 dias;
- último ranking conhecido antes do cutoff;
- âncoras ex ante aproximadas de seis e doze meses;
- mudança contínua de força desde cada âncora;
- dias desde o último jogo, quando disponíveis;
- cobertura atual, histórica e bilateral.

«Melhor ranking observado» não é apresentado como máximo oficial de carreira:
é apenas o melhor valor encontrado na fonte histórica disponível.

## Casos que ficam distinguíveis

- #40 contra #60 preserva uma diferença pequena sem receber automaticamente
  um voto;
- #10 contra #200 produz uma separação contínua muito superior;
- um atual #110 anteriormente observado como #30 expõe simultaneamente a
  posição atual, o nível histórico e a inatividade, sem assumir que continua a
  valer #30;
- ausência de histórico fica `CURRENT_ONLY`, nunca empate ou zero.

## Proteções

- só entram observações anteriores ao dia do cutoff;
- nenhum preço de mercado é lido;
- `score`, `leader` e `weight` permanecem explicitamente `None`;
- o módulo não é importado pelo motor de produção;
- ranking, trajetória e regresso ficam como componentes dependentes da mesma
  família para evitar dupla contagem futura.

## Próxima validação

Depois de a fonte histórica rica voltar a responder, será medida a cobertura
ATP/WTA/Challenger e executado replay cronológico. O replay deverá comparar a
curva contínua com baselines simples, avaliar regressos e trajetórias, e só
depois propor patamares competitivos ou impacto máximo.
