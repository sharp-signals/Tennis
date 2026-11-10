# Trabalho pendente do modelo contextual — 2026-11-04

## Ordem aprovada

1. Calibrar a probabilidade central e a incerteza.
2. Congelar a transformação em fair odd independente do mercado.
3. Validar prospetivamente em SHADOW.
4. Redesenhar o relatório e a apresentação visual das famílias.
5. Rever integração, segurança e eventual reativação operacional.
6. **Só no fim**, atualizar o ficheiro Google Sheets/Excel de Histórico &
   Aprendizagem.

## Estado atual

- runtime e previsão market-free: concluídos em SHADOW;
- liquidação de resultados: concluída e a acumular observações;
- benchmark pós-previsão e contrato pré-declarado: implementados em
  `CHANGE-2026-11-04-177`, ainda sujeitos a CI/revisão;
- contrato e protótipo visual isolado do relatório: implementados em
  `CHANGE-2026-11-04-178`, sujeitos a CI e revisão visual;
- calibração final, integração operacional do relatório e Excel: ainda
  pendentes.

## Atualização final do Excel

Quando modelo, fair odds e relatório estiverem estabilizados, acrescentar sem
reescrever o histórico existente:

- base histórica do modelo separada de PAPER, GREEN e Guerra Selection;
- cobertura real de cada família por ATP/WTA e superfície;
- jogos utilizáveis, excluídos e respetivos motivos;
- coeficientes e versão do modelo;
- calibração por faixa de probabilidade e intervalos de incerteza;
- evolução cronológica e qualidade da evidência.

Os cerca de 53 mil jogos históricos são observações de aprendizagem, não
relatórios nem entradas. Não devem contaminar as métricas operacionais.
