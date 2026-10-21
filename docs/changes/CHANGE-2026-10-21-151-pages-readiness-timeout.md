# CHANGE-2026-10-21-151 — Janela realista para readiness do GitHub Pages

## Problema observado

Na execução `39644765864`, o bot processou 27 jogos e publicou os 27
relatórios no `main`, mas o GitHub Pages não terminou o deployment dentro dos
120 segundos concedidos pelo passo de readiness. O contrato reteve corretamente
as notificações, porém classificou como falha uma latência normal do Pages.

O deployment iniciado pelo commit dos relatórios demorou mais de dois minutos.
O commit posterior de preservação iniciou um segundo deployment, que cancelou o
primeiro e terminou com sucesso. Os dados e relatórios ficaram preservados, mas
o email e o Telegram não foram enviados nessa execução.

## Alteração

- Aumentar a janela global de readiness de 120 para 360 segundos.
- Manter o polling a cada quatro segundos.
- Manter a exigência de HTTP 200 e igualdade SHA-256, ficheiro a ficheiro.
- Manter a retenção de notificações e a falha explícita se os relatórios não
  estiverem realmente publicados ao fim da nova janela.

## Impacto

Não altera aquisição, análise, pricing, pesos, PAPER, GREEN, relatórios ou
dados históricos. Apenas permite que a validação externa acompanhe a latência
realista do GitHub Pages antes de enviar os links.
