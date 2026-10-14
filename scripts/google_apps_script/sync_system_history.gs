/**
 * CHANGE-2026-09-28-061; CHANGE-2026-10-04-074
 * Sincroniza a Sheet colaborativa "Fenzobot — Histórico & Aprendizagem" a
 * partir do JSON canónico publicado no repositório.
 *
 * Segurança / método:
 * - O GitHub continua a ser a fonte de verdade; esta Sheet é uma vista.
 * - O payload já exclui relatórios HTML repetidos das métricas.
 * - Se o fingerprint não mudou, não reescreve células nem cria versões.
 * - Não usa Claude, RapidAPI nem qualquer API de odds.
 *
 * Propriedades de script opcionais:
 * - GITHUB_REPOSITORY     sharp-signals/Tennis (opcional)
 * - GITHUB_BRANCH         main (opcional)
 * - SYSTEM_HISTORY_SHEET_ID (opcional; já tem uma predefinição)
 */

const SYSTEM_HISTORY_SYNC = {
  defaultRepository: 'sharp-signals/Tennis',
  defaultBranch: 'main',
  defaultSpreadsheetId: '1KojvHlLEJ-d4UCaN-Jb0Eu3fEIATbQmoP6_FqGYmWdw',
  sourcePath: 'data/dashboard/system_history_analytics.json',
  manualPaperPath: 'data/manual_paper_22bet_authoritative.json',
  fingerprintProperty: 'SYSTEM_HISTORY_LAST_FINGERPRINT',
  projectionSchemaVersion: '2026-10-14-factor-coverage-diagnostics-v1',
  triggerHandler: 'syncSystemHistoryToSheet',
};

function syncSystemHistoryToSheet() {
  const properties = PropertiesService.getScriptProperties();
  const repository = properties.getProperty('GITHUB_REPOSITORY') || SYSTEM_HISTORY_SYNC.defaultRepository;
  const branch = properties.getProperty('GITHUB_BRANCH') || SYSTEM_HISTORY_SYNC.defaultBranch;
  const spreadsheetId = properties.getProperty('SYSTEM_HISTORY_SHEET_ID') || SYSTEM_HISTORY_SYNC.defaultSpreadsheetId;
  const payload = fetchSystemHistoryPayload_(repository, branch);
  let manualPaper = {};
  try {
    manualPaper = fetchPublicJson_(repository, branch, SYSTEM_HISTORY_SYNC.manualPaperPath);
  } catch (error) {
    // O Histórico canónico não pode deixar de atualizar só porque a Sheet
    // manual ainda não publicou o seu primeiro agregado.
    manualPaper = {manual_paper_fetch_error: String(error && error.message || error)};
  }
  const continuity = payload.forward_only_continuity || null;
  const prospective = continuity && continuity.prospective || null;
  const historyFingerprint = continuity
    ? String((continuity.historical_baseline || {}).sha256_at_t0 || '') + ':' + String((prospective || {}).input_fingerprint_sha256 || '')
    : String(payload.input_fingerprint_sha256 || '');
  const manualFingerprint = String((manualPaper || {}).data_fingerprint || 'manual-paper-unavailable');
  // A versão da projeção faz parte do fingerprint. Assim, uma atualização
  // apenas visual/estrutural do Apps Script não fica bloqueada por o JSON
  // canónico continuar exatamente igual.
  const fingerprint = SYSTEM_HISTORY_SYNC.projectionSchemaVersion + ':' + historyFingerprint + ':' + manualFingerprint;
  if (!historyFingerprint) throw new Error('O JSON canónico não tem input_fingerprint_sha256.');
  const spreadsheet = SpreadsheetApp.openById(spreadsheetId);
  const attributionSheetsMissing = [
    'Atribuição — fatores',
    'Atribuição — força do peso',
    'Cobertura — fatores',
    'Cobertura — motivos',
    'GUERRA — fatores',
    'GUERRA — segmentos',
    'GUERRA — qualidade',
  ].some(name => {
    const sheet = spreadsheet.getSheetByName(name);
    return !sheet || sheet.getLastRow() < 2;
  });
  if (
    properties.getProperty(SYSTEM_HISTORY_SYNC.fingerprintProperty) === fingerprint
    && !attributionSheetsMissing
  ) {
    return 'Histórico sem alterações; Sheet preservada.';
  }

  if (continuity) {
    writeProspectiveSystemHistory_(spreadsheet, prospective || {});
  } else {
    writeSystemHistoryWorkbook_(spreadsheet, payload);
  }
  // É uma auditoria nova, deliberadamente fora das folhas históricas
  // protegidas. Em forward-only, usa o produto operacional atual para poder
  // estudar todos os snapshots canónicos sem recalcular as métricas legadas.
  const currentOperational = continuity && continuity.operational_current || (payload.operational || {});
  writeFactorAttributionSheets_(spreadsheet, currentOperational.factor_attribution || {});
  writeFactorCoverageSheets_(spreadsheet, currentOperational.factor_coverage || {});
  writeChallengerManualPaperSheet_(spreadsheet, manualPaper || {});
  writeGuerraAuditSheets_(spreadsheet, manualPaper || {});
  writeWeightDecisionPanel_(spreadsheet, currentOperational.factor_attribution || {}, manualPaper || {});
  properties.setProperty(SYSTEM_HISTORY_SYNC.fingerprintProperty, fingerprint);
  return 'Histórico & Aprendizagem atualizado com sucesso.';
}

function factorLabel_(value) {
  const labels = {
    comeback_set1: 'Recuperação após perder o 1.º set',
    fadiga: 'Fadiga',
    forma_recente: 'Forma recente',
    h2h: 'Confronto direto',
    h2h_piso: 'Confronto direto no piso',
    historico_torneio: 'Histórico no torneio',
    indoor_outdoor: 'Indoor / outdoor',
    lesao: 'Lesão / condição física',
    matchup_maos: 'Matchup de lateralidade',
    mudanca_piso: 'Mudança de piso',
    nivel_adversario: 'Nível dos adversários',
    piso: 'Desempenho no piso',
    pressao_ronda: 'Pressão da ronda',
    qualidade_vitorias: 'Qualidade das vitórias',
    ranking: 'Ranking',
    ranking_evolucao: 'Evolução do ranking',
    recuperacao_sets: 'Recuperação entre sets',
    sazonal: 'Forma sazonal',
    servico_carreira: 'Serviço na carreira',
    servico_recente: 'Serviço recente',
    tiebreak: 'Tiebreaks',
    velocidade_piso: 'Velocidade do piso',
  };
  return labels[String(value || '')] || String(value || '').replace(/_/g, ' ');
}

