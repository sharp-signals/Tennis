"""Camada de apresentação guiada do dashboard, sem alterar métricas de domínio."""

from __future__ import annotations


PANEL_GUIDANCE = {
    "REPORT_HISTORY": "Compara o desempenho observado das versões com divergência ou alinhamento. Leia sempre a taxa com N e intervalo; amostras pequenas não demonstram vantagem futura.",
    "GREEN_STRONG_V1": "Acompanha, em modo SHADOW, os casos que cumpriram o contrato GREEN_STRONG. Serve para validar o sinal prospectivamente; não é uma recomendação nem um resultado financeiro.",
    "GUERRA_SELECTION_V1": "Resume a seleção manual GUERRA e as respetivas legs PAPER ligadas ex ante. A seleção humana, a completude dos pares e a simulação são dimensões diferentes.",
    "PAIRED_COMPARISON": "Compara mercado e Fenzobot exatamente nos mesmos snapshots elegíveis. Scores menores são melhores, mas uma diferença nesta amostra não prova edge.",
    "MARKET_MEMORY": "Mostra as observações de odds já recolhidas e a cobertura temporal disponível. Closing comparável exige uma observação válida anterior ao início; não é automaticamente CLV da 22Bet.",
    "PAPER_TECHNICAL": "Resume entradas PAPER geradas pelas regras automáticas existentes. Não representa dinheiro real e permanece separado da seleção manual GUERRA.",
    "PAPER_22BET": "Resume apenas agregados da folha manual 22Bet. Não publica nomes, snapshot keys nem linhas individuais.",
    "SYSTEM_HEALTH": "System Health mostra se a execução técnica terminou e que recursos consumiu. HEALTHY ou OK não certifica qualidade das odds, validade do modelo ou vantagem económica.",
    "SOURCE_FRESHNESS": "Indica quando cada fonte foi atualizada e se está disponível. STALE ou N/D pede cautela; a causa técnica é mostrada quando o artefacto a fornece.",
    "DAY_READING": "As cores classificam versões de relatório, não partidas adicionais. GREEN_STRONG, PAPER técnico e GUERRA são universos separados.",
}


