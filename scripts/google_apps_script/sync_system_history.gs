/**
 * CHANGE-2026-09-28-061
 * Sincroniza a Sheet colaborativa "Fenzobot — Histórico & Aprendizagem" a
 * partir do JSON canónico publicado no repositório.
 *
 * Segurança / método:
 * - O GitHub continua a ser a fonte de verdade; esta Sheet é uma vista.
 * - O payload já exclui relatórios HTML repetidos das métricas.
 * - Se o fingerprint não mudou, não reescreve células nem cria versões.
 * - Não usa Claude, RapidAPI nem qualquer API de odds.
 *
 * Propriedades de script necessárias (as mesmas do sync PAPER):
 * - GITHUB_TOKEN          Contents: Read no repositório Tennis
 * - GITHUB_REPOSITORY     sharp-signals/Tennis (opcional)
 * - GITHUB_BRANCH         main (opcional)
 * - SYSTEM_HISTORY_SHEET_ID (opcional; já tem uma predefinição)
 */

const SYSTEM_HISTORY_SYNC = {
  defaultRepository: 'sharp-signals/Tennis',
  defaultBranch: 'main',
  defaultSpreadsheetId: '1KojvHlLEJ-d4UCaN-Jb0Eu3fEIATbQmoP6_FqGYmWdw',
  sourcePath: 'data/dashboard/system_history_analytics.json',
  fingerprintProperty: 'SYSTEM_HISTORY_LAST_FINGERPRINT',
  triggerHandler: 'syncSystemHistoryToSheet',
};

