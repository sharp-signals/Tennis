# Família de superfície e condições v2

**CHANGE-ID:** CHANGE-2026-11-02-175
**Estado:** fechada como candidata de família SHADOW; sem produção ou fair odd

## Pergunta da família

Em que medida o histórico dos dois jogadores no contexto exato do encontro
altera a leitura do confronto? Existem quatro contextos mutuamente exclusivos:

1. hard outdoor;
2. hard indoor;
3. terra batida;
4. relva.

Hard sem recinto factual continua por resolver. Não é assumido como outdoor.

## Informação utilizada

Para cada jogador e contexto, apenas partidas anteriores ao jogo analisado:

- carreira;
- época anterior;
- época atual.

Cada percentagem é reduzida para 50% conforme a amostra. A carreira usa dez
pseudojogos e cada época usa oito. Estes valores foram definidos antes da
auditoria segmentada; não foram escolhidos depois de observar o holdout.

As três leituras entram numa única equação por circuito e contexto. Não são
três votos somados manualmente.

## Fontes factuais

- ATP: TennisMyLife, com `surface` e `indoor`, protegida por cache diária de
  última cópia válida no GitHub Actions;
- WTA: cache multi-ano tennis-data, cujo campo `Court` identifica
  indoor/outdoor em todo o período;
- os dados brutos de terceiros não são publicados no repositório.

## Decisão por contexto

- ATP: os quatro contextos ficam prontos para observação SHADOW da família;
- WTA hard outdoor, terra e relva: prontos para SHADOW;
- WTA hard indoor: permanece factual e visível, mas sem voto numérico autónomo.
  No holdout disponível, o ganho sobre uma previsão constante foi praticamente
  zero. A ausência de voto não transforma o contexto em empate.

## Condições adicionais

- transição recente de piso fica visível, mas não vota: o ajuste fixo testado
  foi rejeitado;
- velocidade slow/medium/fast fica visível quando factual, mas não vota até
  existir um ledger histórico cronológico e verificável;
- hold, break, serviço e resposta pertencem à família própria e não são
  repetidos aqui;
- Challenger não define esta equação e será tratado separadamente mais tarde.

## Proteções

- mercado e odds não entram;
- dados em falta aumentam incerteza;
- `OBSERVED_NONE` não é dado em falta nem voto;
- nenhum contexto pode criar fair odd, PAPER ou GREEN sozinho;
- a família só poderá entrar na combinação depois de todas as famílias estarem
  fechadas e de uma nova calibração conjunta.
