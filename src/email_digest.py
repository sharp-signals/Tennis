"""Digest HTML único de uma execução do Tennis Bot.

O bot apenas gera um manifesto local. O workflow envia-o depois de publicar
os relatórios, garantindo que os links já existem quando o email chega.
Credenciais e destinatários vêm exclusivamente de variáveis/secrets.
"""
from __future__ import annotations

import html
import json
import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path
from typing import Iterable


PRIORITIES = {
    "high": (4, "🔴", "Prioridade alta"),
    "candidate": (3, "🟢", "Valor experimental a analisar"),
    "watch": (2, "🟡", "A acompanhar"),
    "routine": (1, "⚪", "Sem prioridade"),
    "no_odds": (0, "⚠️", "Sem odds"),
}


def _safe_float(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _game_entry(payload: dict, result: dict, url: str | None) -> dict:
    divergence = payload.get("divergencia") or {}
    level = (divergence.get("classificacao") or {}).get("nivel", -1)
    pricing = payload.get("pricing") or {}
    candidate_side = pricing.get("candidate_side") if pricing.get("available") else None
    odds = payload.get("market_odds_decimal") or {}
    has_odds = any(
        number is not None and number > 1
        for number in (_safe_float(value) for value in odds.values())
    )

    if not has_odds:
        category = "no_odds"
    elif isinstance(level, (int, float)) and level >= 3:
        category = "high"
    elif candidate_side:
        category = "candidate"
    elif isinstance(level, (int, float)) and level >= 1:
        category = "watch"
    else:
        category = "routine"

    candidate = None
    if candidate_side:
        side = (pricing.get("players") or {}).get(candidate_side) or {}
        candidate = {
            "player": payload.get(f"player_{candidate_side}") or pricing.get("candidate_player"),
            "fair_odd": _safe_float(side.get("fair_odd")),
            "market_odd": _safe_float(side.get("market_odd")),
            "expected_edge_pct": _safe_float(side.get("expected_edge_pct")),
            "status": "experimental",
        }

    return {
        "player_a": payload.get("player_a") or "?",
        "player_b": payload.get("player_b") or "?",
        "tournament": payload.get("tournament") or "",
        "category": category,
        "priority_label": PRIORITIES[category][2],
        "summary": result.get("summary_line") or result.get("executive_summary") or "",
        "report_url": url,
        "candidate": candidate,
    }


def build_digest_manifest(
    match_reports: Iterable[tuple[dict, dict, str | None]],
    report_date: str,
    index_url: str,
) -> dict:
    games = [_game_entry(payload, result, url) for payload, result, url in match_reports]
    games.sort(key=lambda game: PRIORITIES[game["category"]][0], reverse=True)
    counts = {key: sum(game["category"] == key for game in games) for key in PRIORITIES}
    return {
        "schema_version": 1,
        "report_date": report_date,
        "index_url": index_url,
        "counts": counts,
        "games": games,
    }


def write_digest_manifest(path: str, manifest: dict) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, destination)


def _fmt(value, decimals=2, suffix="") -> str:
    number = _safe_float(value)
    return "—" if number is None else f"{number:.{decimals}f}{suffix}"


