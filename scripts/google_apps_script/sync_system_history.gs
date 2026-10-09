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
  const fingerprint = historyFingerprint + ':' + manualFingerprint;
  if (!historyFingerprint) throw new Error('O JSON canónico não tem input_fingerprint_sha256.');
  if (properties.getProperty(SYSTEM_HISTORY_SYNC.fingerprintProperty) === fingerprint) {
    return 'Histórico sem alterações; Sheet preservada.';
  }

  const spreadsheet = SpreadsheetApp.openById(spreadsheetId);
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
  writeChallengerManualPaperSheet_(spreadsheet, manualPaper || {});
  properties.setProperty(SYSTEM_HISTORY_SYNC.fingerprintProperty, fingerprint);
  return 'Histórico & Aprendizagem atualizado com sucesso.';
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
  const values = [
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
  upsertSystemSheet_(spreadsheet, 'Challenger 125 · PAPER 0,5u', values, { titleRows: 2, headerRow: 4, widths: [38, 16, 14, 12, 12, 12, 14, 14, 14, 14] });
  const sheet = spreadsheet.getSheetByName('Challenger 125 · PAPER 0,5u');
  for (let row = 14; row <= values.length; row += 1) {
    if (String(values[row - 1][0] || '').indexOf('Por ') === 0) {
      sheet.getRange(row, 1, 1, 10).setBackground('#0F766E').setFontColor('#FFFFFF').setFontWeight('bold');
      sheet.getRange(row + 1, 1, 1, 10).setBackground('#17365D').setFontColor('#FFFFFF').setFontWeight('bold');
    }
  }
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
  sheet.getRange(headerRow, 1, values.length - headerRow + 1, values[0].length).createFilter();
}
