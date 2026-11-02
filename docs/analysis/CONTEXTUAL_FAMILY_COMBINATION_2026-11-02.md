# Combinação das cinco famílias — 02/11/2026

## Resultado

A combinação market-free superou a previsão constante e a melhor família
individual nos três universos.

| Universo | Acerto | Log loss combinado | Melhor família | Ganho vs melhor família |
|---|---:|---:|---:|---:|
| ATP | 65,43% | 0,62039 | 0,62658 | 0,00620 |
| WTA | 66,43% | 0,61135 | 0,62227 | 0,01092 |
| Challenger | 63,86% | 0,64013 | 0,64972 | 0,00959 |

O erro de calibração ECE ficou em 1,97% ATP, 1,38% WTA e 2,56%
Challenger. Ainda será necessária calibração explícita dos intervalos antes de
produzir fair odds operacionais.

## Contribuições da combinação

| Família | ATP | WTA | Challenger |
|---|---:|---:|---:|
| Forma recente | 0,234 | 0,305 | 0,114 |
| Força estrutural | **0,649** | **0,622** | **0,708** |
| Superfície/condições | 0,147 | 0,357 | 0,204 |
| Matchup/H2H | 0,201 | 0,135 | **0,037** |
| Serviço/resposta | 0,399 | 0,337 | 0,421 |

Estes coeficientes multiplicam logits já calibrados por família. Não são
percentagens, não somam 100% e não devem ser copiados para o sistema antigo de
pontos.

## Leitura

1. **Força estrutural é a âncora principal** nos três circuitos.
2. **Forma recente é mais importante no WTA** e claramente mais fraca nos
   Challengers, onde a transferência entre níveis exige prudência.
3. **Superfície tem contribuição particularmente relevante no WTA.**
4. **H2H Challenger caiu para perto de zero**, confirmando que deve ser apenas
   contextual e nunca obrigatório.
5. **Serviço/resposta acrescenta informação complementar real.** O coeficiente
   não lhe dá estatuto de família principal: forma e força estrutural continuam
   obrigatórias para prontidão, e serviço não pode produzir sinal autónomo.
6. Nenhuma família teve sinal invertido. Redundância só pode reduzir a sua
   contribuição até zero.

## Cobertura operacional primária

Forma recente e força estrutural estavam ambas disponíveis em:

- ATP: 84,94% do holdout;
- WTA: 82,87%;
- Challenger: 80,34%.

O modelo consegue produzir uma probabilidade descritiva nos restantes casos
através dos estados de ausência, mas esses jogos não ficam automaticamente
prontos para utilização operacional.

## Estado atual

- primeira probabilidade global independente do mercado: construída;
- fair odd operacional: ainda não;
- intervalo de incerteza: pendente;
- limites de extrapolação: pendentes;
- integração no bot: proibida nesta fase;
- odds de mercado usadas na construção: zero.

## Próximo passo

Calibrar incerteza e prontidão:

- curvas de calibração por circuito e faixa de probabilidade;
- intervalos mais largos quando faltam famílias ou há pouca amostra;
- limites para impedir probabilidades extremas sem evidência suficiente;
- avaliação separada dos casos com famílias principais completas;
- conversão em intervalo de fair odd apenas depois destas proteções.
