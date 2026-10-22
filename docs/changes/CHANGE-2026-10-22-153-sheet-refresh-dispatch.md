# CHANGE-2026-10-22-153 — atualização derivada após sincronização PAPER

Depois de publicar alterações agregadas da Sheet PAPER, o Apps Script envia um
evento `paper_sheet_synced` ao GitHub. O workflow observacional passa a aceitar
esse evento e promove a cópia autorizada, o histórico e o dashboard sem depender
do intervalo do agendamento de recuperação.

O agendamento periódico continua ativo como fallback. A publicação permanece
agregada e não envia apostas individuais, notas ou dados pessoais.