function buildWeightDecisionPanelModel_(attribution, manualPaper) {
  const summary = Array.isArray((attribution || {}).summary) ? attribution.summary : [];
  const global = summary.filter(row => String(row.scope || '').toUpperCase() === 'GLOBAL');
  const byScope = {};
  summary.forEach(row => {
    byScope[String(row.scope || '').toUpperCase() + '|' + String(row.factor || '')] = row;
  });
  const strategy = (((manualPaper || {}).by_strategy || {}).GUERRA_SELECTION_V1 || {});
  const audit = strategy.audit_v1 || {};
  const quality = audit.quality || {};
  const linked = Number(quality.linked_entries || 0);
  const canonical = Number(quality.canonical_entries || 0);
  const legacy = Number(quality.legacy_entries || 0);
  const reconstructed = Number(quality.legacy_factor_reconstructed_entries || 0);
  const eligible = Number(quality.factor_audit_eligible_entries || 0);
  const unresolved = Number(quality.selected_side_unresolved || 0);
  const minimumTrend = 20;
  const minimumReview = 40;

  const rows = global.map(row => {
    const factor = String(row.factor || '');
    const atp = byScope['ATP|' + factor] || {};
    const wta = byScope['WTA|' + factor] || {};
    const matches = Number(row.active_matches || 0);
    const coverage = Number(row.coverage_pct || 0);
    const residual = typeof row.market_residual_pp === 'number' ? row.market_residual_pp : null;
    const atpResidual = typeof atp.market_residual_pp === 'number' ? atp.market_residual_pp : null;
    const wtaResidual = typeof wta.market_residual_pp === 'number' ? wta.market_residual_pp : null;
    const strongSample = matches >= 100 && coverage >= 20;
    const tourConflict = atpResidual !== null && wtaResidual !== null
      && Math.sign(atpResidual) !== Math.sign(wtaResidual)
      && Math.abs(atpResidual - wtaResidual) >= 4;
    let signal = 'Manter em observação';
    let reason = 'Sem diferença material face à expectativa do mercado.';
    if (!strongSample) {
      signal = 'Recolher mais dados';
      reason = 'Cobertura ou amostra estrutural ainda curta.';
    } else if (tourConflict) {
      signal = 'Separar ATP / WTA';
      reason = 'O efeito muda materialmente entre circuitos.';
    } else if (residual !== null && residual >= 3) {
      signal = 'Sinal positivo a validar';
      reason = 'Residual estrutural positivo; só rever peso após validação PAPER.';
    } else if (residual !== null && residual <= -2.5) {
      signal = 'Sinal negativo a validar';
      reason = 'Residual estrutural negativo; só rever peso após validação PAPER.';
    }
    return {
      factor: factor,
      label: factorLabel_(factor),
      matches: matches,
      coverage_pct: row.coverage_pct,
      hit_pct: row.hit_pct,
      market_expected_pct: row.market_expected_pct,
      residual_pp: residual,
      average_effective_weight: row.average_effective_weight,
      atp_residual_pp: atpResidual,
      wta_residual_pp: wtaResidual,
      signal: signal,
      reason: reason,
    };
  }).sort((left, right) => {
    const priority = {'Sinal negativo a validar': 0, 'Sinal positivo a validar': 1, 'Separar ATP / WTA': 2, 'Recolher mais dados': 3, 'Manter em observação': 4};
    const leftPriority = Object.prototype.hasOwnProperty.call(priority, left.signal) ? priority[left.signal] : 9;
    const rightPriority = Object.prototype.hasOwnProperty.call(priority, right.signal) ? priority[right.signal] : 9;
    return leftPriority - rightPriority
      || Math.abs(Number(right.residual_pp || 0)) - Math.abs(Number(left.residual_pp || 0));
  });

  const positive = rows.filter(row => row.signal === 'Sinal positivo a validar').slice(0, 3);
  const negative = rows.filter(row => row.signal === 'Sinal negativo a validar').slice(0, 3);
  const conflicts = rows.filter(row => row.signal === 'Separar ATP / WTA').slice(0, 3);
  const overallStatus = eligible < minimumTrend ? 'MANTER PESOS — AMOSTRA PAPER INSUFICIENTE'
    : eligible < minimumReview ? 'OBSERVAR — TENDÊNCIA AINDA NÃO CONFIRMADA'
      : 'REVISÃO MANUAL DE PESOS JÁ É PERMITIDA';
  const headline = eligible < minimumTrend
    ? 'Só ' + eligible + ' entrada(s) GUERRA permite(m) atribuir o resultado aos fatores. Faltam ' + (minimumTrend - eligible) + ' para a primeira leitura de tendência.'
    : eligible < minimumReview
      ? 'A amostra GUERRA já permite observar tendências, mas faltam ' + (minimumReview - eligible) + ' entradas para rever pesos.'
      : 'A amostra mínima para revisão foi atingida; começar por ±0,25, nunca exceder ±0,5 por ciclo e exigir validação humana.';
  const list = values => values.length ? values.map(item => item.label).join(', ') : 'nenhum com evidência suficiente';
  return {
    status: overallStatus,
    headline: headline,
    linked: linked,
    canonical: canonical,
    legacy: legacy,
    reconstructed: reconstructed,
    eligible: eligible,
    unresolved: unresolved,
    structural_snapshots: global.reduce((maximum, row) => Math.max(maximum, Number(row.seen_snapshots || 0)), 0),
    factor_count: global.length,
    positive_text: 'Sinais positivos estruturais: ' + list(positive) + '.',
    negative_text: 'Sinais negativos estruturais: ' + list(negative) + '.',
    conflict_text: 'Diferenças ATP/WTA a estudar: ' + list(conflicts) + '.',
    rule_text: 'Regra: <20 PAPER elegíveis = não mexer; 20–39 = tendência; ≥40 = revisão manual. Começar por ±0,25 e nunca exceder ±0,5 por ciclo.',
    rows: rows,
  };
}

