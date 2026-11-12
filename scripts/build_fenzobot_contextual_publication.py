"""Publica relatórios contextuais e prepara notificações verificáveis."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from html import escape
import json
import os
from pathlib import Path
import sys
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_fenzobot_contextual_report_preview import (  # noqa: E402
    OUTCOMES_PATH,
    build_release_previews,
)
from src import report_notifications, run_metrics  # noqa: E402
from src.config import SITE_BASE_URL  # noqa: E402
from src.contextual_shadow_settlement_v2 import read_jsonl  # noqa: E402
from src.fenzobot_contextual_store import DEFAULT_PATH  # noqa: E402


DEFAULT_OUTPUT_DIR = ROOT / "docs" / "relatorios" / "fenzobot-contextual"


def _name(observation: dict, side: str) -> str:
    return str(((observation.get("players") or {}).get(side) or {}).get("name") or "N/D")


def _chunks(lines: list[str], limit: int = 3800) -> list[str]:
    chunks: list[str] = []
    current = ""
    for line in lines:
        candidate = f"{current}\n{line}".strip()
        if current and len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def build_publication(
    *, output_dir: Path, max_observations: int, now: datetime | None = None,
) -> dict:
    summary = build_release_previews(
        output_dir=output_dir,
        max_observations=max_observations,
    )
    instant = now or datetime.now(timezone.utc)
    outcomes = {
        str(row.get("observation_id")) for row in read_jsonl(OUTCOMES_PATH)
        if row.get("observation_id")
    }
    observations = read_jsonl(DEFAULT_PATH)
    observations.sort(key=lambda row: str(row.get("analyzed_at_utc") or ""), reverse=True)
    if max_observations > 0:
        observations = observations[:max_observations]

    reports: list[dict[str, object]] = []
    notification_lines = [
        "<b>FENZOBOT CONTEXTUAL — RELATÓRIOS PRÉ-JOGO</b>",
        "Fair odd independente do mercado · decisão final humana · sem entrada automática",
        "",
    ]
    for row in observations:
        observation_id = str(row.get("observation_id") or "")
        if not observation_id or observation_id in outcomes:
            continue
        try:
            commence = datetime.fromisoformat(
                str(row.get("commence_time_utc") or "").replace("Z", "+00:00")
            )
        except ValueError:
            continue
        if commence < instant:
            continue
        local_path = output_dir / f"report-{observation_id}.html"
        if not local_path.is_file():
            continue
        url = (
            f"{SITE_BASE_URL}/relatorios/fenzobot-contextual/"
            f"{quote(local_path.name)}"
        )
        reports.append({"url": url, "local_path": str(local_path)})
        player_a = escape(_name(row, "a"))
        player_b = escape(_name(row, "b"))
        notification_lines.append(
            f"• <b>{player_a} vs {player_b}</b> — <a href=\"{url}\">ABRIR RELATÓRIO</a>"
        )

    run_id = os.environ.get("GITHUB_RUN_ID", "").strip()
    metrics_path = os.environ.get(
        "FENZOBOT_RUN_METRICS_PATH", "data/run_metrics_log.json",
    )
    if run_id:
        checkpoint = {
            "status": "contextual_reports_built",
            "phase": "contextual_publication",
            "reports_ok": len(reports),
            "github_run_id": run_id,
        }
        if not run_metrics.update_persisted_run(
            run_id, checkpoint, path=metrics_path,
        ):
            run_metrics.append_run(path=metrics_path, context=checkpoint)

    manifest = report_notifications.write_manifest(
        run_date=instant.date().isoformat(),
        reports=reports,
        telegram_chunks=_chunks(notification_lines) if reports else [],
        email={"enabled": False},
        github_run_id=run_id or None,
    )
    publication_isolation = dict(summary.get("isolation") or {})
    publication_isolation.update({
        "notifications_sent": False,
        "operational_reports_published": bool(reports),
    })
    return {
        **summary,
        "mode": "CONTEXTUAL_PUBLICATION",
        "isolation": publication_isolation,
        "operational_reports_published": len(reports),
        "notification_manifest": str(manifest) if manifest else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-observations", type=int, default=50)
    args = parser.parse_args()
    print(json.dumps(build_publication(
        output_dir=args.output_dir,
        max_observations=max(0, args.max_observations),
    ), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
