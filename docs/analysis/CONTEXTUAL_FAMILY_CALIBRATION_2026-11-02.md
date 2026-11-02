# Calibração das equações internas — 02/11/2026

## Estado

As cinco famílias foram calibradas separadamente para ATP, WTA e Challenger.
Todas superaram a previsão constante em validação e no holdout. Continuam
isoladas entre si e sem efeito em produção.

## Resultado no holdout

O ganho representa a redução de log loss face a prever sempre a frequência
base. Quanto maior, mais informação probabilística acrescentou a família.

| Família | ATP ganho / acerto | WTA ganho / acerto | Challenger ganho / acerto |
|---|---:|---:|---:|
| Forma recente | 0,0374 / 61,18% | 0,0527 / 62,92% | 0,0241 / 59,88% |
| Força estrutural | **0,0660 / 64,61%** | **0,0695 / 64,20%** | **0,0435 / 61,97%** |
| Superfície/condições | 0,0324 / 60,94% | 0,0409 / 63,15% | 0,0312 / 60,44% |
| Matchup/H2H | 0,0190 / 60,27% | 0,0165 / 59,38% | 0,0073 / 57,02% |
| Serviço/resposta | 0,0415 / 63,02% | 0,0478 / 63,95% | 0,0352 / 61,51% |

Estes acertos dizem respeito apenas aos jogos cobertos por cada família. Não
são o desempenho do futuro modelo combinado.

## Leitura das equações

### Forma recente

A margem de games nos últimos 90 dias recebeu a maior contribuição interna nos
três circuitos. O simples balanço vitória/derrota ficou muito pequeno depois de
considerar competitividade e adversários. Qualidade das vitórias e derrotas
permanece útil, mas com menor intensidade nos Challengers.

### Força estrutural

O ranking atual transformado foi suficiente para a primeira equação. A mudança
desde a última observação ficou fora porque já falhara no treino e validação.
Isto não elimina uma futura trajetória de 30/90/180/365 dias.

### Superfície e condições

O registo histórico no piso teve maior contribuição do que a forma de 90 dias
no mesmo piso. Ambas permanecem na mesma família e não são dois votos.

### Matchup/H2H

H2H global foi mais estável no ATP e WTA. H2H no mesmo piso acrescentou pouco
no WTA, mas foi mantido porque a regularização escolhida em validação não o
eliminou. Nos Challengers, o ganho total é reduzido e a família continuará
opcional, sem penalizar jogos sem confrontos anteriores.

### Serviço e resposta

A família foi preditiva isoladamente, especialmente no WTA. Isto não prova que
deva receber peso elevado: serviço, hold e resposta também refletem força,
forma e piso. A combinação entre famílias terá de reduzir esta duplicação. A
governação continua a classificá-la como secundária.

## Nota sobre os coeficientes

Os coeficientes operam sobre componentes limitadas e escaladas. Não são
percentagens nem pesos diretamente comparáveis com os pontos do relatório
antigo. Só a futura combinação pode dizer quanto cada família acrescenta depois
de conhecer as restantes.

## Próximo passo

Construir a combinação de segundo nível com previsões fora da amostra dentro
do desenvolvimento:

1. gerar probabilidades de cada família sem a família ver o próprio alvo;
2. combinar essas cinco saídas com regularização;
3. manter ausência, conflito e fiabilidade como informação explícita;
4. avaliar uma única vez no holdout congelado;
5. só depois converter a probabilidade final em fair odd.

Odds de mercado continuam excluídas de todo este processo.
