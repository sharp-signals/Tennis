#!/usr/bin/env bash
set -euo pipefail

title="${1:-chore: atualizar dados gerados}"
slug="$(printf '%s' "${GITHUB_WORKFLOW:-workflow}" | tr '[:upper:] ' '[:lower:]-' | tr -cd 'a-z0-9_-')"
branch="bot/${slug}-${GITHUB_RUN_ID:-manual}-${GITHUB_RUN_ATTEMPT:-1}"

if git show-ref --verify --quiet "refs/heads/$branch"; then
  git switch "$branch"
else
  git switch -c "$branch"
fi
git push --set-upstream origin "$branch"
pr_url="$(gh pr list --state open --head "$branch" --json url --jq '.[0].url // empty')"
if [ -z "$pr_url" ]; then
  pr_url="$(gh pr create --base main --head "$branch" --title "$title" \
    --body "Atualização automática gerada por \`${GITHUB_WORKFLOW:-workflow}\`, execução \`${GITHUB_RUN_ID:-local}\`. O CI deve passar antes da integração.")"
fi
gh pr merge "$pr_url" --auto --squash --delete-branch

# Não libertar o grupo de concorrência enquanto a telemetria/caches ainda
# estiverem apenas no branch do PR. Sem esta confirmação, a execução seguinte
# poderia arrancar de main desatualizada e subcontar a quota diária.
for tentativa in $(seq 1 30); do
  state="$(gh pr view "$pr_url" --json state --jq '.state')"
  if [ "$state" = "MERGED" ]; then
    echo "PR automático integrado: $pr_url"
    exit 0
  fi
  if [ "$state" = "CLOSED" ]; then
    echo "PR automático fechado sem merge: $pr_url"
    exit 1
  fi
  echo "PR ainda $state; a aguardar integração ($tentativa/30)..."
  sleep 10
done

echo "PR automático não foi integrado dentro de 5 minutos: $pr_url"
exit 1