METRIC_HELP = {
    "Jogos distintos": "Partidas agrupadas; várias versões HTML do mesmo jogo contam uma só vez.",
    "Versões de relatório": "Ficheiros HTML produzidos; um jogo pode ter várias versões.",
    "Snapshots": "Fotografias pré-jogo persistidas em instantes específicos; não equivalem necessariamente a jogos.",
    "Liquidados": "Snapshots ou entradas cujo resultado final já foi associado, conforme o painel.",
    "Liquidadas": "Entradas cujo resultado final já foi associado; pendentes e voids são apresentados separadamente.",
    "Versões verdes": "Versões cuja decisão canónica é verde. Conta versões, não jogos, e não cria GREEN_STRONG nem PAPER.",
    "Versões amarelas": "Versões cuja decisão canónica é amarela. Conta versões, não jogos.",
    "Versões vermelhas": "Versões cuja decisão canónica é vermelha. Conta versões, não jogos.",
    "Versões N/D": "Versões sem classificação canónica demonstrável; consulte o motivo disponível na fonte.",
    "Versões com cor N/D": "Versões para as quais não foi possível provar a cor canónica sem inferência.",
    "GREEN_STRONG": "Candidatos que cumpriram GREEN_STRONG_V1 em SHADOW; não são apostas automáticas.",
    "PAPER técnico": "Entradas simuladas criadas pelo pipeline automático, sem dinheiro real.",
    "PAPER 22Bet": "Entradas manuais 22Bet; uma partida pode originar mais de uma leg.",
    "Market obs.": "Observações válidas já persistidas no Market-Time Ledger.",
    "Acertos": "Previsões corretas dentro da amostra apresentada.",
    "N": "Tamanho da amostra efetivamente usada nesta métrica.",
    "Taxa": "Percentagem de acertos observada; deve ser lida com N e intervalo.",
    "Intervalo": "Faixa de incerteza estatística; não é garantia para o próximo jogo.",
    "Candidatos": "Snapshots que cumpriram todos os critérios da coorte indicada.",
    "Pendentes": "Entradas ou candidatos ainda sem resultado final.",
    "Mercado médio": "Probabilidade média implícita do mercado nos candidatos elegíveis.",
    "Fenzobot médio": "Probabilidade média produzida pelo Fenzobot nos candidatos elegíveis.",
    "Win rate observado": "Percentagem de vitórias observada; não é uma previsão calibrada por si só.",
    "Market Brier": "Erro quadrático das probabilidades do mercado. Menor é melhor; compare na mesma amostra.",
    "Fenzobot Brier": "Erro quadrático das probabilidades do Fenzobot. Menor é melhor; compare na mesma amostra.",
    "Δ Brier": "Fenzobot menos mercado. Negativo favorece o Fenzobot nesta amostra, sem provar edge.",
    "Market Log Loss": "Erro probabilístico do mercado que penaliza confiança excessiva. Menor é melhor.",
    "Fenzobot Log Loss": "Log loss do Fenzobot na mesma amostra. Menor é melhor.",
    "Δ Log Loss": "Fenzobot menos mercado. Negativo favorece o Fenzobot nesta amostra, não certifica vantagem.",
    "Closing comparável N": "Casos com preço de entrada e último preço pré-início comparáveis.",
    "Movimento médio": "Variação média da probabilidade entre entrada e último preço válido pré-início.",
    "Mediana": "Movimento central da amostra, menos sensível a extremos do que a média.",
    "Na direção Fenzobot": "Percentagem de movimentos do mercado no sentido indicado pelo Fenzobot.",
    "GS elegíveis": "Snapshot keys GREEN_STRONG únicas elegíveis para seleção manual.",
    "Candidatos selecionados": "Snapshot keys únicas escolhidas para GUERRA; não conta legs.",
    "Taxa de seleção": "Candidatos GUERRA únicos divididos por GREEN_STRONG elegíveis.",
    "Entradas / legs": "Apostas PAPER individuais; Moneyline e handicap são duas legs.",
    "Entradas": "Entradas ou legs incluídas no agregado deste painel.",
    "W–L": "Vitórias e derrotas; voids e pendentes ficam fora desta dupla.",
    "Win rate": "Vitórias divididas por vitórias mais derrotas liquidadas.",
    "Unidades": "Resultado na unidade original da fonte; não é a simulação fixa em euros.",
    "ROI": "Resultado dividido pelo stake da fonte; não é o ROI da simulação fixa.",
    "Odd média": "Média aritmética das odds decimais válidas incluídas.",
    "Underdogs selecionados": "Candidatos underdog únicos selecionados para a estratégia manual.",
    "Pares completos": "Underdogs com Moneyline e handicap de jogos positivo.",
    "Só Moneyline": "Underdogs com apenas a leg Moneyline reconhecida.",
    "Só handicap +": "Underdogs com apenas o handicap positivo reconhecido.",
    "Incompleto / N/D": "Underdogs cujas legs não permitem provar o par completo.",
    "Resultado acumulado": "Lucro/prejuízo simulado com €10 por leg válida liquidada; não usa stake real.",
    "Total apostado concluído": "€10 por cada leg válida concluída, incluindo voids.",
    "Em aberto": "Exposição simulada de €10 por cada leg válida pendente.",
    "ROI stake fixa": "Resultado simulado dividido pelo total apostado nas legs concluídas.",
    "Entradas resolvidas": "Legs válidas com resultado GANHOU, PERDEU ou VOID.",
    "Void": "Legs anuladas: concluídas com resultado simulado zero.",
    "Excluídas da simulação": "Legs ligadas ex ante excluídas por odd ou resultado inválido.",
    "Observações": "Registos append-only presentes na vista derivada de mercado.",
    "Eventos distintos": "Eventos canónicos distintos cobertos pelas observações.",
    "Com entry market": "Eventos com observação válida representativa do mercado à entrada.",
    "Closing comparável": "Eventos com último preço válido anterior ao início e comparável à entrada.",
    "Cobertura closing": "Percentagem de eventos com closing temporalmente comparável.",
    "Market-only N": "Casos avaliados usando apenas a previsão implícita do mercado.",
    "Market + Fenzobot N": "Casos em que mercado e Fenzobot estão disponíveis conjuntamente.",
    "Brier": "Erro quadrático médio das probabilidades. Menor é melhor; leia com o N.",
    "Log Loss": "Erro probabilístico que penaliza confiança excessiva. Menor é melhor.",
    "N emparelhado": "Snapshots em que mercado e Fenzobot são comparados na mesma amostra.",
    "Previsões elegíveis": "Previsões que passaram os critérios de integridade desta comparação.",
    "Brier mercado": "Brier do mercado calculado apenas na amostra emparelhada.",
    "Brier Fenzobot": "Brier do Fenzobot calculado apenas na amostra emparelhada.",
    "Timestamp": "Momento UTC da última execução, apresentado em hora de Lisboa.",
    "Fase": "Última fase do workflow registada na telemetria.",
    "Elegíveis": "Jogos que passaram os gates anteriores da execução.",
    "Processados": "Jogos efetivamente processados nessa execução.",
    "Análises falhadas": "Análises que falharam na última execução conhecida.",
    "Relatórios falhados": "Relatórios cuja geração falhou na última execução conhecida.",
    "RapidAPI calls": "Chamadas RapidAPI da execução; não é o saldo mensal restante.",
    "LLM calls": "Invocações LLM registadas; não é custo faturado.",
    "Custo LLM USD": "Estimativa disponível do custo LLM, não uma fatura.",
    "Duração": "Duração total registada para a execução.",
    "Frescura da fonte": "Estado AVAILABLE/FRESH, STALE, DEGRADED ou UNAVAILABLE/N/D.",
    "Timestamp da fonte": "Último momento de atualização demonstrável pela fonte.",
}