function writeWeightDecisionPanel_(spreadsheet, attribution, manualPaper) {
  const model = buildWeightDecisionPanelModel_(attribution, manualPaper);
  const name = 'Painel — Pesos';
  const sheet = spreadsheet.getSheetByName(name) || spreadsheet.insertSheet(name);
  const existingFilter = sheet.getFilter();
  if (existingFilter) existingFilter.remove();
  const fullSheetRange = sheet.getRange(1, 1, sheet.getMaxRows(), sheet.getMaxColumns());
  fullSheetRange.breakApart();
  // clear() não remove necessariamente validações antigas. O painel anterior
  // tinha dropdowns na coluna de ação; sem esta limpeza, valores legítimos da
  // nova projeção podem falhar com DATA_VALIDATION_ERROR (por exemplo J40).
  fullSheetRange.clearDataValidations();
  // clear({contentsOnly:false}) não é equivalente a uma limpeza integral no
  // Apps Script e deixou células da versão anterior entre os novos blocos.
  sheet.clear();
  sheet.clearConditionalFormatRules();
  sheet.getCharts().forEach(chart => sheet.removeChart(chart));
  sheet.setHiddenGridlines(true);
  sheet.setFrozenRows(11);

  sheet.getRange('A1:L1').merge().setValue('FENZOBOT — DECISÃO SOBRE PESOS')
    .setBackground('#0B1726').setFontColor('#FFFFFF').setFontFamily('Arial')
    .setFontSize(18).setFontWeight('bold').setHorizontalAlignment('left');
  sheet.getRange('A2:L2').merge().setValue('O painel separa evidência estrutural do motor da validação PAPER de Guerra. Atualiza automaticamente; não altera o modelo.')
    .setBackground('#EAF2F8').setFontColor('#35546F').setFontFamily('Arial').setFontSize(10);

  const cards = [
    ['A4:C4', 'A5:C6', 'SNAPSHOTS ESTRUTURAIS', model.structural_snapshots],
    ['D4:F4', 'D5:F6', 'FATORES ANALISADOS', model.factor_count],
    ['G4:I4', 'G5:I6', 'GUERRA LIGADAS', model.linked],
    ['J4:L4', 'J5:L6', 'AUDITORIA DE FATORES', model.eligible],
  ];
  cards.forEach(card => {
    sheet.getRange(card[0]).merge().setValue(card[2]).setBackground('#17365D').setFontColor('#FFFFFF').setFontWeight('bold').setHorizontalAlignment('center');
    sheet.getRange(card[1]).merge().setValue(card[3]).setBackground('#F3F7FA').setFontColor('#17365D').setFontSize(19).setFontWeight('bold').setHorizontalAlignment('center').setVerticalAlignment('middle');
  });

  const safe = model.eligible < 20;
  sheet.getRange('A8:L8').merge().setValue(model.status)
    .setBackground(safe ? '#FFF3CD' : '#DFF3E7').setFontColor(safe ? '#7A4F01' : '#166534')
    .setFontSize(13).setFontWeight('bold');
  sheet.getRange('A9:L9').merge().setValue(model.headline).setBackground('#FFFDF5').setFontColor('#3C4652').setWrap(true);
  sheet.getRange('A10:L10').merge().setValue('Qualidade do linkage: ' + model.linked + ' ligadas · '
    + model.canonical + ' canónicas · ' + model.legacy + ' legacy sem snapshot ('
    + model.reconstructed + ' reconstruídas do relatório) · '
    + model.unresolved + ' sem lado selecionado resolvido.')
    .setBackground('#FFFDF5').setFontColor('#3C4652');

  sheet.getRange('A12:L12').merge().setValue('CONCLUSÕES AUTOMÁTICAS — O QUE FAZER AGORA')
    .setBackground('#0F766E').setFontColor('#FFFFFF').setFontWeight('bold');
  const conclusions = [model.positive_text, model.negative_text, model.conflict_text, model.rule_text];
  sheet.getRange(13, 1, conclusions.length, 12).setBackground('#F3F7FA');
  conclusions.forEach((value, index) => sheet.getRange(13 + index, 1, 1, 12).merge().setValue('• ' + value).setWrap(true));

  const headerRow = 19;
  const headers = ['Fator', 'Amostra', 'Cobertura', 'Acerto', 'Mercado', 'Residual', 'Peso médio', 'ATP residual', 'WTA residual', 'Leitura', 'Justificação'];
  sheet.getRange(headerRow - 1, 1, 1, 12).merge().setValue('DETALHE DOS FATORES — ORDENADO POR PRIORIDADE DE REVISÃO')
    .setBackground('#0F766E').setFontColor('#FFFFFF').setFontWeight('bold');
  sheet.getRange(headerRow, 1, 1, 11).setValues([headers]).setBackground('#17365D').setFontColor('#FFFFFF').setFontWeight('bold').setHorizontalAlignment('center').setWrap(true);
  const rows = model.rows.map(row => [
    row.label, row.matches, row.coverage_pct == null ? '' : row.coverage_pct / 100,
    row.hit_pct == null ? '' : row.hit_pct / 100,
    row.market_expected_pct == null ? '' : row.market_expected_pct / 100,
    row.residual_pp, row.average_effective_weight,
    row.atp_residual_pp, row.wta_residual_pp, row.signal, row.reason,
  ]);
  if (rows.length) {
    sheet.getRange(headerRow + 1, 1, rows.length, 11).setValues(rows).setVerticalAlignment('top').setWrap(true);
    sheet.getRange(headerRow + 1, 3, rows.length, 3).setNumberFormat('0.0%');
    sheet.getRange(headerRow + 1, 6, rows.length, 1).setNumberFormat('0.0 "p.p."');
    sheet.getRange(headerRow + 1, 8, rows.length, 2).setNumberFormat('0.0 "p.p."');
    sheet.getRange(headerRow + 1, 2, rows.length, 1).setNumberFormat('0');
    const rules = [
      SpreadsheetApp.newConditionalFormatRule().whenTextContains('positivo').setBackground('#DFF3E7').setFontColor('#166534').setRanges([sheet.getRange(headerRow + 1, 10, rows.length, 1)]).build(),
      SpreadsheetApp.newConditionalFormatRule().whenTextContains('negativo').setBackground('#FDECEC').setFontColor('#B42318').setRanges([sheet.getRange(headerRow + 1, 10, rows.length, 1)]).build(),
      SpreadsheetApp.newConditionalFormatRule().whenTextContains('Separar').setBackground('#FFF3CD').setFontColor('#7A4F01').setRanges([sheet.getRange(headerRow + 1, 10, rows.length, 1)]).build(),
    ];
    sheet.setConditionalFormatRules(rules);
  }
  [34, 12, 14, 14, 14, 14, 14, 16, 16, 26, 54, 4].forEach((width, index) => sheet.setColumnWidth(index + 1, width * 7));
  sheet.setRowHeight(1, 34);
  sheet.setRowHeights(4, 3, 25);
  sheet.setRowHeights(8, 3, 28);
  try {
    spreadsheet.setActiveSheet(sheet);
    spreadsheet.moveActiveSheet(2);
  } catch (error) {
    console.warn('Painel de pesos não foi movido: ' + String(error && error.message || error));
  }
}

function writeProspectiveSystemHistory_(spreadsheet, payload) {
  // Deliberately never calls the legacy full-workbook writer: T0 sheets are
  // immutable and only two explicitly named post-T0 sheets may be replaced.
  const summary = payload.summary || {};
  upsertSystemSheet_(spreadsheet, 'Pós-T0 - Resumo', [
    ['Fenzobot — contribuições pós-T0', ''],
    ['Universo separado; as folhas históricas publicadas em T0 não são recalculadas.', ''],
    ['', ''],
    ['Indicador', 'Valor'],
    ['Snapshots pós-T0', summary.raw_snapshots || 0],
    ['Partidas canónicas pós-T0', summary.canonical_snapshots || 0],
    ['Liquidadas pós-T0', summary.settled_canonical_snapshots || 0],
    ['Seleções liquidadas com índice Fenzobot', summary.settled_fenzobot_index_observations || 0],
    ['Versões HTML pós-T0', summary.raw_report_html_versions || 0],
  ], { titleRows: 2, headerRow: 4, widths: [42, 85], preserveCharts: false });
  const operational = payload.operational || {};
  upsertSystemSheet_(spreadsheet, 'Pós-T0 - Partidas', rowsWithHeaders_(
    ['ID canónico', 'Snapshot', 'Analisado UTC', 'Início UTC', 'Tour', 'Torneio', 'Jogador A', 'Jogador B', 'Odd A', 'Odd B', 'Vencedor', 'Score', 'Fenzobot favorece', 'Índice Fenzobot', 'Faixa do índice'],
    operational.event_rows || [],
    ['event_id', 'snapshot_key', 'analyzed_at_utc', 'commence_time_utc', 'tour', 'tournament', 'player_a', 'player_b', 'odd_a', 'odd_b', 'winner_side', 'result', 'fenzobot_side', 'fenzobot_index', 'fenzobot_index_band'],
  ), { headerRow: 1, widths: [42, 28, 22, 22, 10, 34, 25, 25, 10, 10, 10, 20, 25, 16, 16] });
}

function installSystemHistorySync() {
  ScriptApp.getProjectTriggers()
    .filter(trigger => trigger.getHandlerFunction() === SYSTEM_HISTORY_SYNC.triggerHandler)
    .forEach(trigger => ScriptApp.deleteTrigger(trigger));
  ScriptApp.newTrigger(SYSTEM_HISTORY_SYNC.triggerHandler)
    .timeBased()
    .everyHours(1)
    .create();
  return 'Atualização horária instalada. Só escreve quando o histórico mudar.';
}

function fetchSystemHistoryPayload_(repository, branch) {
  // O repositório e o ficheiro de histórico são públicos. Usar o URL RAW
  // remove a necessidade de guardar um token pessoal no Apps Script.
  return fetchPublicJson_(repository, branch, SYSTEM_HISTORY_SYNC.sourcePath);
}

