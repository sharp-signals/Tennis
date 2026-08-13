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
echo "PR automático criado: $pr_url"
