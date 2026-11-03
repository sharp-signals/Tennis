# Replay cronológico do H2H contextual — 2026-11-03

**CHANGE-ID:** CHANGE-2026-11-02-175  
**Estado:** auditoria read-only; sem efeito no índice, fair odd, relatório ou PAPER

## Pergunta

O confronto direto deve contribuir para a família de matchup? Em particular,
um H2H no mesmo contexto de piso acrescenta informação estável ao H2H global?

O replay usa apenas encontros anteriores ao alvo, adiciona os resultados de
cada dia só depois de avaliar todos os jogos desse dia e não consulta odds.
Validação e holdout são cronológicos. Zero confrontos confirmados é
`OBSERVED_NONE`: pesquisa concluída, cobertura factual e impacto nulo.

## Holdout

| Circuito | H2H anterior | Alvos | Acerto do líder global | Acerto no mesmo contexto | Acerto recente no mesmo contexto |
|---|---:|---:|---:|---:|---:|
| ATP | 1 | 807 | 58,2% | 57,4% (265) | 58,3% (187) |
| ATP | 2–3 | 557 | 62,3% (387 sinais) | 57,6% (236) | 57,3% (185) |
| ATP | 4+ | 258 | 66,0% (215 sinais) | 65,5% (142) | 63,4% (112) |
| WTA | 1 | 883 | 57,1% | 57,3% (377) | 56,2% (242) |
| WTA | 2–3 | 680 | 62,3% (483 sinais) | 59,3% (364) | 61,4% (246) |
| WTA | 4+ | 347 | 60,8% (283 sinais) | 63,3% (226) | 58,3% (163) |

Os parênteses indicam a quantidade de sinais não empatados quando ela difere
do número de alvos.

## Decisão metodológica

1. **Um único H2H não pode ser um voto material.** O acerto de 57–58% é
   compatível com um modificador muito pequeno, sujeito a forte shrinkage.
2. **Repetição interessa.** As bandas 2–3 e 4+ preservam sinal no holdout,
   embora a intensidade não seja monotónica em ambos os circuitos.
3. **Mesmo piso não é uma segunda confirmação independente.** Não melhora de
   forma estável o líder global e não será somado como outro peso.
4. **Contexto é modificador, não voto.** Recência, piso, circuito, formato e
   evolução dos jogadores devem ajustar a aplicabilidade do mesmo histórico.
5. **A família continuará limitada.** H2H nunca poderá liderar sozinho a
   probabilidade nem compensar forma recente forte em sentido contrário.

## Próximo teste

Construir candidatos limitados e monotónicos:

- baseline global com shrinkage por número de confrontos;
- desconto por antiguidade e mudança estrutural dos jogadores;
- ajuste contextual pequeno, sem duplicar partidas;
- estado neutro explícito quando o H2H é inexistente ou empatado.

Os candidatos serão comparados primeiro na validação e apenas uma configuração
congelada será confirmada no holdout. Nenhuma configuração fica autorizada por
este documento.

## Artefacto

`data/validation/contextual-h2h-audit-2026-11-03.json`