function fetchPublicJson_(repository, branch, path) {
  const url = 'https://raw.githubusercontent.com/' + repository + '/' + encodeURIComponent(branch) + '/' + path;
  const response = UrlFetchApp.fetch(url, {
    method: 'get',
    muteHttpExceptions: true,
  });
  if (response.getResponseCode() !== 200) {
    throw new Error('Não foi possível obter JSON público (' + path + '): HTTP ' + response.getResponseCode() + ': ' + response.getContentText());
  }
  const payload = JSON.parse(response.getContentText());
  if (!payload || typeof payload !== 'object') throw new Error('Payload JSON inválido: ' + path);
  return payload;
}

function writeChallengerManualPaperSheet_(spreadsheet, manualPaper) {
  const strategy = ((manualPaper || {}).by_strategy || {}).CHALLENGER_125_EXPERIMENTAL_V1 || {};
  const summary = strategy.summary || {};
  const available = strategy.status === 'AVAILABLE';
  const valueOrND = (value) => available ? (value == null ? 'N/D' : value) : 'N/D';
  const statsRows = (collection) => Object.keys(collection || {}).sort().map(key => {
    const stat = collection[key] || {};
    return [key, stat.total_entries || 0, stat.settled || 0, stat.wins || 0, stat.losses || 0, stat.pushes || 0, stat.pending || 0, stat.units == null ? 'N/D' : stat.units, stat.roi_pct == null ? 'N/D' : stat.roi_pct, stat.average_odd == null ? 'N/D' : stat.average_odd];
  });
  const section = (title, rows) => [[title, '', '', '', '', '', '', '', '', ''], ['Grupo', 'Entradas', 'Liquidadas', 'Vitórias', 'Derrotas', 'Void', 'Pendentes', 'Unidades', 'ROI', 'Odd média']].concat(rows.length ? rows : [['Sem amostra', '', '', '', '', '', '', '', '', '']]);
  const rawValues = [
    ['Challenger 125 — PAPER manual 0,5u', '', '', '', '', '', '', '', '', ''],
    ['Universo separado do PAPER normal. Só entram linhas registadas com a estratégia CHALLENGER_125_EXPERIMENTAL_V1, stake de 0,5u, Snapshot Key e data de seleção.', '', '', '', '', '', '', '', '', ''],
    ['', '', '', '', '', '', '', '', '', ''],
    ['Indicador', 'Valor', '', '', '', '', '', '', '', ''],
    ['Estado', strategy.status || 'UNAVAILABLE', '', '', '', '', '', '', '', '', ''],
    ['Entradas válidas', valueOrND(summary.total_entries), '', '', '', '', '', '', '', '', ''],
    ['Liquidadas', valueOrND(summary.settled), '', '', '', '', '', '', '', '', ''],
    ['W–L', available ? (summary.wins || 0) + '–' + (summary.losses || 0) : 'N/D', '', '', '', '', '', '', '', '', ''],
    ['Void / pendentes', available ? (summary.pushes || 0) + ' / ' + (summary.pending || 0) : 'N/D', '', '', '', '', '', '', '', '', ''],
    ['Unidades / ROI', available ? (summary.units == null ? 'N/D' : summary.units) + ' / ' + (summary.roi_pct == null ? 'N/D' : summary.roi_pct + '%') : 'N/D', '', '', '', '', '', '', '', ''],
    ['Odd média', valueOrND(summary.average_odd), '', '', '', '', '', '', '', '', ''],
    ['Stake fixo da estratégia', strategy.fixed_stake_units == null ? '0,5u' : String(strategy.fixed_stake_units).replace('.', ',') + 'u', '', '', '', '', '', '', '', ''],
    ['', '', '', '', '', '', '', '', '', ''],
  ].concat(
    section('Por mercado', statsRows(strategy.by_market)), [['', '', '', '', '', '', '', '', '', '']],
    section('Por perfil', statsRows(strategy.by_side)), [['', '', '', '', '', '', '', '', '', '']],
    section('Por índice Fenzobot', statsRows(strategy.by_fenzobot_index_band)), [['', '', '', '', '', '', '', '', '', '']],
    section('Por cobertura', statsRows(strategy.by_coverage_band)), [['', '', '', '', '', '', '', '', '', '']],
    section('Por edge experimental', statsRows(strategy.by_edge_band)),
  );
  // A secção resumo teve historicamente rows com uma célula vazia a mais.
  // Normalizar aqui mantém o contrato retangular exigido por setValues() e
  // impede que uma aba Challenger bloqueie toda a sincronização do histórico.
  const values = rawValues.map(row => Array.from({length: 10}, (_, index) => (
    index < row.length ? row[index] : ''
  )));
  upsertSystemSheet_(spreadsheet, 'Challenger 125 · PAPER 0,5u', values, { titleRows: 2, headerRow: 4, widths: [38, 16, 14, 12, 12, 12, 14, 14, 14, 14] });
  const sheet = spreadsheet.getSheetByName('Challenger 125 · PAPER 0,5u');
  for (let row = 14; row <= values.length; row += 1) {
    if (String(values[row - 1][0] || '').indexOf('Por ') === 0) {
      sheet.getRange(row, 1, 1, 10).setBackground('#0F766E').setFontColor('#FFFFFF').setFontWeight('bold');
      sheet.getRange(row + 1, 1, 1, 10).setBackground('#17365D').setFontColor('#FFFFFF').setFontWeight('bold');
    }
  }
}

