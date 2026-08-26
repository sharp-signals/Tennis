"""Envia o digest criado pelo bot depois de os relatórios serem publicados."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.email_digest import send_digest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", help="Manifesto JSON produzido por src.main")
    parser.add_argument("--skip-if-unconfigured", action="store_true")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        print("[email] sem manifesto nesta execução; não há digest para enviar.")
        return

    required = (
        "REPORT_EMAIL_SMTP_USERNAME",
        "REPORT_EMAIL_SMTP_PASSWORD",
        "REPORT_EMAIL_TO",
    )
    missing = [name for name in required if not os.getenv(name)]
    if missing and args.skip_if_unconfigured:
        print(f"[email] envio ignorado; secrets em falta: {', '.join(missing)}")
        return
    if missing:
        raise SystemExit(f"Configuração de email incompleta: {', '.join(missing)}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    count = send_digest(manifest)
    print(f"[email] digest HTML único enviado a {count} destinatário(s).")


if __name__ == "__main__":
    main()