def build_digest_html(manifest: dict) -> str:
    date = html.escape(str(manifest.get("report_date") or ""))
    index_url = html.escape(str(manifest.get("index_url") or ""), quote=True)
    counts = manifest.get("counts") or {}
    games = manifest.get("games") or []
    summary = "".join(
        f'<span style="display:inline-block;margin:0 8px 8px 0;padding:7px 10px;'
        f'border:1px solid #2b4058;border-radius:999px;background:#122740">'
        f'{icon} {int(counts.get(key, 0) or 0)} {html.escape(label.lower())}</span>'
        for key, (_, icon, label) in PRIORITIES.items()
    )

    sections = []
    for category, (_, icon, label) in PRIORITIES.items():
        category_games = [game for game in games if game.get("category") == category]
        if not category_games:
            continue
        cards = []
        for game in category_games:
            players = (
                f'{html.escape(str(game.get("player_a") or "?"))} '
                f'<span style="color:#8092a8;font-weight:400">vs</span> '
                f'{html.escape(str(game.get("player_b") or "?"))}'
            )
            candidate = game.get("candidate") or {}
            candidate_block = ""
            if candidate:
                candidate_block = (
                    '<div style="margin-top:12px;padding:10px 12px;border-radius:8px;'
                    'background:#102f2c;border:1px solid #247f70;color:#d8fff7">'
                    f'<strong>Candidato experimental: {html.escape(str(candidate.get("player") or "—"))}</strong><br>'
                    f'<span style="font-size:13px">Fair odd {_fmt(candidate.get("fair_odd"))} · '
                    f'odd de mercado {_fmt(candidate.get("market_odd"))} · '
                    f'expected edge {_fmt(candidate.get("expected_edge_pct"), 1, "%")}</span></div>'
                )
            report_url = game.get("report_url")
            report_link = (
                f'<a href="{html.escape(str(report_url), quote=True)}" '
                'style="display:inline-block;margin-top:12px;color:#62b8f4;text-decoration:none;font-weight:700">'
                'Abrir relatório individual →</a>'
                if report_url else
                '<div style="margin-top:12px;color:#d9aa4f">Relatório individual indisponível</div>'
            )
            cards.append(
                '<div style="margin:0 0 12px;padding:16px;border-radius:10px;'
                'background:#111e2d;border:1px solid #263b51">'
                f'<div style="font-size:17px;font-weight:700;color:#f4f7fb">{players}</div>'
                f'<div style="margin-top:4px;font-size:12px;letter-spacing:.04em;text-transform:uppercase;'
                f'color:#8ca2ba">{html.escape(str(game.get("tournament") or ""))}</div>'
                f'<div style="margin-top:10px;color:#c8d3df;line-height:1.45">'
                f'{html.escape(str(game.get("summary") or "Sem resumo adicional."))}</div>'
                f'{candidate_block}{report_link}</div>'
            )
        sections.append(
            f'<h2 style="margin:26px 0 10px;font-size:17px;color:#f4f7fb">{icon} '
            f'{html.escape(label)} ({len(category_games)})</h2>{"".join(cards)}'
        )

    return f'''<!doctype html>
<html lang="pt"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"></head>
<body style="margin:0;background:#08111c;color:#f4f7fb;font-family:Segoe UI,Arial,sans-serif">
<div style="display:none;max-height:0;overflow:hidden">Resumo completo dos relatórios Tennis de {date}</div>
<div style="max-width:760px;margin:0 auto;padding:28px 16px 48px">
  <div style="padding-bottom:18px;border-bottom:2px solid #327fb1">
    <h1 style="margin:0;font-size:24px">🎾 Resumo Pré-Live — {date}</h1>
    <p style="margin:8px 0 0;color:#91a5ba">{len(games)} jogos analisados numa única execução.</p>
  </div>
  <div style="margin-top:18px">{summary}</div>
  <a href="{index_url}" style="display:inline-block;margin-top:8px;padding:11px 15px;border-radius:8px;
     background:#327fb1;color:white;text-decoration:none;font-weight:700">Abrir índice completo do dia</a>
  {''.join(sections)}
  <div style="margin-top:28px;padding-top:15px;border-top:1px solid #263b51;color:#8092a8;font-size:12px;line-height:1.5">
    Fair odds e expected edge são experimentais e ainda estão em validação; não representam garantia de resultado.
  </div>
</div></body></html>'''


def build_digest_text(manifest: dict) -> str:
    lines = [
        f"Resumo Pré-Live — {manifest.get('report_date', '')}",
        f"Índice completo: {manifest.get('index_url', '')}",
        "",
    ]
    for game in manifest.get("games") or []:
        lines.append(
            f"[{game.get('priority_label')}] {game.get('player_a')} vs {game.get('player_b')}"
        )
        candidate = game.get("candidate") or {}
        if candidate:
            lines.append(
                f"Candidato experimental: {candidate.get('player')} | fair odd "
                f"{_fmt(candidate.get('fair_odd'))} | edge "
                f"{_fmt(candidate.get('expected_edge_pct'), 1, '%')}"
            )
        if game.get("report_url"):
            lines.append(str(game["report_url"]))
        lines.append("")
    return "\n".join(lines)


def parse_recipients(value: str) -> list[str]:
    return [item.strip() for item in value.replace(";", ",").split(",") if item.strip()]


def send_digest(manifest: dict, environ: dict | None = None) -> int:
    env = os.environ if environ is None else environ
    username = (env.get("REPORT_EMAIL_SMTP_USERNAME") or "").strip()
    password = env.get("REPORT_EMAIL_SMTP_PASSWORD") or ""
    recipients = parse_recipients(env.get("REPORT_EMAIL_TO") or "")
    sender = (env.get("REPORT_EMAIL_FROM") or username).strip()
    if not username or not password or not recipients or not sender:
        raise ValueError(
            "Configuração de email incompleta: são obrigatórios "
            "REPORT_EMAIL_SMTP_USERNAME, REPORT_EMAIL_SMTP_PASSWORD e REPORT_EMAIL_TO."
        )

    host = (env.get("REPORT_EMAIL_SMTP_HOST") or "smtp.gmail.com").strip()
    port = int(env.get("REPORT_EMAIL_SMTP_PORT") or "465")
    message = EmailMessage()
    message["Subject"] = f"Tennis — resumo pré-live de {manifest.get('report_date', '')}"
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message.set_content(build_digest_text(manifest))
    message.add_alternative(build_digest_html(manifest), subtype="html")

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as smtp:
        smtp.login(username, password)
        smtp.send_message(message, from_addr=sender, to_addrs=recipients)
    return len(recipients)