LEGEND = (
    {"term": "🟢 / 🟡 / 🔴 / N/D", "meaning": "Cor da versão; não é resultado nem aposta."},
    {"term": "GS", "meaning": "Candidato GREEN_STRONG em validação SHADOW."},
    {"term": "PAPER", "meaning": "Entrada simulada; nunca dinheiro real."},
    {"term": "Jogo", "meaning": "Partida distinta, agrupando versões."},
    {"term": "Versão", "meaning": "Um ficheiro HTML; um jogo pode ter vários."},
    {"term": "Snapshot", "meaning": "Fotografia pré-jogo num instante específico."},
    {"term": "Leg", "meaning": "Aposta individual; Moneyline + handicap são duas."},
)


def guidance_payload() -> dict[str, object]:
    """Contrato público, central e reutilizável para ajuda contextual."""
    return {
        "language": "pt-PT",
        "panels": dict(PANEL_GUIDANCE),
        "metrics": dict(METRIC_HELP),
        "legend": [dict(item) for item in LEGEND],
        "status_separation": {
            "execution": "Indica se o workflow correu e terminou segundo a telemetria disponível.",
            "data_quality": "Mede disponibilidade e frescura; consulte os totais Fresh, Stale e N/D.",
            "validation": "Quantifica a evidência prospetiva acumulada; N baixo não permite conclusão.",
            "warning": "HEALTHY/OK não certifica qualidade das odds, validade do modelo nem edge.",
        },
    }


