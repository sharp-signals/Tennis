"""Presentation-only additions. Existing cards/metrics remain in the DOM."""
CSS = """
.grid{align-items:start}.panel{padding:16px}.panel .metrics{grid-template-columns:repeat(2,minmax(0,1fr))}
.shell{grid-template-columns:minmax(265px,24vw) minmax(0,1fr)}.main{padding:24px clamp(16px,2vw,32px) 36px}
.empty{padding:10px 0}.status-strip{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:0 0 16px}
.status-tile{padding:12px;background:var(--panel);border:1px solid var(--line);border-radius:10px;min-width:0}
.status-tile h2{font-size:10px;letter-spacing:.06em;text-transform:uppercase;margin:0 0 8px}
.status-tile p{margin:5px 0;color:var(--dim);font-size:12px;overflow-wrap:anywhere}
.audit-detail{margin-top:12px}.audit-detail summary{cursor:pointer;color:var(--steel);padding:8px 0;font-weight:600}
.audit-detail pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:11px;color:var(--dim)}
.audit-caption{color:var(--dim);font-size:12px;margin:0 0 14px;line-height:1.5}
.paired-panel{border-color:#365573}.paired-panel .metrics strong{font-size:17px}
@media(max-width:900px){.shell{grid-template-columns:1fr}.status-strip{grid-template-columns:1fr}}
"""
JS = r"""
function auditStatus(){
 const a=DATA.audit_v1||{},q=a.source_quality||{},s=DATA.system_health||{},p=a.paired_comparison||{};
 const latest=s.latest||{};
 return `<div class="status-strip" aria-label="Execução, dados e validação">
 <section class="status-tile"><h2>Execução</h2><span class="health ${esc(s.status)}">${esc(s.status||'UNKNOWN')}</span><p>Última execução: ${fmtTime(latest.timestamp)}</p><p>Estado do programa, não certifica os dados.</p></section>
 <section class="status-tile"><h2>Qualidade e atualização dos dados</h2><p>Fresh: ${val(q.fresh)} · Stale: ${val(q.stale)} · N/D: ${val(q.unknown)}</p><p>Diagnóstico do monitor; não altera o gate de pricing.</p><p>Recolha: ${fmtTime(q.last_monitor_capture_utc)}</p><p>Vista de mercado: ${fmtTime(DATA.market_memory?.generated_at_utc)}</p><p>Ledger: ${esc(a.ledger_status||'UNAVAILABLE')}</p><p>Última atualização: ${esc(a.last_refresh_attempt?.market_memory||'N/D')}</p></section>
 <section class="status-tile"><h2>Evidência para validação</h2><p>N emparelhado: ${val(p.sample_size)} · GREEN_STRONG: ${val(DATA.green_strong_v1?.sample?.candidates)}</p><p>Experimental — sem promoção automática.</p><p>Sync 22Bet: ${fmtTime(DATA.paper_22bet?.synced_at_utc)}</p><p>Publicação: N/D — geração não prova publicação.</p></section></div>`;
}
function auditDetails(title,obj){return `<details class="audit-detail"><summary>${esc(title)}</summary><pre>${esc(JSON.stringify(obj,null,2))}</pre></details>`}
function pairedPanel(){
 const p=DATA.audit_v1?.paired_comparison||{},m=p.market||{},f=p.fenzobot||{},d=p.delta||{};
 return panel('Mercado vs Fenzobot — mesma amostra','Descritivo · experimental · não é OOS primário',
 `<div class="metrics">${metric('N emparelhado',p.sample_size)}${metric('Previsões elegíveis',p.eligible_forecasts)}${metric('Brier mercado',m.brier_score)}${metric('Brier Fenzobot',f.brier_score)}${metric('Δ Brier',d.brier_score)}${metric('Δ Log Loss',d.log_loss)}</div>
 <p class="audit-caption">Mesmos snapshots e mercado congelado no pricing. Menor score é melhor. Δ = Fenzobot − mercado; negativo favorece o modelo nesta amostra, não prova vantagem.</p>
 ${auditDetails('Scores, exclusões e versões',p)}`,'paired-panel');
}
function foldPanel(node,message){
 if(!node)return;
 const details=document.createElement('details');details.className='audit-detail';
 const summary=document.createElement('summary');summary.textContent='Ver todas as métricas';details.append(summary);
 const children=[...node.children].slice(2);for(const child of children)details.append(child);
 if(message){const note=document.createElement('p');note.className='audit-caption';note.textContent=message;node.append(note)}
 node.append(details);
}
function globalView(){
 const host=document.createElement('div');host.innerHTML=legacyGlobalView();
 const grid=host.querySelector('.grid');
 const find=title=>[...host.querySelectorAll('article.panel')].find(n=>n.querySelector('h2')?.textContent===title);
 const gs=find('GREEN_STRONG_V1'),gu=find('GUERRA_SELECTION_V1'),health=find('System Health'),mm=find('Market Memory / Odds History');
 if(gs){gs.classList.remove('wide');if(!(DATA.green_strong_v1?.sample?.candidates>0))foldPanel(gs,'N=0 ou N/D — acumulação prospetiva. Sem conclusão possível.');gs.insertAdjacentHTML('beforeend',auditDetails('Disponibilidade e motivos de exclusão',DATA.audit_v1?.green_diagnostics||{}))}
 if(gu&&DATA.guerra_selection_v1?.status!=='AVAILABLE')foldPanel(gu,'N/D — agregado da estratégia indisponível. Não demonstra ausência de seleções; instalação da Sheet não auditada.');
 if(health){health.querySelector('h2').textContent='Detalhe da execução';foldPanel(health,'Alertas existentes preservados. llm_calls é um contador legado de invocações, não faturação.');health.insertAdjacentHTML('beforeend',auditDetails('Provider e chamadas externas',DATA.audit_v1?.llm||{}))}
 if(mm){mm.querySelector('.eyebrow').insertAdjacentHTML('afterend','<div class="note warning">Séries legacy descritivas: os N podem diferir. Não comparar diretamente estes scores; usar o painel emparelhado.</div>');mm.insertAdjacentHTML('beforeend',`<p class="audit-caption">Cobertura legacy: ${val(DATA.market_memory.events_with_comparable_closing)}/${val(DATA.market_memory.distinct_events)} eventos de snapshots, incluindo legacy. Último mercado pré-início comparável não é CLV 22Bet.</p><p class="audit-caption">Primeiro registo no ledger: ${fmtTime(DATA.audit_v1?.source_quality?.first_ledger_capture_utc)}. Barras anteriores não comprovam dias monitorizados com zero observações.</p>`)}
 if(grid)grid.firstElementChild.insertAdjacentHTML('afterend',pairedPanel());
 const cardsHost=host.querySelector('.cards');
 if(cardsHost){cardsHost.insertAdjacentHTML('beforeend',`<div class="card"><div class="label">Cor indisponível / N/D</div><div class="value">${val(DATA.global.report_colors.UNAVAILABLE)}</div></div>`);cardsHost.querySelector('.card .label').textContent='Relatórios / versões';cardsHost.insertAdjacentHTML('afterend','<p class="audit-caption">Relatórios contam ficheiros e versões; snapshots contam fotografias. Legs PAPER não são jogos independentes. Cor operacional não é resultado de aposta.</p>')}
 return auditStatus()+host.innerHTML;
}
function dayView(){return auditStatus()+legacyDayView()}
"""
