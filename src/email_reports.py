"""Entrega por e-mail do resumo e links dos relatórios de uma run."""

from __future__ import annotations

import html
import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Iterable


SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
SMTP_TIMEOUT_SECONDS = 20


def _settings() -> tuple[str, str, str] | None:
    recipient = os.environ.get("REPORT_EMAIL_TO", "").strip()
    sender = os.environ.get("REPORT_EMAIL_FROM", "").strip()
    app_password = os.environ.get("REPORT_EMAIL_APP_PASSWORD", "").strip()
    if not all((recipient, sender, app_password)):
        return None
    return recipient, sender, app_password


def _report_rows(match_reports: Iterable[tuple[dict, dict, str | None]]) -> list[tuple[str, str | None]]:
    rows = []
    for payload, _result, url in match_reports:
        title = f"{payload.get('player_a', 'A')} vs {payload.get('player_b', 'B')}"
        rows.append((title, url))
    return rows


def send_run_report_email(today: str, match_reports: Iterable[tuple[dict, dict, str | None]]) -> bool:
    """Envia um resumo de uma run, sem anexos e sem expor segredos nos erros.

    A entrega é opcional: credenciais em falta deixam a run operacional e são
    visíveis apenas como aviso no log. O chamador decide se uma falha de SMTP
    deve degradar a execução; o pipeline atual limita-se a alertar no log.
    """
    settings = _settings()
    if settings is None:
        print("[email] não configurado: faltam REPORT_EMAIL_TO, REPORT_EMAIL_FROM ou REPORT_EMAIL_APP_PASSWORD.")
        return False
    recipient, sender, app_password = settings
    rows = _report_rows(match_reports)

    plain_lines = [f"Relatórios pré-live Fenzobot — {today}", ""]
    html_rows = []
    for title, url in rows:
        if url:
            plain_lines.append(f"- {title}: {url}")
            html_rows.append(f'<li><a href="{html.escape(url, quote=True)}">{html.escape(title)}</a></li>')
        else:
            plain_lines.append(f"- {title}: relatório indisponível")
            html_rows.append(f"<li>{html.escape(title)} — relatório indisponível</li>")
    if not rows:
        plain_lines.append("Não foram gerados relatórios nesta run.")
        html_rows.append("<li>Não foram gerados relatórios nesta run.</li>")

    message = EmailMessage()
    message["Subject"] = f"Fenzobot — Relatórios pré-live {today}"
    message["From"] = sender
    message["To"] = recipient
    message.set_content("\n".join(plain_lines))
    message.add_alternative(
        "<html><body><h2>Relatórios pré-live Fenzobot</h2>"
        f"<p>Run de {html.escape(today)}.</p><ul>{''.join(html_rows)}</ul>"
        "<p>Os relatórios são links para o site publicado; não seguem anexos.</p>"
        "</body></html>",
        subtype="html",
    )

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context, timeout=SMTP_TIMEOUT_SECONDS) as client:
            client.login(sender, app_password)
            client.send_message(message)
    except (OSError, smtplib.SMTPException):
        raise RuntimeError("Falha ao enviar o resumo de relatórios por e-mail.") from None

    print(f"[email] resumo enviado para {recipient} com {len(rows)} relatório(s).")
    return True