function writeGuerraAuditSheets_(spreadsheet, manualPaper) {
  const strategy = ((manualPaper || {}).by_strategy || {}).GUERRA_SELECTION_V1 || {};
  const audit = strategy.audit_v1 || {};
  const factors = normaliseGuerraAuditRows_(audit.factors);
  const segments = normaliseGuerraAuditRows_(audit.segments);
  const quality = audit.quality || {};
  const executedEdge = audit.executed_edge_v1 || {};
  const executedAll = executedEdge.all_linked || {};
  const executedExact = executedEdge.exact_timestamp || {};
  const referenceMovement = audit.reference_market_movement_v1 || {};
  const movementAll = referenceMovement.all_linked || {};
  const movementExact = referenceMovement.exact_timestamp || {};

  upsertSystemSheet_(spreadsheet, 'GUERRA — fatores', rowsWithHeaders_(
    ['Universo', 'Fator', 'Relação com seleção', 'Entradas', 'Liquidadas', 'Pendentes', 'Vitórias', 'Derrotas', '% acerto', 'Unidades', 'ROI', 'Odd média', 'Break-even', 'Margem vs break-even (p.p.)', 'Peso efetivo médio', 'Leitura da amostra'],
    factors,
    ['scope', 'factor', 'relation', 'total_entries', 'settled', 'pending', 'wins', 'losses', 'win_rate_pct', 'units', 'roi_pct', 'average_odd', 'break_even_pct', 'hit_vs_break_even_pp', 'average_effective_weight', 'sample_status'],
  ), {headerRow: 1, widths: [14, 24, 22, 12, 12, 12, 12, 12, 14, 14, 14, 14, 16, 24, 20, 26], percentageColumns: [9, 11, 13], marginColumn: 14});

  upsertSystemSheet_(spreadsheet, 'GUERRA — segmentos', rowsWithHeaders_(
    ['Dimensão', 'Grupo', 'Entradas', 'Liquidadas', 'Pendentes', 'Vitórias', 'Derrotas', 'Void', '% acerto', 'Unidades', 'ROI', 'Odd média', 'Break-even', 'Margem vs break-even (p.p.)', 'Leitura da amostra'],
    segments,
    ['dimension', 'group', 'total_entries', 'settled', 'pending', 'wins', 'losses', 'pushes', 'win_rate_pct', 'units', 'roi_pct', 'average_odd', 'break_even_pct', 'hit_vs_break_even_pp', 'sample_status'],
  ), {headerRow: 1, widths: [22, 30, 12, 12, 12, 12, 12, 10, 14, 14, 14, 14, 16, 24, 26], percentageColumns: [9, 11, 13], marginColumn: 14});

  const qualityRows = [
    ['Auditoria GUERRA_SELECTION', 'Valor'],
    ['Estado', audit.status || 'UNAVAILABLE'],
    ['Contrato de privacidade', audit.privacy_contract || 'N/D'],
    ['Entradas ligadas a relatório', quality.linked_entries || 0],
    ['Entradas com snapshot canónico', quality.canonical_entries || 0],
    ['Entradas ligadas apenas a relatório legacy', quality.legacy_entries || 0],
    ['Ligações ex ante com hora exata', quality.exact_timestamp_entries || 0],
    ['Ligações retrospetivas por data', quality.retrospective_entries || 0],
    ['Snapshots encontrados no índice de fatores', quality.factor_index_matches || 0],
    ['Entradas legacy reconstruídas do relatório público', quality.legacy_factor_reconstructed_entries || 0],
    ['Entradas elegíveis para auditoria de fatores', quality.factor_audit_eligible_entries || 0],
    ['Lado selecionado não resolvido', quality.selected_side_unresolved || 0],
    ['Snapshot ausente do índice de fatores', quality.factor_index_missing || 0],
    ['Possíveis legs exatas duplicadas', quality.duplicate_exact_legs || 0],
    ['Snapshots públicos no índice', audit.factor_index_records == null ? 'N/D' : audit.factor_index_records],
    ['', ''],
    ['Edge executado Moneyline — amostra calculável', executedAll.sample_size || 0],
    ['Edge executado Moneyline — média', executedAll.average_pct == null ? 'N/D' : executedAll.average_pct + '%'],
    ['Edge executado Moneyline — mediana', executedAll.median_pct == null ? 'N/D' : executedAll.median_pct + '%'],
    ['Edge executado Moneyline — % positivo', executedAll.positive_pct == null ? 'N/D' : executedAll.positive_pct + '%'],
    ['Edge executado ex ante — amostra', executedExact.sample_size || 0],
    ['Edge executado — regra', 'Probabilidade Fenzobot congelada × odd realmente executada. Betfair desconta 5% sobre lucro. Handicap fica N/D sem probabilidade da linha exata.'],
    ['', ''],
    ['Movimento de referência — amostra calculável', movementAll.sample_size || 0],
    ['Movimento de referência — média', movementAll.average_pct == null ? 'N/D' : movementAll.average_pct + ' p.p.'],
    ['Movimento de referência — % encurtou', movementAll.positive_pct == null ? 'N/D' : movementAll.positive_pct + '%'],
    ['Movimento de referência ex ante — amostra', movementExact.sample_size || 0],
    ['Movimento de referência — limite', 'Não é CLV da aposta. Compara o mesmo feed/bookmaker do ledger, que pode não ser 22Bet ou Betfair.'],
    ['Regra de amostra', '<20 informativo · 20–39 tendência · ≥40 candidato a revisão; alterações máximas de peso ±0,5 por ciclo.'],
    ['Limite', 'Auditoria descritiva. Não altera pesos, PAPER, pricing ou decisões automaticamente. Challenger mantém universo próprio.'],
  ];
  upsertSystemSheet_(spreadsheet, 'GUERRA — qualidade', qualityRows, {
    headerRow: 1, widths: [48, 105], preserveCharts: false,
  });
}

function normaliseGuerraAuditRows_(rows) {
  return (Array.isArray(rows) ? rows : []).map(source => {
    const row = Object.assign({}, source || {});
    const odd = Number(row.average_odd);
    if (Number.isFinite(odd) && odd > 1) {
      const breakEven = Math.round(1000 / odd) / 10;
      row.break_even_pct = breakEven;
      row.hit_vs_break_even_pp = typeof row.win_rate_pct === 'number'
        ? Math.round(10 * (row.win_rate_pct - breakEven)) / 10
        : null;
    } else {
      row.break_even_pct = null;
      row.hit_vs_break_even_pp = null;
    }
    return row;
  });
}

