# Runtime contextual SHADOW v1

## Finalidade

Observar prospetivamente o novo modelo de cinco famílias sem modificar o
Fenzobot operacional. Esta fase mede estabilidade, cobertura e calibração em
jogos futuros; não escolhe apostas.

## Ordem de execução

1. O pipeline atual recolhe dados e fecha o pricing e a decisão atuais.
2. Só depois, o runtime contextual reconstrói uma linha pré-jogo sem mercado.
3. As cinco equações familiares congeladas geram probabilidades internas.
4. O combinador congelado produz uma probabilidade central.
5. O bin empírico correspondente produz o intervalo de 90% e a faixa de fair
   odd SHADOW.
6. A observação é anexada ao ledger contextual separado.

Uma falha em qualquer ponto cria apenas estado `UNAVAILABLE`; não derruba o
relatório nem muda qualquer decisão.

## Isolamento obrigatório

- nenhuma odd de mercado entra nas famílias ou na probabilidade;
- não se calcula edge neste ledger;
- não se escreve em PAPER ou GREEN;
- não se altera o pricing, o índice ou a decisão atuais;
- não se altera a ordem ou a cor das notificações;
- o painel visual é um protótipo isolado e não integra o HTML atual.

## Identidade e deduplicação

Cada registo exige identidade canónica. A chave combina identidade do jogo,
versão do modelo e fingerprint da configuração. Um rerun não reescreve a
primeira observação da mesma versão.

## Prontidão

`READY_FOR_PROSPECTIVE_SHADOW` exige forma recente e força estrutural
observadas, probabilidade dentro do suporte histórico e bin com pelo menos 80
casos. Este estado não significa prontidão operacional.

## Promoção futura

Qualquer proposta de substituir o modelo atual exige resultados prospetivos
liquidados, auditoria por ATP/WTA/Challenger, comparação com baselines,
validação humana e alteração explícita de versão. Não existe promoção
automática.
