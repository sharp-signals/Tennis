# CHANGE-2026-11-11-186 — robustez contextual gradual e leitura humana

## Nível e objetivo

Alteração **Level 3**, exclusivamente na release global isolada
`FENZOBOT_CONTEXTUAL_2026_11`. Corrigir num único bloco a distorção estrutural
observada em regressos após ausência prolongada, tornar cobertura e dependência
de famílias coerentes e substituir a leitura técnica em logits por uma leitura
visual orientada à decisão humana.

O caso Rune–Kecmanovic é um teste de aceitação, não uma exceção por nome.

## Contrato metodológico

1. O ranking atual continua factual, mas deixa de representar sozinho a força
   estrutural quando existe uma ausência longa seguida de poucos jogos de
   regresso.
2. O replay passa a expor, sempre ex ante:
   - duração do hiato mais recente;
   - data e número de jogos desde o regresso;
   - ranking estável anterior ao hiato;
   - diferença entre ranking atual e nível pré-hiato;
   - confiança do ranking atual durante a fase de regresso.
3. O nível histórico reduz a representatividade do ranking atual e cria
   contexto de fricção; não restaura silenciosamente a antiga força nem garante
   favoritismo.
4. A equação candidata é recalibrada cronologicamente e comparada com a release
   anterior. Mercado e resultados futuros permanecem proibidos na previsão.
5. A dependência `leave-one-family-out` deixa de ser binária:
   - `ROBUST` — o lado não muda;
   - `BALANCED_SENSITIVE` — pequena inversão num jogo próximo de 50/50;
   - `MATERIAL_DEPENDENCE` — alteração relevante que reduz confiança;
   - `CRITICAL_DEPENDENCE` — uma família cria sozinha favoritismo forte e
     bloqueia formulação de mercados.
   Os limiares auditáveis são: inversão com favorito abaixo de 55% e efeito
   inferior a 10 p.p. é sensível; a partir de 55% ou 10 p.p. é material; a
   partir de 60% ou 15 p.p. é crítica. São regras de governação da leitura, não
   coeficientes usados para formar a probabilidade.
6. Falta de família e dependência de família permanecem conceitos separados.

## Contrato de cobertura

Cada família é apresentada como `SOLID`, `PARTIAL`, `OBSERVED_NEUTRAL` ou
`UNAVAILABLE`. Uma família sem probabilidade utilizável não conta como sólida.
Uma família parcial pode contribuir apenas com identificação explícita dessa
condição. Ausência factual de H2H após pesquisa conta como observação neutra,
sem voto.

## Contrato visual

- A vista principal não mostra logits nem features cruas.
- Cada família mostra lado favorecido, intensidade visual e impacto em pontos
  percentuais, calculado pela diferença entre a previsão completa e o cenário
  sem essa família.
- Cor, comprimento da barra e rótulo textual transmitem direção/intensidade.
- Parcial usa padrão visual próprio; indisponível fica cinzento.
- O topo resume favorito, fair odd experimental, confiança, argumentos a favor,
  argumentos contra e lacunas.
- Logits, coeficientes e valores brutos ficam apenas numa auditoria técnica
  expansível.

## Preservação e isolamento

- Observações antigas são imutáveis e continuam associadas à respetiva geração.
- A nova metodologia cria nova geração/fingerprint.
- SHADOW apenas: sem PAPER, GREEN, Telegram, email ou relatório operacional.
- Moneyline e handicaps continuam evidência congelada e são formulados apenas
  segundo a política de robustez da nova geração.
- O teste histórico Paul–Darderi mantém limites bilaterais de plausibilidade,
  mas deixa de exigir uma banda de seis pontos que o arquivo ATP cumulativo já
  ultrapassava em `main`; o motor operacional antigo não é alterado.

## Critérios de aceitação

- Regresso longo não pode ser tratado como ranking corrente plenamente
  representativo sem evidência pós-regresso.
- Jogador veterano em declínio normal não é automaticamente restaurado ao seu
  pico histórico.
- Cobertura apresentada coincide com a informação efetivamente utilizada.
- Inversão marginal perto de 50% não é equiparada a 65% → abaixo de 50%.
- Relatório Rune–Kecmanovic explica claramente porque cada família favorece um
  lado, sem logits na leitura principal.
- Targeted tests, replay cronológico, auditor do ledger e full CI final passam.
