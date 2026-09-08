"""Temporary exact edits for reviewed CHANGE030; removed before final commit."""
from pathlib import Path
r = Path(__file__).resolve().parents[1]

def edit(name, old, new):
    p = r / name
    s = p.read_text(encoding='utf-8')
    if old not in s:
        raise RuntimeError(f'Expected baseline text missing in {name}')
    p.write_text(s.replace(old, new), encoding='utf-8')

edit('src/dashboard.py','from . import calibration_store, paper_trading, report_html, run_metrics','from . import audit_observability, dashboard_ui, calibration_store, paper_trading, report_html, run_metrics')
edit('src/dashboard.py','    fingerprint_payload = dict(dashboard)', '''    try:
        dashboard["audit_v1"] = audit_observability.build(root, snapshots_doc, dashboard)
    except Exception as exc:
        # Additive diagnostics must not block the legacy dashboard.
        dashboard["audit_v1"] = {"status": "UNAVAILABLE", "error": type(exc).__name__}
    fingerprint_payload = dict(dashboard)''')
edit('src/dashboard.py','</style></head><body>','{dashboard_ui.CSS}\n</style></head><body>')
edit('src/dashboard.py','function globalView()','function legacyGlobalView()')
edit('src/dashboard.py','function dayView()','function legacyDayView()')
edit('src/dashboard.py',"document.getElementById('day-toggle').addEventListener", "{dashboard_ui.JS}\ndocument.getElementById('day-toggle').addEventListener")
edit('src/dashboard.py',"${{val(value,suffix)}}", "${{/Brier|Loss/i.test(label)&&typeof value==='number'?(value>0&&label.startsWith('Δ')?'+':'')+value.toLocaleString('pt-PT',{{minimumFractionDigits:6,maximumFractionDigits:6}}):val(value,suffix)}}")
edit('src/dashboard.py',"d.toLocaleString('pt-PT',{{dateStyle:'short',timeStyle:'short'}})","d.toLocaleString('pt-PT',{{dateStyle:'short',timeStyle:'short',timeZone:'Europe/Lisbon'}})+' Lisboa'")
edit('src/run_metrics.py','        _COUNTERS.clear()', '''        _COUNTERS.clear()
        _COUNTERS.update(llm_provider_invocations=0, llm_external_requests=0)''')
edit('src/analyze.py','    run_metrics.increment("llm_calls")','''    run_metrics.increment("llm_calls")
    run_metrics.increment("llm_provider_invocations")
    run_metrics.update_context(llm_mode=provider.name)''')
edit('src/llm_provider.py','from .config import (','from . import run_metrics\n\nfrom .config import (')
edit('src/llm_provider.py','        response = client.messages.create(','''        # One SDK request attempt, not a claim about transport retries or billing.
        run_metrics.increment("llm_external_requests")
        response = client.messages.create(''')
for old,new in [('SHARP PRICING — MARKET RESIDUAL','FENZOBOT PRICING — MARKET RESIDUAL'),('Sharp estimate</span>','Fenzobot estimate</span>'),('Captura Sharp Signals:','Captura Fenzobot:'),('Â·','·')]:
    edit('src/report_html.py',old,new)
edit('src/report_html.py',"f'<span>Cobertura <b>{coverage_pct:.0f}%</b></span>'", "f'<span>Cobertura do pricing <b>{coverage_pct:.0f}%</b></span>'")
edit('src/report_html.py',"f'<span>Fiabilidade das fontes <b>{source_pct:.0f}%</b></span>'", "f'<span>Coeficiente de fonte (pricing) <b>{source_pct:.0f}%</b></span>'")
edit('src/report_html.py',"f'<span>Cobertura <b>{_esc(coverage_text)}</b></span></div>'", "f'<span>Cobertura ponderada operacional <b>{_esc(coverage_text)}</b></span></div>'")
edit('src/report_html.py','''    if payload.get("odds_endpoint"):
        parts.append(f"Endpoint: {_esc(payload['odds_endpoint'])}")''','''    endpoint_detail = (
        f'<details><summary>Proveniência técnica — endpoint</summary><p style="overflow-wrap:anywhere">'
        f'{_esc(payload["odds_endpoint"])}</p></details>'
        if payload.get("odds_endpoint") else ""
    )''')
edit('src/report_html.py','''    return f'<div class="mh-odds-meta">{" · ".join(parts)}</div>' if parts else ""''','''    return f'<div class="mh-odds-meta">{" · ".join(parts)}{endpoint_detail}</div>' if parts else ""''')
edit('src/report_html.py',"'<div class=\"pricing-kicker\">FENZOBOT PRICING — MARKET RESIDUAL</div>'", "'<div class=\"pricing-kicker\">FENZOBOT PRICING — MARKET RESIDUAL</div>'\n        '<p class=\"pricing-disclaimer\">PAPER técnico automático e revisão manual 22Bet são estratégias separadas. As coberturas operacional e de pricing têm bases distintas.</p>'")
edit('tests/test_report_contract.py','SHARP PRICING — MARKET RESIDUAL','FENZOBOT PRICING — MARKET RESIDUAL')
edit('tests/test_run_metrics.py','{"llm_calls": 1, "llm_input_tokens": 120}', '{"llm_calls": 1, "llm_input_tokens": 120, "llm_provider_invocations": 0, "llm_external_requests": 0}')
edit('.github/workflows/odds-monitor.yml','      - name: Persistir observações e telemetria', '''      - name: Atualizar vistas derivadas sem aquisição
        run: python -m scripts.refresh_observability
        continue-on-error: true

      - name: Persistir observações e telemetria''')
edit('.github/workflows/odds-monitor.yml','git add data/odds_monitor/ data/market_ledger/ data/rapidapi_usage_log.json','git add data/odds_monitor/ data/market_ledger/ data/rapidapi_usage_log.json data/dashboard/ docs/dashboard/ data/validation/')
p = r / 'README.md'
s = p.read_text(encoding='utf-8')
s += '\n### Continuidade das métricas e auditoria\n\nO CHANGE-2026-09-08-030 acrescenta observabilidade e uma comparação emparelhada descritiva, sem substituir métricas legacy ou alterar decisões. Consulte [o contrato de continuidade](docs/AUDIT_METRIC_CONTINUITY.md). `python -m scripts.refresh_observability` reconstrói apenas vistas locais, sem aquisição ou settlement.\n'
p.write_text(s, encoding='utf-8')
