#!/usr/bin/env bash
set -euo pipefail

# Cross-platform logic is deliberately kept in the tested Python helper.
# Publication core: git push origin HEAD:main (without force/autostash).
exec python scripts/publish_generated_changes.py "${1:-chore: atualizar dados gerados}"
