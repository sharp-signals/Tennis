# Dry-run emparelhado do modelo contextual SHADOW

## Âmbito

Comparação retrospetiva entre a versão atual
`hierarchical-surface-elo-v4.3`, o novo modelo
`contextual-family-shadow-v1` e a probabilidade sem margem do mercado.

Esta análise não é validação prospetiva e não autoriza promoção, PAPER ou
GREEN. O modelo contextual não recebeu odds de mercado.

## População e linkage

- snapshots existentes: 1 616;
- snapshots liquidados: 1 406;
- liquidados produzidos exatamente pela versão atual: 55;
- emparelhamentos históricos inequívocos: 15;
- sem par na janela histórica: 39;
- resultado incompatível: 1.

A cobertura baixa não foi corrigida por aproximação. A fonte histórica ainda
não contém 29 desses pares e nove pares só existem em encontros antigos. Usar
o histórico atual diretamente para reconstruir os restantes permitiria que o
resultado do próprio jogo entrasse nos fatores, porque várias linhas possuem
apenas a data inicial do torneio.

## Resultado global emparelhado

| Modelo | n | Log loss | Brier | Acerto |
|---|---:|---:|---:|---:|
| Contextual SHADOW | 15 | 0,599681 | 0,206472 | 66,67% |
| Modelo atual | 15 | 0,624139 | 0,224657 | 53,33% |
| Mercado sem margem | 15 | 0,580327 | 0,198829 | 73,33% |

O novo modelo melhorou o atual nesta amostra, mas não superou o mercado. Quinze
jogos são insuficientes para uma decisão de promoção.

## Circuitos

### ATP — 11 jogos

- contextual: log loss 0,585907; acerto 63,64%;
- atual: log loss 0,551713; acerto 63,64%;
- mercado: log loss 0,562569; acerto 72,73%.

No ATP, o atual foi ligeiramente melhor em log loss. Não existe fundamento
para substituir o modelo com esta amostra.

### WTA — 3 jogos

- contextual: log loss 0,702923; acerto 66,67%;
- atual: log loss 0,935689; acerto 0%;
- mercado: log loss 0,730952; acerto 66,67%.

É um sinal exploratório favorável ao contextual, mas três jogos não permitem
conclusão.

### Challenger — 1 jogo

Sem valor inferencial. O caso também ficou `NOT_OPERATIONALLY_READY`.

## Comportamento extremo

Na amostra emparelhada, o novo modelo produziu apenas uma probabilidade de pelo
menos 80%, contra quatro no modelo atual. Isto é consistente com o objetivo de
reduzir confiança excessiva sem transformar ausência de dados em 50/50.

Maiores diferenças:

- Diana Shnaider vs Mia Pohankova: atual 41,4%, contextual 72,5%, mercado
  72,5%; Shnaider venceu;
- Jerome Kym vs Jiri Lehecka: atual 12,7%, contextual 31,8%, mercado 30,8%;
  Lehecka venceu;
- Alex de Minaur vs Matteo Berrettini: atual 80,4%, contextual 67,3%, mercado
  68,0%; De Minaur venceu;
- Carlos Alcaraz vs Tommy Paul: atual 82,1%, contextual 69,9%, mercado 79,2%;
  Alcaraz venceu.

Os exemplos mostram menor extremização e maior proximidade factual ao mercado
em vários casos, mas proximidade ao mercado não foi usada como objetivo do
modelo nem prova qualidade por si só.

## Decisão

1. Manter o novo modelo exclusivamente em SHADOW.
2. Não alterar o modelo atual, relatórios, PAPER, GREEN ou Telegram.
3. Recolher observações prospetivas diretamente no novo ledger, evitando o
   problema de linkage retrospetivo.
4. Só reavaliar promoção após amostra liquidada suficiente por ATP, WTA e
   Challenger e análise de log loss, Brier, calibração, ROI e extremos.
