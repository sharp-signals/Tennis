#!/usr/bin/env bash
set -euo pipefail

# Este script é usado exclusivamente por workflows que acabaram de criar um
# commit de dados gerados (caches, relatórios, telemetria ou SHADOW). Código
# continua a entrar por Pull Request; não há auto-merge nem GitHub CLI aqui.
title="${1:-chore: atualizar dados gerados}"
recovery_dir="${FENZOBOT_RECOVERY_DIR:-${RUNNER_TEMP:-/tmp}/fenzobot-data-recovery}"

write_recovery() {
  reason="$1"
  mkdir -p "$recovery_dir"
  git status --porcelain=v1 --untracked-files=all > "$recovery_dir/git-status.txt" || true
  git diff --binary > "$recovery_dir/unstaged.patch" || true
  git diff --cached --binary > "$recovery_dir/staged.patch" || true
  git log -5 --decorate --oneline > "$recovery_dir/git-log.txt" || true
  git bundle create "$recovery_dir/local-commits.bundle" "origin/main..HEAD" 2>/dev/null || true
  python - "$recovery_dir/recovery-manifest.json" "$reason" "$title" <<'PY'
import hashlib
import json
import pathlib
import sys
from datetime import datetime, timezone

target = pathlib.Path(sys.argv[1])
files = []
for path in sorted(target.parent.iterdir()):
    if path == target or not path.is_file():
        continue
    files.append({
        "name": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
    })
target.write_text(json.dumps({
    "status": "NOT_PUBLISHED",
    "reason_code": sys.argv[2],
    "title": sys.argv[3],
    "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "files": files,
}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
  echo "Estado não publicado preservado em $recovery_dir ($reason)."
}

if [ "$(git branch --show-current)" != "main" ]; then
  echo "Publicação automática só é permitida a partir de main."
  exit 1
fi

# A seleção de ficheiros pertence ao workflow chamador. O helper nunca faz
# staging implícito e recusa esconder alterações legítimas num autostash.
if [ -n "$(git status --porcelain=v1 --untracked-files=all)" ]; then
  write_recovery "WORKTREE_NOT_CLEAN_AFTER_EXPLICIT_COMMIT"
  exit 1
fi

python scripts/validate_forward_only.py

git fetch origin main

# A fila partilhada evita writers simultâneos. Um avanço humano entre checkout
# e push é reconciliado sem autostash; conflitos reais ficam num artifact.
for tentativa in 1 2 3; do
  if ! git rebase origin/main; then
    git rebase --abort 2>/dev/null || true
    write_recovery "REBASE_CONFLICT"
    exit 1
  fi
  if git push origin HEAD:main; then
    echo "Dados gerados publicados diretamente em main: $title (tentativa $tentativa)."
    exit 0
  fi
  echo "Push falhou; nova tentativa ($tentativa/3)."
  git fetch origin main
  sleep 3
done

write_recovery "PUSH_REJECTED_AFTER_RETRIES"
exit 1
