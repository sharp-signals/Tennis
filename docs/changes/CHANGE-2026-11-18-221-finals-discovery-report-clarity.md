# CHANGE-2026-11-18-221 — descoberta Finals e clareza do relatório

## Objetivo

- Recuperar jogos factuais presentes em `all-upcoming` quando o endpoint de
  fixtures do torneio ainda está incompleto.
- Mostrar em cada notificação as odds capturadas, a casa e a hora da captura.
- Mostrar o resultado agregado do confronto direto no detalhe H2H.

## Garantias

- Só entram jogos de torneios já aceites, com ID de evento, hora e IDs dos dois
  jogadores.
- Um conflito de identidade entre endpoints continua a excluir o jogo.
- A previsão e a fair odd continuam independentes das odds de mercado.

## Verificação

- Testes de descoberta resiliente.
- Testes do relatório contextual e da publicação Telegram/email.
- Verificação de formatação do diff.

## Rollback

Reverter este change remove a união factual de fixtures e os novos elementos de
apresentação, sem alterar o modelo de pricing nem os registos históricos.
