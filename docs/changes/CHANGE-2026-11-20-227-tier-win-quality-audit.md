# CHANGE-2026-11-20-227 — auditoria do crédito das vitórias pela categoria

**Nível:** 2 — comportamento de reporting e rastreabilidade metodológica  
**Estado:** implementação  
**Âmbito:** SHADOW contextual ATP/WTA; sem alteração do pricing operacional

## Problema

O relatório apresentava `contextual_recent_tier_win_credit_v7` como
“Qualidade das vitórias ajustada ao nível”, mas não mostrava quais vitórias,
categorias e pesos temporais produziam o valor. A designação também podia ser
confundida com a qualidade do adversário, que é um fator separado.

O controlo Medvedev–Tiafoe de 20/11/2026 mostrou que o fator favorecia Tiafoe
sem permitir ao utilizador auditar diretamente a sequência de jogos.

## Decisão

1. Preservar a fórmula e a fair odd nesta alteração. Não promover uma nova
   combinação de categoria, ronda e adversário sem replay cronológico e
   validação fora da amostra.
2. Renomear a leitura pública para `Crédito das vitórias pela categoria`.
3. Persistir, dentro do audit trail da forma recente, todos os jogos da janela
   de 90 dias usados no denominador e os campos necessários para reprodução:
   data, torneio, ronda, adversário, resultado, categoria, peso temporal e
   crédito ponderado.
4. Mostrar no relatório as vitórias que contribuíram, separadas por jogador,
   explicando explicitamente que derrotas valem zero mas permanecem no
   denominador e que ronda/adversário são apenas contexto nesta versão.

## Comportamento preservado

- Mercado continua proibido na probabilidade e na fair odd.
- Janela de 90 dias e meia-vida temporal de 60 dias permanecem iguais.
- Escala de categoria e coeficientes calibrados permanecem iguais.
- Snapshots anteriores não são reescritos.
- SHADOW, PAPER e REAL permanecem isolados.

## Hipótese metodológica seguinte

Uma fórmula que combine categoria, ronda e adversário só poderá substituir a
atual se um replay cronológico demonstrar melhoria fora da amostra sem dupla
contagem com `Qualidade das vitórias`. Até essa prova, a informação adicional
é apenas auditoria factual e não altera o preço.

