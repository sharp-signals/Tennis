#!/usr/bin/env bash
set -euo pipefail

# Este script é usado exclusivamente por workflows que acabaram de criar um
# commit de dados gerados (caches, relatórios, telemetria ou SHADOW). Código
# continua a entrar por Pull Request; não há auto-merge nem GitHub CLI aqui.
title="${1:-chore: atualizar dados gerados}"

if [ "$(git branch --show-current)" != "main" ]; then
  echo "Publicação automática só é permitida a partir de main."
  exit 1
fi

# A concorrência partilhada dos workflows evita corridas entre bot e monitor.
# Ainda assim, rebase + três tentativas protegem contra um push humano ou uma
# atualização remota que ocorra durante a execução.
for tentativa in 1 2 3; do
  if ! git pull --rebase --autostash origin main; then
    echo "Rebase falhou; não é seguro publicar dados gerados."
    exit 1
  fi
  if git push origin HEAD:main; then
    echo "Dados gerados publicados diretamente em main: $title (tentativa $tentativa)."
    exit 0
  fi
  echo "Push falhou; nova tentativa ($tentativa/3)."
  sleep 3
done

echo "Push dos dados gerados falhou após 3 tentativas."
exit 1