function writeSystemHistoryWorkbook_(spreadsheet, payload) {
  const summary = payload.summary || {};
  const operational = payload.operational || {};
  const pricedBands = (operational.fenzobot_band_summary || []).filter(row => Number(row.matches || 0) >= 5 && typeof row.break_even_pct === 'number');
  const aboveBreakEven = pricedBands.filter(row => Number(row.margin_vs_break_even_pp || 0) >= 0).length;
  upsertSystemSheet_(spreadsheet, 'Resumo', [
    ['Fenzobot — Histórico & Aprendizagem', ''],
    ['Fonte: snapshots canónicos e cache WTA local. ATP operacional usa snapshots Fenzobot; não existe cache ATP bruta local.', ''],
    ['', ''],
    ['Indicador', 'Valor'],
    ['Snapshots guardados (brutos)', summary.raw_snapshots || 0],
    ['Partidas canónicas', summary.canonical_snapshots || 0],
    ['Repetições excluídas das métricas', summary.duplicate_snapshots_excluded || 0],
    ['Partidas canónicas liquidadas', summary.settled_canonical_snapshots || 0],
    ['Seleções liquidadas com índice Fenzobot', summary.settled_fenzobot_index_observations || 0],
    ['Versões HTML guardadas', summary.raw_report_html_versions || 0],
    ['Jogos WTA históricos locais', summary.historical_wta_matches || 0],
    ['Faixas Fenzobot ≥ break-even teórico (n ≥ 5)', pricedBands.length ? aboveBreakEven + ' / ' + pricedBands.length : 'N/D'],
    ['', ''],
    ['Leitura do break-even', 'Usa 1 / odd média decimal de cada faixa. É um limiar teórico; não é ROI, lucro, stake nem execução 22Bet.'],
    ['Regra', 'Cada partida conta uma vez: primeiro snapshot pré-jogo válido. PAPER/REAL não são misturados neste painel.'],
  ], { titleRows: 2, headerRow: 4, widths: [44, 105], preserveCharts: true });

  upsertSystemSheet_(spreadsheet, 'Partidas canónicas', rowsWithHeaders_(
    ['ID canónico', 'Snapshot', 'Analisado UTC', 'Início UTC', 'Tour', 'Torneio', 'Jogador A', 'Jogador B', 'Odd A', 'Odd B', 'Vencedor', 'Score', 'Fenzobot favorece', 'Índice Fenzobot', 'Faixa do índice'],
    operational.event_rows || [],
    ['event_id', 'snapshot_key', 'analyzed_at_utc', 'commence_time_utc', 'tour', 'tournament', 'player_a', 'player_b', 'odd_a', 'odd_b', 'winner_side', 'result', 'fenzobot_side', 'fenzobot_index', 'fenzobot_index_band'],
  ), { headerRow: 1, widths: [42, 28, 22, 22, 10, 34, 25, 25, 10, 10, 10, 20, 25, 16, 16] });
  upsertSystemSheet_(spreadsheet, 'Registo HTML bruto', rowsWithHeaders_(
    ['Data indicada', 'Ficheiro HTML'], payload.report_registry || [], ['report_date', 'report_file'],
  ), { headerRow: 1, widths: [18, 100] });
  upsertSystemSheet_(spreadsheet, 'Operacional - jogador odd', rowsWithHeaders_(
    ['Jogador', 'Faixa de odd', 'Papel', 'Jogos', 'Vitórias', 'Derrotas', '% vitória'], operational.player_odds || [],
    ['player', 'odds_band', 'role', 'matches', 'wins', 'losses', 'win_pct'],
  ), { headerRow: 1, widths: [28, 16, 14, 12, 12, 12, 14], percentageColumn: 7 });
  upsertSystemSheet_(spreadsheet, 'Operacional - Fenzobot odd', rowsWithHeaders_(
    ['Seleção Fenzobot', 'Faixa de odd', 'Papel', 'Jogos', 'Vitórias', 'Derrotas', '% acerto'], operational.fenzobot_odds || [],
    ['player', 'odds_band', 'role', 'matches', 'wins', 'losses', 'win_pct'],
  ), { headerRow: 1, widths: [28, 16, 14, 12, 12, 12, 14], percentageColumn: 7 });
  upsertSystemSheet_(spreadsheet, 'Operacional - índice Fenzobot', rowsWithHeaders_(
    ['Faixa do índice', 'Jogos', 'Vitórias', 'Derrotas', '% acerto'], operational.fenzobot_index_band_summary || [],
    ['index_band', 'matches', 'wins', 'losses', 'win_pct'],
  ), { headerRow: 1, widths: [20, 14, 14, 14, 16], percentageColumn: 5 });
  upsertSystemSheet_(spreadsheet, 'Operacional — odd & break-even', rowsWithHeaders_(
    ['Faixa de odd', 'Jogos', 'Vitórias', 'Derrotas', '% acerto', 'Odd média', 'Break-even teórico', 'Margem vs break-even (p.p.)'], operational.fenzobot_band_summary || [],
    ['odds_band', 'matches', 'wins', 'losses', 'win_pct', 'average_odd', 'break_even_pct', 'margin_vs_break_even_pp'],
  ), { headerRow: 1, widths: [18, 12, 12, 12, 15, 14, 18, 24], percentageColumns: [5, 7], marginColumn: 8 });
  upsertSystemSheet_(spreadsheet, 'Operacional — índice × odd', rowsWithHeaders_(
    ['Faixa do índice', 'Faixa de odd', 'Jogos', 'Vitórias', 'Derrotas', '% acerto', 'Odd média', 'Break-even teórico', 'Margem vs break-even (p.p.)'], operational.fenzobot_index_odds_summary || [],
    ['index_band', 'odds_band', 'matches', 'wins', 'losses', 'win_pct', 'average_odd', 'break_even_pct', 'margin_vs_break_even_pp'],
  ), { headerRow: 1, widths: [18, 18, 12, 12, 12, 15, 14, 18, 24], percentageColumns: [6, 8], marginColumn: 9 });
  const byTour = operational.by_tour || {};
  writeTourOperationalSheets_(spreadsheet, 'ATP', byTour.ATP || {});
  writeTourOperationalSheets_(spreadsheet, 'WTA', byTour.WTA || {});

  const wta = payload.historical_wta || {};
  upsertSystemSheet_(spreadsheet, 'WTA histórico - jogador odd', rowsWithHeaders_(
    ['Jogadora', 'Faixa de odd', 'Papel', 'Jogos', 'Vitórias', 'Derrotas', '% vitória'], wta.player_odds || [],
    ['player', 'odds_band', 'role', 'matches', 'wins', 'losses', 'win_pct'],
  ), { headerRow: 1, widths: [28, 16, 14, 12, 12, 12, 14], percentageColumn: 7 });
  upsertSystemSheet_(spreadsheet, 'WTA histórico — handicap', rowsWithHeaders_(
    ['Jogadora', 'Papel', 'Linha referência BO3 (não lucro)', 'Jogos', 'Cobre', 'Devolve', 'Falha', '% cobre'], wta.handicap_reference || [],
    ['player', 'role', 'reference_line', 'matches', 'covers', 'pushes', 'fails', 'cover_pct'],
  ), { headerRow: 1, widths: [28, 14, 18, 12, 12, 12, 12, 14], percentageColumn: 8 });
  upsertSystemSheet_(spreadsheet, 'WTA histórico — recuperação', rowsWithHeaders_(
    ['Jogadora', 'Perdeu 1.º set', 'Recuperou e venceu', '% recuperação'], wta.set1_recovery || [],
    ['player', 'lost_first', 'recovered', 'recovery_pct'],
  ), { headerRow: 1, widths: [28, 18, 22, 16], percentageColumn: 4 });
  upsertSystemSheet_(spreadsheet, 'WTA histórico — set decisivo', rowsWithHeaders_(
    ['Jogadora', 'Sets decisivos', 'Venceu', '% vitória'], wta.deciding_set || [],
    ['player', 'matches', 'wins', 'win_pct'],
  ), { headerRow: 1, widths: [28, 18, 14, 16], percentageColumn: 4 });
  upsertSystemSheet_(spreadsheet, 'WTA histórico — tiebreak', rowsWithHeaders_(
    ['Jogadora', 'Tiebreaks', 'Venceu', '% vitória'], wta.tiebreak || [],
    ['player', 'matches', 'wins', 'win_pct'],
  ), { headerRow: 1, widths: [28, 16, 14, 16], percentageColumn: 4 });
  writeRankingsSheet_(spreadsheet, payload.rankings || {});
  upsertSystemSheet_(spreadsheet, 'Metodologia e limites', [
    ['Tema', 'Regra'],
    ['Deduplicação', 'Uma partida entra uma vez: primeiro snapshot pré-jogo válido. HTMLs repetidos não são observações analíticas.'],
    ['Operacional', 'Snapshots canónicos já liquidados; os agrupamentos por odd e por faixa de índice são observacionais, não backtest nem carteira PAPER. O índice não é probabilidade.'],
    ['ATP operacional', 'Não existe cache ATP bruta local neste projeto. As abas ATP operacional usam apenas snapshots canónicos já registados pelo Fenzobot; não apresentam handicap, recuperação ou tiebreak ATP como se fossem histórico completo.'],
    ['Histórico WTA', 'Resultados e odds da cache local tennis-data.co.uk. Não se afirma cobertura ATP onde não existe base bruta local.'],
    ['Handicaps', 'O número -4.5, +2 etc. é a linha interna BO3 de referência, não lucro, retorno ou linha real de bookmaker. Os rankings são ordenados por % cobre e amostra.'],
    ['Break-even', 'Taxa teórica 1 / odd decimal média dos snapshots canónicos da faixa. Não incorpora stake, vigor, limites ou execução numa casa de apostas.'],
    ['Recuperação', 'Vitórias após perder o 1.º set; ainda não existe estatística ponto-a-ponto de breaks.'],
    ['PAPER / REAL', 'Permanecem separados e devem ser avaliados nos respetivos registos financeiros.'],
  ], { headerRow: 1, widths: [28, 110] });
  writeFenzobotCharts_(spreadsheet, operational.fenzobot_band_summary || [], operational.fenzobot_index_band_summary || []);
}

