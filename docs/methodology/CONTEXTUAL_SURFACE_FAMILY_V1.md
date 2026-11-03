# Família contextual de superfície e condições v1

**CHANGE-ID:** CHANGE-2026-11-02-175
**Estado:** candidato exploratório; insuficiente para fechar a família

> Nota de revisão de 03/11/2026: esta versão não deve ser promovida nem
> tratada como contrato final. Ao reduzir o sinal ao piso físico genérico,
> volta a misturar hard outdoor e hard indoor. A família será reavaliada com
> quatro contextos explícitos, carreira e evolução anual.

## Papel

Esta família responde apenas à pergunta: qual dos jogadores demonstrou melhor
desempenho histórico no piso do jogo? É contextual e não substitui forma
recente nem força estrutural.

## Componentes testados nesta versão exploratória

| Componente | Impacto na família v1 |
|---|---:|
| Registo histórico no piso atual | 100% do sinal |
| Indoor/outdoor | 0%; diagnóstico |
| Velocidade do hard | 0%; diagnóstico |
| Transição recente de piso | 0%; alerta |
| Hold/break/serviço/resposta | 0%; pertence a outra família |

Esta composição descreve apenas o candidato v1/v3 testado. Não constitui a
arquitetura final: hard outdoor e hard indoor têm de ser tratados como
contextos distintos, e a evolução por época ainda não foi incorporada.

O registo no piso usa vitórias e derrotas com shrinkage simétrico equivalente a
dez jogos prévios. Assim, 4–0 não é tratado como certeza superior a uma amostra
estável de dezenas de jogos.

## Porque este candidato não fecha a família

- O voto fixo de transição piorou significativamente ATP e WTA. A transição
  continua visível, mas não favorece automaticamente nenhum jogador.
- Retirar também indoor/outdoor/velocidade produziu resultado praticamente
  igual à versão que os usava, mas o teste usava um modificador contextual
  limitado e não quatro históricos de piso independentes. Não prova que
  indoor/outdoor seja irrelevante.
- A fonte histórica tem boa cobertura de piso, mas cobertura insuficiente e
  desigual de indoor/outdoor no WTA e não fornece velocidade histórica ampla.
- Não se inventa um contexto ausente nem se transfere serviço/hold/break para
  esta família, evitando duplicação.

## Evidência descritiva

No holdout emparelhado, o candidato apenas com piso obteve:

| Circuito | Jogos | Log loss legado | Log loss piso v1 |
|---|---:|---:|---:|
| ATP | 4 884 | 0,660137 | 0,648041 |
| WTA | 4 565 | 0,650631 | 0,640949 |

Estes resultados reutilizam o holdout depois da auditoria da versão anterior.
Por isso confirmam a direção metodológica, mas a promoção operacional exige
dados futuros ou uma nova janela temporal não consultada.

## Proteções

- A família produz um único sinal; os contextos sobrepostos nunca são somados.
- Ausência de amostra bilateral gera incerteza, não valor neutro inventado.
- Hard, terra e relva permanecem identificados separadamente no diagnóstico.
- ATP e WTA têm calibração separada.
- Challengers não definiram esta versão.
- O mercado e as odds não participaram.
- Produção, PAPER, fair odds, relatórios e bot automático permanecem intactos.
- A promoção deste candidato está proibida enquanto a arquitetura de quatro
  pisos e a evolução anual não forem testadas.