function syncSystemHistoryToSheet() {
  const properties = PropertiesService.getScriptProperties();
  const token = properties.getProperty('GITHUB_TOKEN');
  if (!token) throw new Error('Falta GITHUB_TOKEN nas Propriedades do script.');

  const repository = properties.getProperty('GITHUB_REPOSITORY') || SYSTEM_HISTORY_SYNC.defaultRepository;
  const branch = properties.getProperty('GITHUB_BRANCH') || SYSTEM_HISTORY_SYNC.defaultBranch;
  const spreadsheetId = properties.getProperty('SYSTEM_HISTORY_SHEET_ID') || SYSTEM_HISTORY_SYNC.defaultSpreadsheetId;
  const payload = fetchSystemHistoryPayload_(token, repository, branch);
  const fingerprint = String(payload.input_fingerprint_sha256 || '');
  if (!fingerprint) throw new Error('O JSON canónico não tem input_fingerprint_sha256.');
  if (properties.getProperty(SYSTEM_HISTORY_SYNC.fingerprintProperty) === fingerprint) {
    return 'Histórico sem alterações; Sheet preservada.';
  }

  const spreadsheet = SpreadsheetApp.openById(spreadsheetId);
  writeSystemHistoryWorkbook_(spreadsheet, payload);
  properties.setProperty(SYSTEM_HISTORY_SYNC.fingerprintProperty, fingerprint);
  return 'Histórico & Aprendizagem atualizado com sucesso.';
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

function fetchSystemHistoryPayload_(token, repository, branch) {
  const url = 'https://api.github.com/repos/' + repository + '/contents/' + SYSTEM_HISTORY_SYNC.sourcePath + '?ref=' + encodeURIComponent(branch);
  const response = UrlFetchApp.fetch(url, {
    method: 'get',
    headers: {
      Authorization: 'Bearer ' + token,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
    },
    muteHttpExceptions: true,
  });
  if (response.getResponseCode() !== 200) {
    throw new Error('Não foi possível obter o histórico canónico: HTTP ' + response.getResponseCode() + ': ' + response.getContentText());
  }
  const document = JSON.parse(response.getContentText());
  const text = Utilities.newBlob(Utilities.base64Decode(String(document.content || '').replace(/\s/g, ''))).getDataAsString();
  const payload = JSON.parse(text);
  if (!payload || typeof payload !== 'object') throw new Error('Payload histórico inválido.');
  return payload;
}

function writeSystemHistoryWorkbook_(spreadsheet, payload) {
  const summary = payload.summary || {};
  upsertSystemSheet_(spreadsheet, 'Resumo', [
    ['Fenzobot — Histórico & Aprendizagem', ''],
    ['Fonte: snapshots canónicos e cache WTA local. Relatórios HTML repetidos não entram nas métricas.', ''],
    ['', ''],
    ['Indicador', 'Valor'],
    ['Snapshots guardados (brutos)', summary.raw_snapshots || 0],
    ['Partidas canónicas', summary.canonical_snapshots || 0],
    ['Repetições excluídas das métricas', summary.duplicate_snapshots_excluded || 0],
    ['Partidas canónicas liquidadas', summary.settled_canonical_snapshots || 0],
    ['Versões HTML guardadas', summary.raw_report_html_versions || 0],
    ['Jogos WTA históricos locais', summary.historical_wta_matches || 0],
    ['', ''],
    ['Regra', 'Cada partida conta uma vez: primeiro snapshot pré-jogo válido. PAPER/REAL não são misturados neste painel.'],
  ], { titleRows: 2, headerRow: 4, widths: [40, 85] });

  const operational = payload.operational || {};
  upsertSystemSheet_(spreadsheet, 'Partidas canónicas', rowsWithHeaders_(
    ['ID canónico', 'Snapshot', 'Analisado UTC', 'Início UTC', 'Tour', 'Torneio', 'Jogador A', 'Jogador B', 'Odd A', 'Odd B', 'Vencedor', 'Score', 'Fenzobot favorece'],
    operational.event_rows || [],
    ['event_id', 'snapshot_key', 'analyzed_at_utc', 'commence_time_utc', 'tour', 'tournament', 'player_a', 'player_b', 'odd_a', 'odd_b', 'winner_side', 'result', 'fenzobot_side'],
  ), { headerRow: 1, widths: [42, 28, 22, 22, 10, 34, 25, 25, 10, 10, 10, 20, 25] });
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

  const wta = payload.historical_wta || {};
  upsertSystemSheet_(spreadsheet, 'WTA histórico - jogador odd', rowsWithHeaders_(
    ['Jogadora', 'Faixa de odd', 'Papel', 'Jogos', 'Vitórias', 'Derrotas', '% vitória'], wta.player_odds || [],
    ['player', 'odds_band', 'role', 'matches', 'wins', 'losses', 'win_pct'],
  ), { headerRow: 1, widths: [28, 16, 14, 12, 12, 12, 14], percentageColumn: 7 });
  upsertSystemSheet_(spreadsheet, 'WTA histórico — handicap', rowsWithHeaders_(
    ['Jogadora', 'Papel', 'Linha referência', 'Jogos', 'Cobre', 'Devolve', 'Falha', '% cobre'], wta.handicap_reference || [],
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
  upsertSystemSheet_(spreadsheet, 'Metodologia e limites', [
    ['Tema', 'Regra'],
    ['Deduplicação', 'Uma partida entra uma vez: primeiro snapshot pré-jogo válido. HTMLs repetidos não são observações analíticas.'],
    ['Operacional', 'Snapshots canónicos já liquidados; não é backtest nem carteira PAPER.'],
    ['Histórico WTA', 'Resultados e odds da cache local tennis-data.co.uk. Não se afirma cobertura ATP onde não existe base bruta local.'],
    ['Handicaps', 'Cobertura contra linha interna BO3 de referência, inferida da faixa de Moneyline; não é linha real de bookmaker.'],
    ['Recuperação', 'Vitórias após perder o 1.º set; ainda não existe estatística ponto-a-ponto de breaks.'],
    ['PAPER / REAL', 'Permanecem separados e devem ser avaliados nos respetivos registos financeiros.'],
  ], { headerRow: 1, widths: [28, 110] });
}

function rowsWithHeaders_(headers, objects, fields) {
  return [headers].concat(objects.map(item => fields.map(field => item && item[field] != null ? item[field] : '')));
}

function upsertSystemSheet_(spreadsheet, name, values, options) {
  const sheet = spreadsheet.getSheetByName(name) || spreadsheet.insertSheet(name);
  const existingFilter = sheet.getFilter();
  if (existingFilter) existingFilter.remove();
  sheet.getDataRange().breakApart();
  sheet.clear({ contentsOnly: false });
  sheet.clearConditionalFormatRules();
  sheet.getCharts().forEach(chart => sheet.removeChart(chart));
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
  if (options.percentageColumn && values.length > headerRow) {
    const range = sheet.getRange(headerRow + 1, options.percentageColumn, values.length - headerRow, 1);
    const raw = range.getValues();
    range.setValues(raw.map(row => [typeof row[0] === 'number' ? row[0] / 100 : row[0]])).setNumberFormat('0.0%');
  }
  sheet.getRange(headerRow, 1, values.length - headerRow + 1, values[0].length).createFilter();
}