function writeTourOperationalSheets_(spreadsheet, tour, series) {
  const label = tour + ' operacional';
  upsertSystemSheet_(spreadsheet, label + ' — Fenzobot odd', rowsWithHeaders_(
    ['Seleção Fenzobot', 'Faixa de odd', 'Papel', 'Jogos', 'Vitórias', 'Derrotas', '% acerto'], series.fenzobot_odds || [],
    ['player', 'odds_band', 'role', 'matches', 'wins', 'losses', 'win_pct'],
  ), { headerRow: 1, widths: [28, 16, 14, 12, 12, 12, 14], percentageColumn: 7 });
  upsertSystemSheet_(spreadsheet, label + ' — índice × odd', rowsWithHeaders_(
    ['Faixa do índice', 'Faixa de odd', 'Jogos', 'Vitórias', 'Derrotas', '% acerto', 'Odd média', 'Break-even teórico', 'Margem vs break-even (p.p.)'], series.fenzobot_index_odds_summary || [],
    ['index_band', 'odds_band', 'matches', 'wins', 'losses', 'win_pct', 'average_odd', 'break_even_pct', 'margin_vs_break_even_pp'],
  ), { headerRow: 1, widths: [18, 18, 12, 12, 12, 15, 14, 18, 24], percentageColumns: [6, 8], marginColumn: 9 });
}

function writeFactorAttributionSheets_(spreadsheet, attribution) {
  const summary = attribution.summary || [];
  const byWeight = attribution.by_weight_band || [];
  upsertSystemSheet_(spreadsheet, 'Atribuição — fatores', rowsWithHeaders_(
    ['Universo', 'Fator', 'Snapshots com estado', 'Disponível', 'Ativo', '% ativo', 'Acertos', 'Erros', '% acerto', '% acerto ponderado', 'Peso efetivo médio', 'Odd média do lado', '% esperado mercado', 'Residual vs mercado (p.p.)'],
    summary,
    ['scope', 'factor', 'seen_snapshots', 'available_snapshots', 'active_matches', 'coverage_pct', 'wins', 'losses', 'hit_pct', 'weighted_hit_pct', 'average_effective_weight', 'average_odd', 'market_expected_pct', 'market_residual_pp'],
  ), { headerRow: 1, widths: [14, 24, 20, 14, 12, 12, 12, 12, 14, 22, 22, 18, 20, 24], percentageColumns: [6, 9, 10, 13], marginColumn: 14 });
  upsertSystemSheet_(spreadsheet, 'Atribuição — força do peso', rowsWithHeaders_(
    ['Universo', 'Fator', 'Faixa de peso', 'Jogos', 'Acertos', 'Erros', '% acerto', 'Peso efetivo médio', 'Odd média do lado', '% esperado mercado', 'Residual vs mercado (p.p.)'],
    byWeight,
    ['scope', 'factor', 'weight_band', 'matches', 'wins', 'losses', 'hit_pct', 'average_effective_weight', 'average_odd', 'market_expected_pct', 'market_residual_pp'],
  ), { headerRow: 1, widths: [14, 24, 18, 12, 12, 12, 14, 22, 18, 20, 24], percentageColumns: [7, 10], marginColumn: 11 });
}

function writeFactorCoverageSheets_(spreadsheet, coverage) {
  const summary = coverage.summary || [];
  const reasons = coverage.reasons || [];
  upsertSystemSheet_(spreadsheet, 'Cobertura — fatores', rowsWithHeaders_(
    ['Universo', 'Fator', 'Snapshots com estado', 'Disponível', 'Indisponível', 'Disponível sem impacto', 'Aplicado', '% disponível', '% aplicado'],
    summary,
    ['scope', 'factor', 'seen_snapshots', 'available_snapshots', 'unavailable_snapshots', 'available_inactive_snapshots', 'active_snapshots', 'availability_pct', 'active_pct'],
  ), {
    headerRow: 1,
    widths: [16, 26, 22, 14, 16, 24, 14, 16, 16],
    percentageColumns: [8, 9],
  });
  upsertSystemSheet_(spreadsheet, 'Cobertura — motivos', rowsWithHeaders_(
    ['Universo', 'Fator', 'Estado', 'Motivo', 'Snapshots', '% dos snapshots do fator'],
    reasons,
    ['scope', 'factor', 'state', 'reason', 'snapshots', 'pct_of_factor_snapshots'],
  ), {
    headerRow: 1,
    widths: [16, 26, 26, 68, 14, 24],
    percentageColumn: 6,
  });
}

function writeRankingsSheet_(spreadsheet, rankings) {
  const sheet = spreadsheet.getSheetByName('Rankings') || spreadsheet.insertSheet('Rankings');
  const existingFilter = sheet.getFilter();
  if (existingFilter) existingFilter.remove();
  // Uma união antiga pode estender-se além de getDataRange(). Se a limparmos
  // apenas parcialmente, clear() falha no Apps Script. Abrangemos a folha toda.
  sheet.getRange(1, 1, sheet.getMaxRows(), sheet.getMaxColumns()).breakApart();
  sheet.clear({ contentsOnly: false });
  sheet.clearConditionalFormatRules();
  sheet.getCharts().forEach(chart => sheet.removeChart(chart));
  sheet.getRange(1, 1).setValue('Rankings de aprendizagem').setFontSize(16).setFontWeight('bold').setFontColor('#17365D');
  sheet.getRange(2, 1).setValue('Top 10 e Bottom 10 por métrica. Em handicap, a linha é referência interna BO3 e a métrica é % cobre — não lucro. WTA inclui apenas jogadoras ativas no cache dos últimos 12 meses.').setFontSize(10).setFontStyle('italic').setFontColor('#5B6573');
  let row = 5;
  Object.keys(rankings).forEach(category => {
    const group = rankings[category] || {};
    sheet.getRange(row, 1, 1, 7).merge().setValue(category + ' · amostra mínima ' + (group.minimum_sample || '—')).setBackground('#0F766E').setFontColor('#FFFFFF').setFontWeight('bold');
    row += 1;
    const metricLabel = group.metric_label || 'Métrica';
    sheet.getRange(row, 1, 1, 7).setValues([['Top 10', 'Amostra', metricLabel, '', group.bottom_title || 'Bottom 10', 'Amostra', metricLabel]]).setBackground('#17365D').setFontColor('#FFFFFF').setFontWeight('bold').setHorizontalAlignment('center');
    const strongest = Array.isArray(group.strongest) ? group.strongest : [];
    const weakest = Array.isArray(group.weakest) ? group.weakest : [];
    const count = Math.max(strongest.length, weakest.length, 1);
    const rows = [];
    for (let index = 0; index < count; index += 1) {
      const top = strongest[index] || {};
      const bottom = weakest[index] || {};
      rows.push([
        top.label || (index === 0 ? (group.empty_strongest_message || 'Sem amostras suficientes') : ''), top.sample || '', typeof top.metric_pct === 'number' ? top.metric_pct / 100 : '', '',
        bottom.label || (index === 0 ? (group.empty_weakest_message || 'Sem amostras suficientes') : ''), bottom.sample || '', typeof bottom.metric_pct === 'number' ? bottom.metric_pct / 100 : '',
      ]);
    }
    sheet.getRange(row + 1, 1, count, 7).setValues(rows);
    sheet.getRange(row + 1, 3, count, 1).setNumberFormat('0.0%');
    sheet.getRange(row + 1, 7, count, 1).setNumberFormat('0.0%');
    sheet.getRange(row + 1, 1, count, 1).setBackground('#E8F5E9');
    sheet.getRange(row + 1, 5, count, 1).setBackground('#FDECEC');
    row += count + 3;
  });
  [40, 12, 14, 4, 40, 12, 14].forEach((width, index) => sheet.setColumnWidth(index + 1, width * 7));
  sheet.setFrozenRows(5);
  sheet.setHiddenGridlines(true);
  sheet.getRange(1, 1, Math.max(row - 1, 5), 7).setVerticalAlignment('top').setWrap(true);
}

