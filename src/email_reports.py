"""Entrega por e-mail do resumo e links dos relatórios de uma run."""

from __future__ import annotations

import html
import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Iterable

from .config import SITE_BASE_URL
from .telegram_summary import decision_row

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
SMTP_TIMEOUT_SECONDS = 20
GROUP_NAMES = {
    3: "🟢 EDGE POSITIVO / PAPER",
    2: "🔴 EDGE NEGATIVO / EXCLUÍDO",
    1: "⚪ EDGE ZERO / EXCLUÍDO",
    0: "🟡 PREÇO DE MERCADO INDISPONÍVEL / SEM PAPER",
    -1: "⚫ RELATÓRIO NULO",
}


def _settings() -> tuple[str, str, str] | None:
    recipient = os.environ.get("REPORT_EMAIL_TO", "").strip()
    sender = os.environ.get("REPORT_EMAIL_FROM", "").strip()
    app_password = os.environ.get("REPORT_EMAIL_APP_PASSWORD", "").strip()
    if not all((recipient, sender, app_password)):
        return None
    return recipient, sender, app_password


def _grouped_report_rows(match_reports: Iterable[tuple[dict, dict, str | None]]) -> list[tuple[str, list[tuple[str, str | None]]]]:
    """Agrupa como o resumo Telegram, mantendo os links do e-mail simples."""
    grouped: dict[int, list[tuple[str, str | None]]] = {}
    for payload, _result, url in match_reports:
        title = f"{payload.get('player_a', 'A')} vs {payload.get('player_b', 'B')}"
        level, _ball, _text = decision_row(payload)
        state = (payload.get("prelive_decision") or {}).get("state")
        group_level = -1 if state == "REPORT_NULL" else level
        grouped.setdefault(group_level if group_level in GROUP_NAMES else -1, []).append((title, url))
    return [(GROUP_NAMES[level], grouped[level]) for level in sorted(grouped, reverse=True)]


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
    groups = _grouped_report_rows(match_reports)
    report_count = sum(len(rows) for _group, rows in groups)

    plain_lines = [f"Relatórios pré-live Fenzobot — {today}", ""]
    html_groups = []
    for group_name, rows in groups:
        plain_lines.extend([group_name, ""])
        html_rows = []
        for title, url in rows:
            if url:
                plain_lines.append(f"- {title}: {url}")
                html_rows.append(f'<li><a href="{html.escape(url, quote=True)}">{html.escape(title)}</a></li>')
            else:
                plain_lines.append(f"- {title}: relatório indisponível")
                html_rows.append(f"<li>{html.escape(title)} — relatório indisponível</li>")
        plain_lines.append("")
        html_groups.append(f"<h3 style=\"margin:20px 0 8px;color:#1e352c;\">{html.escape(group_name)}</h3><ul>{''.join(html_rows)}</ul>")
    if not groups:
        plain_lines.append("Não foram gerados relatórios nesta run.")
        html_groups.append("<p>Não foram gerados relatórios nesta run.</p>")
    plain_lines.extend([
        "",
        "Fenzo Tennis Intelligence",
        "Análise pré-live baseada em dados e contexto de mercado.",
        "Informação analítica; não constitui recomendação de aposta nem garantia de resultado.",
    ])

    message = EmailMessage()
    message["Subject"] = f"Fenzobot — Relatórios pré-live {today}"
    message["From"] = sender
    message["To"] = recipient
    message.set_content("\n".join(plain_lines))
    logo_url = f"{SITE_BASE_URL}/assets/fenzo-logo.png"
    message.add_alternative(
        '<html><body style="margin:0;background:#f4f4f4;color:#202020;font-family:Arial,sans-serif;">'
        '<div style="max-width:640px;margin:0 auto;background:#ffffff;padding:28px;">'
        '<h2 style="margin:0 0 8px;color:#1e352c;">Relatórios pré-live Fenzobot</h2>'
        f"<p style=\"margin:0 0 20px;\">Run de {html.escape(today)}.</p>{''.join(html_groups)}"
        '<p style="margin:20px 0 0;">Os relatórios são links para o site publicado; não seguem anexos.</p>'
        '<hr style="border:0;border-top:1px solid #d7d7d7;margin:28px 0 20px;">'
        f'<img src="{html.escape(logo_url, quote=True)}" alt="Fenzo Tennis Intelligence" width="130" '
        'style="display:block;width:130px;height:auto;margin:0 0 12px;">'
        '<div style="font-size:14px;line-height:1.5;color:#4b4b4b;">'
        '<strong style="color:#1e352c;">Fenzo Tennis Intelligence</strong><br>'
        'Análise pré-live baseada em dados e contexto de mercado.<br>'
        '<span style="font-size:12px;">Informação analítica; não constitui recomendação de aposta nem garantia de resultado.</span>'
        '</div></div></body></html>',
        subtype="html",
    )

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context, timeout=SMTP_TIMEOUT_SECONDS) as client:
            client.login(sender, app_password)
            client.send_message(message)
    except (OSError, smtplib.SMTPException):
        raise RuntimeError("Falha ao enviar o resumo de relatórios por e-mail.") from None

    print(f"[email] resumo enviado para {recipient} com {report_count} relatório(s).")
    return True
