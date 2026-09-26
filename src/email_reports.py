"""Entrega por e-mail do resumo e links dos relatórios de uma run."""

from __future__ import annotations

import html
import os
import re
import smtplib
import ssl
from datetime import date
from email.message import EmailMessage
from typing import Iterable, Mapping

from .config import SITE_BASE_URL
from .telegram_summary import decision_row

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
SMTP_TIMEOUT_SECONDS = 20
EMAIL_REPORTS = "REPORTS"
EMAIL_NO_ELIGIBLE = "NO_ELIGIBLE_HEARTBEAT"
EMAIL_RUN_FAILED = "RUN_FAILED_HEARTBEAT"
EMAIL_DELIVERY_STATUSES = frozenset({
    "SENT", "FAILED", "NOT_CONFIGURED", "NOT_ATTEMPTED",
})
GROUP_NAMES = {
    3: "🟢 EDGE POSITIVO / PAPER",
    2.5: "🟡 EDGE POSITIVO / SEM PAPER — COBERTURA, IDENTIDADE OU EXPERIMENTO",
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


def _delivery(status: str, kind: str, reason_code: str | None = None) -> dict:
    result = {"status": status, "kind": kind}
    if reason_code:
        result["reason_code"] = reason_code
    return result


def _deliver(kind: str, subject: str, plain: str, html_body: str) -> dict:
    """Transporte SMTP único; nunca propaga credenciais nem falhas ao motor."""
    settings = _settings()
    if settings is None:
        print("[email] não configurado: faltam REPORT_EMAIL_TO, REPORT_EMAIL_FROM ou REPORT_EMAIL_APP_PASSWORD.")
        return _delivery("NOT_CONFIGURED", kind)
    recipient, sender, app_password = settings

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    message.set_content(plain)
    message.add_alternative(html_body, subtype="html")

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(
            SMTP_HOST, SMTP_PORT, context=context, timeout=SMTP_TIMEOUT_SECONDS,
        ) as client:
            client.login(sender, app_password)
            client.send_message(message)
    except (OSError, smtplib.SMTPException):
        print(f"[email] falha de transporte ({kind}); detalhes SMTP omitidos.")
        return _delivery("FAILED", kind, "SMTP_SEND_FAILED")

    print(f"[email] entrega {kind} enviada para {recipient}.")
    return _delivery("SENT", kind)


def _display_date(today: str) -> str:
    try:
        return date.fromisoformat(today).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return str(today)


def _simple_html(title: str, lines: list[str]) -> str:
    rows = "".join(
        f'<p style="margin:6px 0;">{html.escape(line)}</p>' for line in lines
    )
    return (
        '<html><body style="margin:0;background:#f4f4f4;color:#202020;'
        'font-family:Arial,sans-serif;"><div style="max-width:640px;margin:0 auto;'
        'background:#ffffff;padding:28px;">'
        f'<h2 style="margin:0 0 18px;color:#1e352c;">{html.escape(title)}</h2>'
        f"{rows}</div></body></html>"
    )


def _value(details: Mapping[str, object], key: str, default: object = "N/D") -> object:
    value = details.get(key)
    return default if value in (None, "") else value


def _discovery_lines(details: Mapping[str, object]) -> list[str]:
    partial = bool(details.get("discovery_partial"))
    return [
        f"Discovery source: {_value(details, 'discovery_selected_source')}",
        f"Discovery status: {_value(details, 'discovery_status')}",
        f"Discovery partial: {'sim' if partial else 'não'}",
    ]


def sanitize_error_message(error: BaseException) -> str:
    message = str(error).replace("\r", " ").replace("\n", " ")[:300]
    for env_name in (
        "REPORT_EMAIL_APP_PASSWORD", "RAPIDAPI_KEY", "TELEGRAM_BOT_TOKEN",
        "TELEGRAPH_ACCESS_TOKEN", "GITHUB_TOKEN", "ANTHROPIC_API_KEY",
    ):
        secret = os.environ.get(env_name, "")
        if secret:
            message = message.replace(secret, "[REDACTED]")
    return re.sub(
        r"(?i)(authorization|bearer|token|api[_ -]?key|password)\s*[:=]?\s*\S+",
        r"\1 [REDACTED]",
        message,
    )


def send_run_report_email(
    today: str,
    match_reports: Iterable[tuple[dict, dict, str | None]],
) -> dict:
    """Envia o único e-mail operacional principal de uma run com relatórios."""
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

    logo_url = f"{SITE_BASE_URL}/assets/fenzo-logo.png"
    html_body = (
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
        '</div></div></body></html>'
    )
    result = _deliver(
        EMAIL_REPORTS,
        f"Fenzobot — Relatórios pré-live {today}",
        "\n".join(plain_lines),
        html_body,
    )
    if result["status"] == "SENT":
        print(f"[email] resumo contém {report_count} relatório(s).")
    return result


def send_no_eligible_heartbeat(
    today: str,
    details: Mapping[str, object],
    *,
    reason: str,
) -> dict:
    state = "DEGRADED" if details.get("discovery_partial") is True else "OK"
    lines = [
        f"Estado: {state}",
        f"Slot: {_value(details, 'trigger_slot', 'manual')}",
        f"Origem: {_value(details, 'trigger_source', 'manual')}",
        f"Fixtures descobertas: {_value(details, 'fixtures_discovered', 0)}",
        f"Jogos dentro da janela: {_value(details, 'fixtures_in_window', 0)}",
        f"Jogos elegíveis antes de identidade: {_value(details, 'eligible_before_identity', 0)}",
        f"Jogos elegíveis após identidade: {_value(details, 'eligible_after_identity', 0)}",
        "Relatórios: 0",
        f"Motivo: {reason}",
        *_discovery_lines(details),
    ]
    title = "Fenzobot — Run concluída sem relatórios"
    return _deliver(
        EMAIL_NO_ELIGIBLE,
        f"{title} — {_display_date(today)}",
        "\n".join(lines),
        _simple_html(title, lines),
    )


def send_run_failed_heartbeat(
    today: str,
    details: Mapping[str, object],
    error: BaseException,
) -> dict:
    lines = [
        "Estado: FAILED",
        f"Slot: {_value(details, 'trigger_slot', 'manual')}",
        f"Origem: {_value(details, 'trigger_source', 'manual')}",
        f"Phase: {_value(details, 'phase')}",
        f"Error type: {type(error).__name__}",
        f"Reason: {sanitize_error_message(error)}",
        f"GitHub run ID: {_value(details, 'github_run_id')}",
        f"GitHub Actions URL: {_value(details, 'github_actions_url')}",
        f"Fixtures descobertas: {_value(details, 'fixtures_discovered')}",
        f"Jogos elegíveis: {_value(details, 'eligible_after_identity', _value(details, 'eligible_before_identity'))}",
        f"Relatórios publicados: {_value(details, 'reports_ok')}",
        *_discovery_lines(details),
    ]
    title = "Fenzobot — FALHA operacional"
    return _deliver(
        EMAIL_RUN_FAILED,
        f"{title} — {_display_date(today)}",
        "\n".join(lines),
        _simple_html(title, lines),
    )