function writeFenzobotCharts_(spreadsheet, rows, indexRows) {
  const summary = spreadsheet.getSheetByName('Resumo');
  const data = spreadsheet.getSheetByName('Dados gráficos') || spreadsheet.insertSheet('Dados gráficos');
  const eligible = rows.filter(row => Number(row.matches || 0) >= 5 && typeof row.win_pct === 'number' && typeof row.break_even_pct === 'number');
  const existingFilter = data.getFilter();
  if (existingFilter) existingFilter.remove();
  data.getRange(1, 1, data.getMaxRows(), data.getMaxColumns()).breakApart();
  data.clear({ contentsOnly: false });
  const eligibleIndex = indexRows.filter(row => Number(row.matches || 0) >= 5 && typeof row.win_pct === 'number');
  const height = Math.max(eligible.length, eligibleIndex.length, 1) + 1;
  data.getRange(1, 1, height, 8).setValues([
    ['Faixa de odd', 'Acerto Fenzobot', 'Break-even teórico', 'Decisões liquidadas', '', 'Faixa do índice', 'Acerto Fenzobot', 'Decisões liquidadas'],
  ].concat(Array.from({ length: height - 1 }, (_, index) => {
    const odds = eligible[index] || {};
    const score = eligibleIndex[index] || {};
    return [odds.odds_band || '', typeof odds.win_pct === 'number' ? odds.win_pct / 100 : '', typeof odds.break_even_pct === 'number' ? odds.break_even_pct / 100 : '', odds.matches || '', '', score.index_band || '', typeof score.win_pct === 'number' ? score.win_pct / 100 : '', score.matches || ''];
  })));
  data.getRange(2, 2, Math.max(eligible.length, 1), 1).setNumberFormat('0.0%');
  data.getRange(2, 3, Math.max(eligible.length, 1), 1).setNumberFormat('0.0%');
  data.getRange(2, 7, Math.max(eligibleIndex.length, 1), 1).setNumberFormat('0.0%');
  data.hideSheet();
  summary.getCharts().forEach(chart => summary.removeChart(chart));
  if (eligible.length) {
    const chart = summary.newChart()
      .asColumnChart()
      .addRange(data.getRange(1, 1, eligible.length + 1, 3))
      .setNumHeaders(1)
      .setPosition(4, 4, 0, 0)
      .setOption('title', 'Acerto Fenzobot vs break-even por faixa de odd (n ≥ 5)')
      .setOption('legend', { position: 'bottom' })
      .setOption('vAxis', { format: 'percent', viewWindow: { min: 0, max: 1 } })
      .build();
    summary.insertChart(chart);
  } else {
    summary.getRange('D5').setValue('Gráfico pendente: ainda não há pelo menos 5 decisões liquidadas na mesma faixa de odd.').setFontStyle('italic').setFontColor('#5B6573');
  }
  if (eligibleIndex.length) {
    const chart = summary.newChart()
      .asColumnChart()
      .addRange(data.getRange(1, 6, eligibleIndex.length + 1, 2))
      .setNumHeaders(1)
      .setPosition(21, 4, 0, 0)
      .setOption('title', 'Acerto Fenzobot por faixa de índice (n ≥ 5)')
      .setOption('legend', { position: 'none' })
      .setOption('vAxis', { format: 'percent', viewWindow: { min: 0, max: 1 } })
      .build();
    summary.insertChart(chart);
  } else {
    summary.getRange('D21').setValue('Gráfico pendente: ainda não há pelo menos 5 decisões liquidadas na mesma faixa de índice.').setFontStyle('italic').setFontColor('#5B6573');
  }
}

function rowsWithHeaders_(headers, objects, fields) {
  return [headers].concat(objects.map(item => fields.map(field => item && item[field] != null ? item[field] : '')));
}

function createSystemFilterBestEffort_(sheet, range) {
  try {
    // Revalidar imediatamente antes de criar: uma execução anterior ou uma
    // alteração manual pode ter deixado um filtro entre o clear() e este ponto.
    const existingFilter = sheet.getFilter();
    if (existingFilter) existingFilter.remove();
    range.createFilter();
    return true;
  } catch (error) {
    // O filtro é apenas uma ajuda visual. Nunca pode invalidar os dados nem
    // bloquear a atualização das restantes abas.
    console.warn('Filtro não recriado em ' + sheet.getName() + ': ' + String(error && error.message || error));
    return false;
  }
}

function upsertSystemSheet_(spreadsheet, name, values, options) {
  const sheet = spreadsheet.getSheetByName(name) || spreadsheet.insertSheet(name);
  const existingFilter = sheet.getFilter();
  if (existingFilter) existingFilter.remove();
  sheet.getRange(1, 1, sheet.getMaxRows(), sheet.getMaxColumns()).breakApart();
  sheet.clear({ contentsOnly: false });
  sheet.clearConditionalFormatRules();
  if (!options.preserveCharts) sheet.getCharts().forEach(chart => sheet.removeChart(chart));
  if (!values.length || !values[0].length) return;
  sheet.getRange(1, 1, values.length, values[0].length).setValues(values);
  sheet.setFrozenRows(options.headerRow || 1);
  sheet.setHiddenGridlines(true);
  (options.widths || []).forEach((width, index) => sheet.setColumnWidth(index + 1, width * 7));

  const headerRow = options.headerRow || 1;
  const header = sheet.getRange(headerRow, 1, 1, values[0].length);
  header.setBackground('#17365D').setFontColor('#FFFFFF').setFontWeight('bold').setHorizontalAlignment('center').setWrap(true);
  if (options.titleRows) {
    sheet.getRange(1, 1).setFontSize(16).setFontWeight('bold').setFontColor('#17365D');
    sheet.getRange(2, 1).setFontSize(10).setFontStyle('italic').setFontColor('#5B6573');
  }
  if (values.length > headerRow) {
    sheet.getRange(headerRow + 1, 1, values.length - headerRow, values[0].length).setVerticalAlignment('top').setWrap(true);
  }
  const percentageColumns = options.percentageColumns || (options.percentageColumn ? [options.percentageColumn] : []);
  if (values.length > headerRow) {
    percentageColumns.forEach(column => {
      const range = sheet.getRange(headerRow + 1, column, values.length - headerRow, 1);
      const raw = range.getValues();
      range.setValues(raw.map(row => [typeof row[0] === 'number' ? row[0] / 100 : row[0]])).setNumberFormat('0.0%');
    });
    if (options.marginColumn) {
      const range = sheet.getRange(headerRow + 1, options.marginColumn, values.length - headerRow, 1);
      const raw = range.getValues();
      range.setNumberFormat('0.0 "p.p."');
      raw.forEach((row, index) => {
        const cell = range.getCell(index + 1, 1);
        if (typeof row[0] !== 'number') return;
        cell.setBackground(row[0] >= 0 ? '#E8F5E9' : '#FDECEC');
        cell.setFontColor(row[0] >= 0 ? '#166534' : '#B42318');
        cell.setFontWeight('bold');
      });
    }
  }
  createSystemFilterBestEffort_(
    sheet,
    sheet.getRange(headerRow, 1, values.length - headerRow + 1, values[0].length),
  );
}
