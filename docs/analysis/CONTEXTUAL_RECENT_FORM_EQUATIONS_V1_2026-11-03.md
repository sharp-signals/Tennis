# Forma recente contextual — comparação das equações v1

**Data:** 03/11/2026  
**CHANGE-ID:** CHANGE-2026-11-02-175  
**Estado:** observacional; promoção bloqueada

## Modelos comparados

As camadas foram definidas pela lógica de ténis antes da medição histórica:

1. `recent_v0`: saldo de resultados nos 90 dias anteriores;
2. `recent_v1`: acrescenta competitividade pela margem de games;
3. `recent_v2`: acrescenta qualidade absoluta dos adversários vencidos;
4. `recent_v3`: acrescenta contexto dos adversários nas derrotas.

O histórico apenas ajustou coeficientes dentro desta ordem e avaliou se cada
adição melhorava o modelo. O mercado não foi utilizado.

## Holdout emparelhado

| Circuito | Modelo | Jogos | Log loss | Brier | Acerto | ECE |
|---|---|---:|---:|---:|---:|---:|
| ATP | resultados | 4 430 | 0,670360 | 0,238646 | 60,14% | 0,025818 |
| ATP | + competitividade | 4 430 | 0,663175 | 0,235149 | 60,47% | 0,018381 |
| ATP | + qualidade das vitórias | 4 430 | 0,659009 | 0,233391 | 60,72% | 0,016431 |
| ATP | + contexto das derrotas | 4 430 | 0,655743 | 0,232042 | 60,99% | 0,013610 |
| WTA | resultados | 4 019 | 0,659903 | 0,233791 | 61,56% | 0,024061 |
| WTA | + competitividade | 4 019 | 0,654377 | 0,231173 | 61,98% | 0,020635 |
| WTA | + qualidade das vitórias | 4 019 | 0,646713 | 0,227645 | 62,70% | 0,011268 |
| WTA | + contexto das derrotas | 4 019 | 0,639120 | 0,224302 | 62,93% | 0,014413 |

Menor log loss, Brier e ECE são melhores. O acerto isolado não decide a
promoção, porque o objetivo final exige probabilidades bem calibradas.

## Ganho incremental com intervalo de confiança de 95%

| Circuito | Adição | Ganho de log loss | IC 95% | Veredicto |
|---|---|---:|---:|---|
| ATP | competitividade | 0,007185 | 0,004112–0,010257 | confirmado |
| ATP | qualidade das vitórias | 0,004166 | 0,001172–0,007159 | confirmado |
| ATP | contexto das derrotas | 0,003267 | 0,001036–0,005497 | confirmado |
| WTA | competitividade | 0,005526 | 0,002882–0,008169 | confirmado |
| WTA | qualidade das vitórias | 0,007664 | 0,004053–0,011275 | confirmado |
| WTA | contexto das derrotas | 0,007593 | 0,005379–0,009808 | confirmado |

Todos os intervalos ficaram inteiramente acima de zero. As três camadas
acrescentaram informação fora da amostra nos dois circuitos.

## Limites da conclusão

- Os coeficientes ajustados não são os pesos finais da família. Resultado e
  margem de games são correlacionados; por isso o tamanho isolado de cada
  coeficiente não redefine a hierarquia humana.
- A qualidade das derrotas ainda não pode ser promovida diretamente. A
  equação final precisa de uma barreira assimétrica: perder contra oposição
  forte pode reduzir a penalização, mas nunca produzir crédito positivo
  autónomo; perder contra oposição fraca pode aumentar a penalização.
- A forma no mesmo piso ficou fora desta equação para não duplicar a família
  de superfície e condições.
- Ausência de uma componente é incerteza, não voto neutro inventado.
- Challengers não participaram na escolha e continuam observacionais.

## Decisão

As quatro componentes avançam para a construção de uma equação contextual v2.
A próxima prova deve comparar a versão estatística livre com uma versão que
aplique explicitamente a barreira assimétrica às derrotas e limites de
duplicação entre resultados e margem. Produção, PAPER, fair odds, relatórios e
bot automático permanecem inalterados.
