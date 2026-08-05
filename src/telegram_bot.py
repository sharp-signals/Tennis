from __future__ import annotations

import os

import requests

REQUEST_TIMEOUT = 20


def send_message(text: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("[aviso] TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID em falta — a imprimir no log em vez de enviar:")
        print(text)
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(
        url,
        data={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return True