CSS = """
.grid{align-items:start}.panel{padding:16px}.panel .metrics{grid-template-columns:repeat(2,minmax(0,1fr))}
.shell{grid-template-columns:minmax(265px,24vw) minmax(0,1fr)}.main{padding:24px clamp(16px,2vw,32px) 36px}
.empty{padding:10px 0}.status-strip{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:0 0 12px}
.status-tile{padding:12px;background:var(--panel);border:1px solid var(--line);border-radius:10px;min-width:0}.status-tile h2{font-size:10px;letter-spacing:.06em;text-transform:uppercase;margin:0 0 8px}.status-tile p{margin:5px 0;color:var(--dim);font-size:12px;overflow-wrap:anywhere}
.guide-warning{border-left:3px solid var(--yellow);padding:10px 12px;margin:0 0 14px;background:#171d22;color:#d9c897;border-radius:0 9px 9px 0}.dashboard-legend{display:flex;flex-wrap:wrap;gap:7px;margin:0 0 16px}.legend-item{display:flex;gap:7px;align-items:flex-start;min-width:0;padding:7px 9px;border:1px solid var(--line);border-radius:999px;background:#0e1721;color:var(--dim);font-size:11px}.legend-item b{color:var(--text);white-space:nowrap}
.panel-guide{color:#b9cbe0;font-size:12px;line-height:1.55;margin:-5px 0 14px;max-width:78ch}.audit-detail{margin-top:12px}.audit-detail summary{cursor:pointer;color:var(--steel);padding:8px 0;font-weight:600}.audit-detail pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:11px;color:var(--dim)}.audit-caption{color:var(--dim);font-size:12px;margin:0 0 14px;line-height:1.5}.paired-panel{border-color:#365573}.paired-panel .metrics strong{font-size:17px}
.metric,.card,.fresh>div{position:relative}.metric span,.card .label{padding-right:26px}.help-trigger{position:absolute;top:7px;right:7px;width:22px;height:22px;border:1px solid #47647e;border-radius:50%;background:#132638;color:#9fc8e5;cursor:pointer;font-size:12px;font-weight:750;line-height:18px;padding:0;z-index:2}.help-trigger:hover,.help-trigger:focus-visible{outline:2px solid var(--steel);outline-offset:2px;background:#1a3650;color:#fff}.help-copy{margin-top:8px;padding:8px 9px;border-radius:7px;background:#0c1722;color:#c1d3e4;font-size:11px;line-height:1.45;overflow-wrap:anywhere}.card-filter{display:block;width:100%;padding:0;border:0;background:transparent;text-align:left;color:inherit;cursor:pointer}.card:has(.card-filter):hover{border-color:var(--steel)}
.row{display:grid;grid-template-columns:minmax(0,1fr) auto 24px;align-items:center}.row>span{grid-column:1}.row>b{grid-column:2}.row>.help-trigger{position:static;grid-column:3;margin-left:2px}.row>.help-copy{grid-column:1/-1}
.flat-sim{margin:14px 0 4px;padding:15px;border:1px solid #3f6c63;border-radius:12px;background:linear-gradient(145deg,#102620,#152333 72%)}.flat-sim h3{margin:0 0 4px;font-size:16px}.flat-sim .sim-status{font-size:10px;letter-spacing:.08em;color:var(--green)}.flat-sim.DEGRADED{border-color:#806822}.flat-sim.DEGRADED .sim-status{color:var(--yellow)}.flat-sim.UNAVAILABLE{border-color:var(--line)}.flat-sim.UNAVAILABLE .sim-status{color:var(--dim)}.sim-note{color:var(--dim);font-size:11px;line-height:1.5;margin:10px 0 0}.sim-result{font-size:24px!important}.sim-result.positive{color:var(--green)}.sim-result.negative{color:var(--red)}
@media(max-width:900px){.shell{grid-template-columns:1fr}.status-strip{grid-template-columns:1fr}}@media(max-width:560px){.dashboard-legend{display:grid;grid-template-columns:1fr}.legend-item{border-radius:10px}.flat-sim{padding:12px}.help-copy{font-size:12px}.panel-guide{max-width:none}}
"""


