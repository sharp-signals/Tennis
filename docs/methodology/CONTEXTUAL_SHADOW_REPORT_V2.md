# Novo relatório contextual v2 — contrato visual SHADOW

## Objetivo

Transformar a previsão congelada num relatório curto, visual e rastreável sem
alterar o modelo, sem publicar relatórios operacionais e sem criar PAPER,
GREEN ou notificações.

## Hierarquia visual

1. contexto do jogo e identificação dos jogadores;
2. probabilidade, intervalo de 90% e fair odd independente;
3. benchmark de mercado recolhido **depois** da previsão;
4. Moneyline e handicaps para validação humana, quando calculáveis;
5. cobertura e qualidade da evidência;
6. direção e contributo das cinco famílias;
7. rastreabilidade técnica expansível.

## Regras de interpretação

- a probabilidade e a fair odd são lidas diretamente do ledger imutável;
- o renderer não recalcula previsões;
- o preço de mercado apenas calcula diferenças e retornos hipotéticos depois
  de existir uma previsão;
- `OBSERVED_NONE`, como ausência real de H2H após consulta, é diferente de
  `UNAVAILABLE` e não representa um voto artificial de 50%;
- a barra de cada família representa a parcela do movimento de logit daquele
  jogo, não uma probabilidade autónoma nem um peso fixo;
- dados em falta permanecem visíveis e alargam a incerteza definida pelo
  modelo;
- o resultado real pode ser associado para auditoria, mas nunca reescreve a
  página pré-jogo.
- a Moneyline é comparada diretamente com a fair odd independente;
- cada handicap usa contagens de margem congeladas antes do jogo e calcula a
  sua própria probabilidade de cobertura; a probabilidade Moneyline nunca é
  apresentada como se fosse a probabilidade da linha;
- handicap negativo destaca a cobertura quando o jogador vence; handicap
  positivo destaca a cobertura total;
- qualquer faixa de preço é condicional à confirmação da odd real da linha e
  nunca cria PAPER automaticamente.

## Distribuição

O workflow produz um artefacto privado descarregável. O diretório não entra no
perfil de publicação de dados, no site de relatórios nem no Telegram. A futura
integração operacional exige uma alteração própria e decisão humana explícita.
