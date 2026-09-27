"""Publicação verificável e envio diferido das notificações de relatórios."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from . import run_metrics
from .email_reports import send_prepared_run_report_email
from .telegram_bot import send_message

MANIFEST_ENV = "FENZOBOT_REPORT_NOTIFICATION_MANIFEST"
DEFAULT_MANIFEST_NAME = "fenzobot-report-notifications.json"
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_INTERVAL_SECONDS = 4.0
HTTP_TIMEOUT_SECONDS = 5
PUBLICATION_TIMEOUT = "REPORT_PUBLICATION_TIMEOUT"
PUBLICATION_STATUSES = frozenset({"NOT_APPLICABLE", "PENDING", "READY", "TIMEOUT"})
NOTIFICATION_STATUSES = frozenset({"REPORTS_DEFERRED", "REPORTS_SENT", "REPORTS_WITHHELD"})


class PublicationTimeoutError(RuntimeError):
    pass


def manifest_path() -> Path:
    configured = os.environ.get(MANIFEST_ENV, "").strip()
    if configured:
        return Path(configured)
    runner_temp = os.environ.get("RUNNER_TEMP", "").strip()
    return Path(runner_temp or tempfile.gettempdir()) / DEFAULT_MANIFEST_NAME


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("Manifesto de notificações inválido.")
    return payload


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def write_manifest(
    *,
    run_date: str,
    reports: list[Mapping[str, object]],
    telegram_chunks: list[str],
    email: Mapping[str, object],
    github_run_id: str | None = None,
    path: Path | None = None,
) -> Path | None:
    """Grava um manifesto efémero, sem credenciais nem respostas de providers."""
    if not reports:
        return None
    serialized_reports = []
    for report in reports:
        url = str(report.get("url") or "")
        local_path = Path(str(report.get("local_path") or ""))
        if not url or not local_path.is_file():
            raise ValueError("Relatório sem URL ou HTML local verificável.")
        serialized_reports.append({
            "url": url,
            "local_path": str(local_path.resolve()),
            "sha256": _sha256(local_path.read_bytes()),
        })
    run_id = str(github_run_id or os.environ.get("GITHUB_RUN_ID") or "local")
    payload = {
        "schema_version": 1,
        "github_run_id": run_id,
        "run_date": str(run_date),
        "report_urls": [item["url"] for item in serialized_reports],
        "reports": serialized_reports,
        "telegram_chunks": [str(chunk) for chunk in telegram_chunks],
        "email": dict(email),
        "report_publication": {
            "status": "PENDING",
            "expected": len(serialized_reports),
            "ready": 0,
        },
        "report_notification_status": "REPORTS_DEFERRED",
    }
    target = path or manifest_path()
    _write_json_atomic(target, payload)
    return target


def _cache_busted_url(url: str, run_id: str, attempt: int) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["fenzobot_run"] = run_id
    query["readiness_attempt"] = str(attempt)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _persist_telemetry(manifest: Mapping[str, object]) -> None:
    run_id = str(manifest.get("github_run_id") or "")
    if not run_id:
        return
    values = {
        "report_publication": dict(manifest.get("report_publication") or {}),
        "report_notification_status": manifest.get("report_notification_status"),
    }
    if manifest.get("email_delivery"):
        values["email_delivery"] = dict(manifest["email_delivery"])
    metrics_path = os.environ.get("FENZOBOT_RUN_METRICS_PATH", "data/run_metrics_log.json")
    run_metrics.update_persisted_run(run_id, values, path=metrics_path)


def _set_publication(
    manifest: dict,
    path: Path,
    status: str,
    ready: int,
    *,
    reason_code: str | None = None,
) -> None:
    if status not in PUBLICATION_STATUSES:
        raise ValueError(f"Estado de publicação inválido: {status}")
    publication = {
        "status": status,
        "expected": len(manifest.get("reports") or []),
        "ready": int(ready),
    }
    if reason_code:
        publication["reason_code"] = reason_code
    manifest["report_publication"] = publication
    if status == "TIMEOUT":
        manifest["report_notification_status"] = "REPORTS_WITHHELD"
    _write_json_atomic(path, manifest)
    _persist_telemetry(manifest)


def wait_for_publication(
    *,
    path: Path | None = None,
    timeout_seconds: float | None = None,
    interval_seconds: float | None = None,
    get: Callable[..., object] = requests.get,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict:
    """Espera por HTTP 200 e igualdade byte-a-byte de todos os HTML."""
    target = path or manifest_path()
    if not target.exists():
        return {"status": "NOT_APPLICABLE", "expected": 0, "ready": 0}
    manifest = _read_json(target)
    reports = manifest.get("reports") or []
    if not reports:
        return {"status": "NOT_APPLICABLE", "expected": 0, "ready": 0}
    timeout = timeout_seconds
    if timeout is None:
        timeout = float(os.environ.get("REPORT_PUBLICATION_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
    interval = interval_seconds
    if interval is None:
        interval = float(os.environ.get("REPORT_PUBLICATION_POLL_SECONDS", DEFAULT_INTERVAL_SECONDS))
    started = monotonic()
    attempt = 0
    run_id = str(manifest.get("github_run_id") or "")
    while True:
        attempt += 1
        ready = 0
        timed_out = False
        for report in reports:
            remaining = max(0.0, timeout - (monotonic() - started))
            if remaining <= 0:
                timed_out = True
                break
            try:
                response = get(
                    _cache_busted_url(str(report["url"]), run_id, attempt),
                    timeout=min(HTTP_TIMEOUT_SECONDS, remaining),
                    headers={"Cache-Control": "no-cache"},
                )
            except requests.RequestException:
                continue
            if getattr(response, "status_code", None) == 200 and _sha256(response.content) == report.get("sha256"):
                ready += 1
        if ready == len(reports):
            _set_publication(manifest, target, "READY", ready)
            return dict(manifest["report_publication"])
        if timed_out or monotonic() - started >= max(0.0, timeout):
            _set_publication(
                manifest, target, "TIMEOUT", ready,
                reason_code=PUBLICATION_TIMEOUT,
            )
            raise PublicationTimeoutError(PUBLICATION_TIMEOUT)
        _set_publication(manifest, target, "PENDING", ready)
        sleep(max(0.0, interval))


def _delivery_state_path(path: Path, run_id: str) -> Path:
    safe_run_id = "".join(character for character in run_id if character.isalnum() or character in "-_") or "local"
    return path.with_name(f"{path.stem}-{safe_run_id}-delivery.json")


def send_ready_notifications(
    *,
    path: Path | None = None,
    telegram_sender: Callable[[str], object] = send_message,
    email_sender: Callable[[Mapping[str, object]], dict] = send_prepared_run_report_email,
) -> dict:
    """Envia exatamente a apresentação do manifesto, com checkpoint por run."""
    target = path or manifest_path()
    if not target.exists():
        return {"status": "NOT_APPLICABLE"}
    manifest = _read_json(target)
    publication = manifest.get("report_publication") or {}
    if publication.get("status") != "READY":
        manifest["report_notification_status"] = "REPORTS_WITHHELD"
        _write_json_atomic(target, manifest)
        _persist_telemetry(manifest)
        return {"status": "REPORTS_WITHHELD", "reason_code": "REPORTS_NOT_READY"}
    if manifest.get("report_notification_status") == "REPORTS_SENT":
        return {
            "status": "REPORTS_SENT",
            "telegram_chunks_sent": len(manifest.get("telegram_chunks") or []),
            "email_delivery": dict(manifest.get("email_delivery") or {}),
        }

    run_id = str(manifest.get("github_run_id") or "local")
    state_path = _delivery_state_path(target, run_id)
    try:
        state = _read_json(state_path)
    except (OSError, ValueError, json.JSONDecodeError):
        state = {"github_run_id": run_id, "telegram_chunks_sent": 0}
    if state.get("github_run_id") != run_id:
        raise ValueError("Checkpoint de entrega pertence a outra run.")

    chunks = [str(chunk) for chunk in manifest.get("telegram_chunks") or []]
    sent_count = min(int(state.get("telegram_chunks_sent") or 0), len(chunks))
    for index in range(sent_count, len(chunks)):
        telegram_sender(chunks[index])
        state["telegram_chunks_sent"] = index + 1
        _write_json_atomic(state_path, state)

    email_delivery = state.get("email_delivery")
    if not isinstance(email_delivery, dict) or email_delivery.get("status") != "SENT":
        email_delivery = email_sender(manifest.get("email") or {})
        state["email_delivery"] = dict(email_delivery)
        _write_json_atomic(state_path, state)
    manifest["email_delivery"] = dict(email_delivery)
    complete = (
        state.get("telegram_chunks_sent") == len(chunks)
        and email_delivery.get("status") == "SENT"
    )
    manifest["report_notification_status"] = (
        "REPORTS_SENT" if complete else "REPORTS_WITHHELD"
    )
    _write_json_atomic(target, manifest)
    _persist_telemetry(manifest)
    return {
        "status": manifest["report_notification_status"],
        "telegram_chunks_sent": state.get("telegram_chunks_sent", 0),
        "email_delivery": dict(email_delivery),
    }


def withhold_notifications(
    reason_code: str,
    *,
    path: Path | None = None,
) -> dict:
    """Marca a entrega como retida sem enviar nada nem alterar a análise."""
    target = path or manifest_path()
    if not target.exists():
        return {"status": "NOT_APPLICABLE"}
    manifest = _read_json(target)
    manifest["report_notification_status"] = "REPORTS_WITHHELD"
    manifest["notification_reason_code"] = str(reason_code)
    _write_json_atomic(target, manifest)
    _persist_telemetry(manifest)
    return {"status": "REPORTS_WITHHELD", "reason_code": str(reason_code)}


def _cli() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("wait", "send", "withhold"))
    parser.add_argument("--reason", default="REPORT_NOTIFICATION_FAILED")
    args = parser.parse_args()
    try:
        if args.command == "wait":
            result = wait_for_publication()
        elif args.command == "send":
            result = send_ready_notifications()
        else:
            result = withhold_notifications(args.reason)
    except PublicationTimeoutError:
        print(PUBLICATION_TIMEOUT)
        return 1
    except Exception:
        if args.command == "send":
            withhold_notifications("REPORT_NOTIFICATION_FAILED")
            print("REPORT_NOTIFICATION_FAILED")
            return 1
        raise
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if args.command == "send" and result.get("status") == "REPORTS_WITHHELD" and result.get("reason_code") == "REPORTS_NOT_READY":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