JS = r"""
let helpSequence=0;
function helpText(label){return DATA.guidance_v1?.metrics?.[label]||''}
function helpUI(label){const copy=helpText(label);if(!copy)return'';const id=`help-${++helpSequence}`;return `<button type="button" class="help-trigger" aria-label="Explicar ${esc(label)}" aria-expanded="false" aria-controls="${id}">?</button><div id="${id}" class="help-copy" role="note" hidden>${esc(copy)}</div>`}
function panelGuide(key){const copy=DATA.guidance_v1?.panels?.[key];return copy?`<p class="panel-guide">${esc(copy)}</p>`:''}
function wireHelp(){document.querySelectorAll('.help-trigger').forEach(button=>button.addEventListener('click',event=>{event.stopPropagation();const copy=document.getElementById(button.getAttribute('aria-controls'));if(!copy)return;const open=button.getAttribute('aria-expanded')==='true';button.setAttribute('aria-expanded',String(!open));copy.hidden=open}));document.onkeydown=event=>{if(event.key!=='Escape')return;document.querySelectorAll('.help-trigger[aria-expanded="true"]').forEach(button=>{button.setAttribute('aria-expanded','false');const copy=document.getElementById(button.getAttribute('aria-controls'));if(copy)copy.hidden=true})}}
function auditStatus(){const a=DATA.audit_v1||{},q=a.source_quality||{},s=DATA.system_health||{},p=a.paired_comparison||{},copy=DATA.guidance_v1?.status_separation||{},latest=s.latest||{};return `<div class="status-strip" aria-label="Execução, dados e validação"><section class="status-tile"><h2>1 · Execução</h2><span class="health ${esc(s.status)}">${esc(s.status||'UNKNOWN')}</span><p>${esc(copy.execution||'Estado técnico da execução.')}</p><p>Última execução: ${fmtTime(latest.timestamp)}</p></section><section class="status-tile"><h2>2 · Qualidade dos dados</h2><p>Fresh: ${val(q.fresh)} · Stale: ${val(q.stale)} · N/D: ${val(q.unknown)}</p><p>${esc(copy.data_quality||'Disponibilidade e frescura das fontes.')}</p><p>Recolha: ${fmtTime(q.last_monitor_capture_utc)} · Ledger: ${esc(a.ledger_status||'UNAVAILABLE')}</p></section><section class="status-tile"><h2>3 · Validação do sinal</h2><p>N emparelhado: ${val(p.sample_size)} · GREEN_STRONG: ${val(DATA.green_strong_v1?.sample?.candidates)}</p><p>${esc(copy.validation||'Evidência prospectiva acumulada.')}</p><p>Experimental — não é OOS primário; sem promoção automática.</p><p>Publicação: N/D — geração não prova publicação.</p></section></div><p class="guide-warning"><b>Leitura essencial:</b> ${esc(copy.warning||'HEALTHY/OK não certifica qualidade das odds, validade do modelo nem edge.')}</p>`}
function dashboardLegend(){const items=DATA.guidance_v1?.legend||[];return `<div class="dashboard-legend" aria-label="Legenda permanente">${items.map(item=>`<span class="legend-item"><b>${esc(item.term)}</b><span>${esc(item.meaning)}</span></span>`).join('')}</div>`}
function auditDetails(title,obj){return `<details class="audit-detail"><summary>${esc(title)}</summary><pre>${esc(JSON.stringify(obj,null,2))}</pre></details>`}
function pairedPanel(){const p=DATA.audit_v1?.paired_comparison||{},m=p.market||{},f=p.fenzobot||{},d=p.delta||{};return panel('Mercado vs Fenzobot — mesma amostra','PAIRED_COMPARISON · descritivo · experimental',`<div class="metrics">${metric('N emparelhado',p.sample_size)}${metric('Previsões elegíveis',p.eligible_forecasts)}${metric('Brier mercado',m.brier_score)}${metric('Brier Fenzobot',f.brier_score)}${metric('Δ Brier',d.brier_score)}${metric('Δ Log Loss',d.log_loss)}</div><p class="audit-caption">Menor score é melhor. Δ = Fenzobot − mercado; negativo favorece o modelo nesta amostra, não prova vantagem.</p>${auditDetails('Scores, exclusões e versões',p)}`,'paired-panel','PAIRED_COMPARISON')}
function flatStakeSimulation(sim){sim=sim||{};const status=sim.status||'UNAVAILABLE',resolved=Number(sim.included_resolved_entries||0),pending=Number(sim.pending_entries||0),excluded=Number(sim.excluded_entries||0),hasResult=resolved>0&&typeof sim.net_profit_eur==='number';const result=hasResult?eur(sim.net_profit_eur,true):'N/D — ainda sem resultados concluídos';const reasons=Object.entries(sim.exclusion_reasons||{}).map(([reason,count])=>`${esc(reason)}: ${val(count)}`).join(' · ');return `<section class="flat-sim ${esc(status)}"><div class="sim-status">${esc(status)}</div><h3>Se apostássemos €10 em cada aposta GUERRA</h3>${status==='UNAVAILABLE'&&resolved===0&&pending===0?'<div class="note">Ainda sem amostra válida — não interpretar como resultado €0.</div>':''}<div class="metrics"><div class="metric"><span>Resultado acumulado</span><strong class="sim-result ${hasResult&&sim.net_profit_eur>0?'positive':hasResult&&sim.net_profit_eur<0?'negative':''}">${result}</strong>${helpUI('Resultado acumulado')}</div>${metric('Total apostado concluído',resolved?eur(sim.resolved_stake_eur):null)}${metric('Em aberto',pending?eur(sim.pending_exposure_eur):eur(0))}${metric('ROI stake fixa',resolved?sim.roi_pct:null,'%')}</div><details class="audit-detail"><summary>Ver composição da simulação</summary><div class="metrics">${metric('Entradas resolvidas',sim.included_resolved_entries)}${metric('Pendentes',sim.pending_entries)}${metric('Void',sim.void_entries)}${metric('Excluídas da simulação',sim.excluded_entries)}</div>${excluded?`<p class="audit-caption">Motivos agregados: ${reasons||'N/D — motivo não publicado pela fonte.'}</p>`:''}</details><p class="sim-note">Simulação. €10 por aposta/leg; não é dinheiro real. Um underdog com Moneyline + handicap conta como duas apostas.</p></section>`}
function foldPanel(node,message){if(!node)return;const details=document.createElement('details');details.className='audit-detail';const summary=document.createElement('summary');summary.textContent='Ver todas as métricas';details.append(summary);const children=[...node.children].filter(child=>!child.matches('h2,.eyebrow,.panel-guide,.flat-sim'));for(const child of children)details.append(child);if(message){const note=document.createElement('p');note.className='audit-caption';note.textContent=message;node.append(note)}node.append(details)}
function globalView(){helpSequence=0;const host=document.createElement('div');host.innerHTML=legacyGlobalView();const grid=host.querySelector('.grid');const find=title=>[...host.querySelectorAll('article.panel')].find(n=>n.querySelector('h2')?.textContent===title);const gs=find('Validação prospetiva'),gu=find('Seleção manual Guerra'),health=find('Saúde da execução'),mm=find('Histórico do mercado');if(gs){gs.classList.remove('wide');if(!(DATA.green_strong_v1?.sample?.candidates>0))foldPanel(gs,'N=0 ou N/D — acumulação prospetiva. Sem conclusão possível.');gs.insertAdjacentHTML('beforeend',auditDetails('Disponibilidade e motivos de exclusão',DATA.audit_v1?.green_diagnostics||{}))}if(gu){gu.insertAdjacentHTML('beforeend',flatStakeSimulation(DATA.guerra_selection_v1?.flat_stake_simulation));if(DATA.guerra_selection_v1?.status!=='AVAILABLE')foldPanel(gu,'N/D — agregado da estratégia indisponível. Não demonstra ausência de seleções; instalação da Sheet não auditada.')}if(health){foldPanel(health,'Alertas existentes preservados. LLM calls é um contador legado de invocações, não faturação.');health.insertAdjacentHTML('beforeend',auditDetails('Provider e chamadas externas',DATA.audit_v1?.llm||{}))}if(mm){mm.querySelector('.eyebrow').insertAdjacentHTML('afterend','<div class="note warning">Séries legacy descritivas: os N podem diferir. Não comparar diretamente estes scores; usar o painel emparelhado.</div>');mm.insertAdjacentHTML('beforeend',`<p class="audit-caption">Cobertura legacy: ${val(DATA.market_memory.events_with_comparable_closing)}/${val(DATA.market_memory.distinct_events)} eventos de snapshots, incluindo legacy. Último mercado pré-início comparável não é CLV 22Bet.</p><p class="audit-caption">Primeiro registo no ledger: ${fmtTime(DATA.audit_v1?.source_quality?.first_ledger_capture_utc)}. Barras anteriores não comprovam dias monitorizados com zero observações.</p>`)}if(grid)grid.firstElementChild.insertAdjacentHTML('afterend',pairedPanel());const cardsHost=host.querySelector('.cards');if(cardsHost){cardsHost.insertAdjacentHTML('beforeend',`<div class="card"><div class="label">Versões com cor N/D</div><div class="value">${val(DATA.global.report_colors.UNAVAILABLE)}</div>${helpUI('Versões com cor N/D')}</div>`);cardsHost.insertAdjacentHTML('afterend','<p class="audit-caption">Jogos distintos agrupam versões do mesmo matchup. total_reports preserva a contagem legacy de ficheiros/versões. As cores e os filtros contam versões, não jogos; snapshots contam fotografias. Legs PAPER não são jogos independentes. Cor operacional não é resultado de aposta.</p>')}return auditStatus()+dashboardLegend()+host.innerHTML}
function dayView(){helpSequence=0;return auditStatus()+dashboardLegend()+legacyDayView()}
"""
