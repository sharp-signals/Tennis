/**
 * CHANGE-2026-09-06-023
 * Publica apenas métricas agregadas da Sheet PAPER 22Bet no repositório.
 * Não publica a lista de apostas, notas ou dados pessoais.
 *
 * Antes de usar, definir nas Propriedades do script:
 * - GITHUB_TOKEN: fine-grained token com Contents: Read and write no Tennis
 * - GITHUB_REPOSITORY: sharp-signals/Tennis
 * - GOOGLE_SHEETS_SPREADSHEET_ID: ID da Sheet PAPER 22Bet (opcional;
 *   usa a Sheet oficial por omissão, para suportar projeto Apps Script autónomo)
 * Opcional: GITHUB_BRANCH (por omissão, main)
 */

const PAPER_22BET_SYNC = {
  sheetName: 'Apostas',
  headerRow: 5,
  firstColumn: 1,
  columnCount: 15,
  targetPath: 'data/manual_paper_22bet.json',
  defaultRepository: 'sharp-signals/Tennis',
  defaultBranch: 'main',
  defaultSpreadsheetId: '1WY4D0yYxBUX5kOQHMoFnEHmDT1oXsGszyFoMUcXQ-8U',
  validationPath: 'data/validation/green-strong-v1.json',
  trackingHeaders: [
    'Fenzobot Snapshot Key', 'Selection Strategy', 'Selected At UTC',
    '22Bet Moneyline Review Odd', '22Bet Handicap Games Line', 'Validation Status',
  ],
  challengerTrackingHeaders: [
    'Challenger Índice Fenzobot', 'Challenger Cobertura %', 'Challenger Edge %',
  ],
  challengerManualStrategy: 'CHALLENGER_125_EXPERIMENTAL_V1',
  challengerManualStakeUnits: 0.5,
  // Índices legacy (A:O) usados exclusivamente como compatibilidade para
  // versões antigas da Sheet sem cabeçalhos reconhecíveis.
  legacyOperationalIndexes: {
    market: 5, side: 7, odd: 9, stake: 10, result: 12, profit: 13,
  },
};

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Fenzobot')
    .addItem('Sincronizar métricas PAPER 22Bet', 'syncPaperTradingToGitHub')
    .addItem('Instalar colunas GREEN_STRONG_V1', 'installGreenStrongTrackingColumns')
    .addItem('Instalar colunas Challenger 125 · 0,5u', 'installChallenger125TrackingColumns')
    .addItem('Ativar sincronização automática', 'installPaperTradingSync')
    .addToUi();
}

function syncPaperTradingToGitHub() {
  const properties = PropertiesService.getScriptProperties();
  const token = properties.getProperty('GITHUB_TOKEN');
  if (!token) throw new Error('Falta GITHUB_TOKEN nas Propriedades do script.');

  const repository = properties.getProperty('GITHUB_REPOSITORY') || PAPER_22BET_SYNC.defaultRepository;
  const branch = properties.getProperty('GITHUB_BRANCH') || PAPER_22BET_SYNC.defaultBranch;
  const payload = buildPaperTradingPayload_(token, repository, branch);
  const apiUrl = 'https://api.github.com/repos/' + repository + '/contents/' + PAPER_22BET_SYNC.targetPath;
  const headers = {
    Authorization: 'Bearer ' + token,
    Accept: 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
  };

  const existingResponse = UrlFetchApp.fetch(apiUrl + '?ref=' + encodeURIComponent(branch), {
    method: 'get', headers: headers, muteHttpExceptions: true,
  });
  let sha = null;
  if (existingResponse.getResponseCode() === 200) {
    const existing = JSON.parse(existingResponse.getContentText());
    sha = existing.sha;
    const decoded = Utilities.newBlob(
      Utilities.base64Decode(String(existing.content || '').replace(/\s/g, '')),
    ).getDataAsString();
    try {
      const previous = JSON.parse(decoded);
      if (previous.data_fingerprint === payload.data_fingerprint) {
        return 'Sem alterações no registo PAPER 22Bet.';
      }
    } catch (error) {
      // Um ficheiro antigo/corrompido é substituído pelo resumo atual.
    }
  } else if (existingResponse.getResponseCode() !== 404) {
    throw new Error('GitHub devolveu HTTP ' + existingResponse.getResponseCode() + ': ' + existingResponse.getContentText());
  }

  const body = {
    message: 'chore: sincronizar métricas PAPER 22Bet [skip ci]',
    content: Utilities.base64Encode(
      JSON.stringify(payload, null, 2),
      Utilities.Charset.UTF_8,
    ),
    branch: branch,
  };
  if (sha) body.sha = sha;
  const writeResponse = UrlFetchApp.fetch(apiUrl, {
    method: 'put', headers: headers, contentType: 'application/json',
    payload: JSON.stringify(body), muteHttpExceptions: true,
  });
  if (writeResponse.getResponseCode() < 200 || writeResponse.getResponseCode() >= 300) {
    throw new Error('Não foi possível publicar o resumo: HTTP ' + writeResponse.getResponseCode() + ': ' + writeResponse.getContentText());
  }
  return 'Métricas PAPER 22Bet sincronizadas com sucesso.';
}

function installGreenStrongTrackingColumns() {
  const sheet = paperTradingSpreadsheet_().getSheetByName(PAPER_22BET_SYNC.sheetName);
  if (!sheet) throw new Error('Não encontrei o separador "' + PAPER_22BET_SYNC.sheetName + '".');
  const width = Math.max(PAPER_22BET_SYNC.columnCount, sheet.getLastColumn());
  const headers = sheet.getRange(PAPER_22BET_SYNC.headerRow, PAPER_22BET_SYNC.firstColumn, 1, width).getValues()[0];
  let next = headers.length;
  missingTrackingHeaders_(headers).forEach(header => {
    if (headers.indexOf(header) === -1) {
      sheet.getRange(PAPER_22BET_SYNC.headerRow, PAPER_22BET_SYNC.firstColumn + next).setValue(header);
      headers.push(header);
      next += 1;
    }
  });
  return 'Colunas GREEN_STRONG_V1 instaladas sem alterar as 15 colunas existentes.';
}

function missingTrackingHeaders_(headers) {
  return PAPER_22BET_SYNC.trackingHeaders.filter(header => headers.indexOf(header) === -1);
}

function installChallenger125TrackingColumns() {
  const sheet = paperTradingSpreadsheet_().getSheetByName(PAPER_22BET_SYNC.sheetName);
  if (!sheet) throw new Error('Não encontrei o separador "' + PAPER_22BET_SYNC.sheetName + '".');
  const width = Math.max(PAPER_22BET_SYNC.columnCount, sheet.getLastColumn());
  const headers = sheet.getRange(PAPER_22BET_SYNC.headerRow, PAPER_22BET_SYNC.firstColumn, 1, width).getValues()[0];
  let next = headers.length;
  PAPER_22BET_SYNC.challengerTrackingHeaders.forEach(header => {
    if (headers.indexOf(header) === -1) {
      sheet.getRange(PAPER_22BET_SYNC.headerRow, PAPER_22BET_SYNC.firstColumn + next).setValue(header);
      headers.push(header);
      next += 1;
    }
  });
  return 'Colunas Challenger 125 instaladas. São opcionais e não alteram linhas PAPER existentes.';
}

function onEdit(e) {
  if (!e || !e.range || e.range.getSheet().getName() !== PAPER_22BET_SYNC.sheetName) return;
  if (e.range.getRow() <= PAPER_22BET_SYNC.headerRow || !e.value) return;
  const sheet = e.range.getSheet();
  const map = trackingColumnMap_(sheet);
  if (map['Fenzobot Snapshot Key'] !== e.range.getColumn()) return;
  const stampColumn = map['Selected At UTC'];
  if (!stampColumn) return;
  const stampCell = sheet.getRange(e.range.getRow(), stampColumn);
  if (!stampCell.getValue()) stampCell.setValue(new Date().toISOString());
}

function installPaperTradingSync() {
  ScriptApp.getProjectTriggers()
    .filter(trigger => trigger.getHandlerFunction() === 'syncPaperTradingToGitHub')
    .forEach(trigger => ScriptApp.deleteTrigger(trigger));
  ScriptApp.newTrigger('syncPaperTradingToGitHub').timeBased().everyMinutes(30).create();
  return 'Sincronização automática ativada: verifica a Sheet a cada 30 minutos e só publica se houver alterações.';
}

function buildPaperTradingPayload_(token, repository, branch) {
  const spreadsheet = paperTradingSpreadsheet_();
  const sheet = spreadsheet.getSheetByName(PAPER_22BET_SYNC.sheetName);
  if (!sheet) throw new Error('Não encontrei o separador "' + PAPER_22BET_SYNC.sheetName + '".');
  const lastRow = sheet.getLastRow();
  const rowCount = Math.max(0, lastRow - PAPER_22BET_SYNC.headerRow);
  const width = Math.max(PAPER_22BET_SYNC.columnCount, sheet.getLastColumn());
  const headers = sheet.getRange(PAPER_22BET_SYNC.headerRow, PAPER_22BET_SYNC.firstColumn, 1, width).getValues()[0];
  const tracking = trackingIndexes_(headers);
  const rows = rowCount ? sheet.getRange(PAPER_22BET_SYNC.headerRow + 1, PAPER_22BET_SYNC.firstColumn, rowCount, width).getValues() : [];
  const activeRows = rows.filter(row => row[0] && row[1] && row[tracking.market]);
  // O agregado principal mantém-se exclusivamente PAPER normal. O Challenger
  // 125 manual tem universo e stake próprios, publicados abaixo por estratégia.
  const standardRows = activeRows.filter(row => !isChallengerManualRow_(row, tracking));
  const summary = newStats_();
  const byMarket = {};
  const bySide = {};
  standardRows.forEach(row => {
    const market = marketName_(row, tracking);
    const side = sideName_(row, tracking);
    if (!byMarket[market]) byMarket[market] = newStats_();
    if (!bySide[side]) bySide[side] = newStats_();
    addRowToStats_(summary, row, tracking);
    addRowToStats_(byMarket[market], row, tracking);
    addRowToStats_(bySide[side], row, tracking);
  });

  const green = tracking.complete ? fetchGreenStrongIndex_(token, repository, branch) : {byKey: {}, eligibleCount: null, available: false};
  const guerraStats = newStats_();
  const guerraByMarket = {};
  const guerraBySide = {};
  const guerraReviewRoutes = {};
  const flatStakeSimulation = newFlatStakeSimulation_();
  const selectedSnapshotKeys = {};
  const underdogPairs = {};
  const linkage = {LINKED_EX_ANTE: 0, SNAPSHOT_NOT_FOUND: 0, NOT_GREEN_STRONG: 0, SELECTION_AFTER_START: 0, MISSING_SELECTION_TIMESTAMP: 0, UNAVAILABLE: 0};
  const challengerStats = newStats_();
  const challengerByMarket = {};
  const challengerBySide = {};
  const challengerByIndexBand = {};
  const challengerByCoverageBand = {};
  const challengerByEdgeBand = {};
  const challengerValidation = {MANUAL_CHALLENGER_RECORDED: 0, MISSING_SNAPSHOT_KEY: 0, MISSING_SELECTION_TIMESTAMP: 0, INVALID_CHALLENGER_STAKE: 0};
  rows.forEach((row, offset) => {
    if (isChallengerManualRow_(row, tracking)) {
      const challengerStatus = validateManualChallengerSelection_(row, tracking);
      challengerValidation[challengerStatus] = (challengerValidation[challengerStatus] || 0) + 1;
      if (tracking.status >= 0) sheet.getRange(PAPER_22BET_SYNC.headerRow + 1 + offset, tracking.status + 1).setValue(challengerStatus);
      if (challengerStatus !== 'MANUAL_CHALLENGER_RECORDED') return;
      const market = marketName_(row, tracking);
      const side = sideName_(row, tracking);
      const indexBand = challengerIndexBand_(row, tracking);
      const coverageBand = challengerCoverageBand_(row, tracking);
      const edgeBand = challengerEdgeBand_(row, tracking);
      [[challengerByMarket, market], [challengerBySide, side], [challengerByIndexBand, indexBand], [challengerByCoverageBand, coverageBand], [challengerByEdgeBand, edgeBand]].forEach(pair => {
        if (!pair[0][pair[1]]) pair[0][pair[1]] = newStats_();
      });
      addRowToStats_(challengerStats, row, tracking);
      addRowToStats_(challengerByMarket[market], row, tracking);
      addRowToStats_(challengerBySide[side], row, tracking);
      addRowToStats_(challengerByIndexBand[indexBand], row, tracking);
      addRowToStats_(challengerByCoverageBand[coverageBand], row, tracking);
      addRowToStats_(challengerByEdgeBand[edgeBand], row, tracking);
      return;
    }
    if (!(row[0] && row[1] && row[tracking.market]) || !tracking.complete || String(row[tracking.strategy] || '').trim() !== 'GUERRA_SELECTION_V1') return;
    const status = validateGuerraSelection_(row, tracking, green.byKey, green.available);
    linkage[status] = (linkage[status] || 0) + 1;
    sheet.getRange(PAPER_22BET_SYNC.headerRow + 1 + offset, tracking.status + 1).setValue(status);
    if (status !== 'LINKED_EX_ANTE') return;
    const snapshotKey = String(row[tracking.snapshot]).trim();
    const cohort = green.byKey[snapshotKey] || {};
    selectedSnapshotKeys[snapshotKey] = true;
    const market = marketName_(row, tracking);
    const side = sideName_(row, tracking);
    const route = moneylineReviewRoute_(row[tracking.reviewOdd]);
    if (!guerraByMarket[market]) guerraByMarket[market] = newStats_();
    if (!guerraBySide[side]) guerraBySide[side] = newStats_();
    addRowToStats_(guerraStats, row, tracking);
    addRowToFlatStakeSimulation_(flatStakeSimulation, row, tracking);
    addRowToStats_(guerraByMarket[market], row, tracking);
    addRowToStats_(guerraBySide[side], row, tracking);
    guerraReviewRoutes[route] = (guerraReviewRoutes[route] || 0) + 1;
    if (cohort.selected_side_market_position === 'UNDERDOG') {
      if (!underdogPairs[snapshotKey]) underdogPairs[snapshotKey] = {moneyline: false, positiveHandicap: false};
      const leg = manualLegType_(row, tracking);
      if (leg === 'MONEYLINE') underdogPairs[snapshotKey].moneyline = true;
      if (leg === 'POSITIVE_HANDICAP_GAMES') underdogPairs[snapshotKey].positiveHandicap = true;
    }
  });

  const pairValues = Object.keys(underdogPairs).map(key => underdogPairs[key]);
  const pairCompleteness = {
    underdog_selected_candidates: pairValues.length,
    complete_moneyline_positive_handicap_pairs: pairValues.filter(pair => pair.moneyline && pair.positiveHandicap).length,
    moneyline_only: pairValues.filter(pair => pair.moneyline && !pair.positiveHandicap).length,
    positive_handicap_only: pairValues.filter(pair => !pair.moneyline && pair.positiveHandicap).length,
    incomplete_or_unrecognized: pairValues.filter(pair => !pair.moneyline && !pair.positiveHandicap).length,
  };
  const selectedCandidates = Object.keys(selectedSnapshotKeys).length;
  const strategyAggregate = {
    summary: finishStats_(guerraStats),
    paper_entries: guerraStats.total_entries,
    selected_candidates: selectedCandidates,
    by_market: finishCollection_(guerraByMarket),
    by_side: finishCollection_(guerraBySide),
    moneyline_review_routes: guerraReviewRoutes,
    underdog_pair_completeness: pairCompleteness,
    linkage: linkage,
    eligible_green_strong: green.eligibleCount,
    selection_rate_pct: green.eligibleCount ? Math.round(10000 * selectedCandidates / green.eligibleCount) / 100 : null,
    status: tracking.complete && green.available ? 'AVAILABLE' : 'UNAVAILABLE',
    flat_stake_simulation: finishFlatStakeSimulation_(
      flatStakeSimulation,
      tracking.complete && green.available,
    ),
  };
  const challengerAggregate = {
    summary: finishStats_(challengerStats),
    paper_entries: challengerStats.total_entries,
    fixed_stake_units: PAPER_22BET_SYNC.challengerManualStakeUnits,
    by_market: finishCollection_(challengerByMarket),
    by_side: finishCollection_(challengerBySide),
    by_fenzobot_index_band: finishCollection_(challengerByIndexBand),
    by_coverage_band: finishCollection_(challengerByCoverageBand),
    by_edge_band: finishCollection_(challengerByEdgeBand),
    validation: challengerValidation,
    status: challengerStats.total_entries ? 'AVAILABLE' : 'UNAVAILABLE',
  };
  const fingerprintRows = tracking.complete ? activeRows.map(row => row.filter((value, index) => index !== tracking.status)) : activeRows;
  const fingerprint = Utilities.computeDigest(
    Utilities.DigestAlgorithm.SHA_256,
    semanticFingerprintMaterial_(fingerprintRows, {
      summary: finishStats_(summary), by_market: finishCollection_(byMarket),
      by_side: finishCollection_(bySide), by_strategy: strategyAggregate,
      challenger_manual: challengerAggregate,
    }),
  ).map(byte => ('0' + (byte & 0xff).toString(16)).slice(-2)).join('');
  return {
    schema_version: 2,
    source: {
      label: 'Track Record PAPER Trading — 22Bet',
      url: spreadsheet.getUrl(),
      reference_bookmaker: '22Bet',
      synced_at_utc: new Date().toISOString(),
    },
    data_fingerprint: fingerprint,
    summary: finishStats_(summary),
    by_market: finishCollection_(byMarket),
    by_side: finishCollection_(bySide),
    by_strategy: {
      GUERRA_SELECTION_V1: strategyAggregate,
      CHALLENGER_125_EXPERIMENTAL_V1: challengerAggregate,
    },
  };
}

/**
 * Resolve a Sheet sem depender de um Apps Script associado ao ficheiro.
 * Isto permite criar o projeto diretamente em script.google.com quando o
 * projeto bound original deixou de estar acessível.
 */
function paperTradingSpreadsheet_() {
  const properties = typeof PropertiesService !== 'undefined'
    ? PropertiesService.getScriptProperties()
    : null;
  const configuredId = properties
    ? properties.getProperty('GOOGLE_SHEETS_SPREADSHEET_ID')
    : null;
  const spreadsheetId = configuredId || PAPER_22BET_SYNC.defaultSpreadsheetId;
  if (!spreadsheetId) {
    throw new Error('Falta GOOGLE_SHEETS_SPREADSHEET_ID nas Propriedades do script.');
  }
  let spreadsheet = null;
  if (typeof SpreadsheetApp.openById === 'function') {
    spreadsheet = SpreadsheetApp.openById(spreadsheetId);
    if (spreadsheet) return spreadsheet;
  }
  // Em alguns projetos autónomos a abertura por ID pode devolver nulo apesar
  // de a conta ter acesso; repetir pela URL canónica da mesma Sheet.
  if (typeof SpreadsheetApp.openByUrl === 'function') {
    spreadsheet = SpreadsheetApp.openByUrl(
      'https://docs.google.com/spreadsheets/d/' + spreadsheetId + '/edit',
    );
    if (spreadsheet) return spreadsheet;
  }
  // Compatibilidade com execução bound e com o simulador Node dos testes.
  if (typeof SpreadsheetApp.getActiveSpreadsheet === 'function') {
    const active = SpreadsheetApp.getActiveSpreadsheet();
    if (active) return active;
  }
  throw new Error('Não foi possível abrir a Sheet PAPER 22Bet. Confirme o ID e o acesso da conta fenzobot@gmail.com.');
}

function trackingIndexes_(headers) {
  const indexes = {};
  PAPER_22BET_SYNC.trackingHeaders.forEach(header => indexes[header] = headers.indexOf(header));
  return {
    snapshot: indexes['Fenzobot Snapshot Key'], strategy: indexes['Selection Strategy'],
    selectedAt: indexes['Selected At UTC'], reviewOdd: indexes['22Bet Moneyline Review Odd'],
    handicapLine: indexes['22Bet Handicap Games Line'],
    status: indexes['Validation Status'],
    challengerIndex: headers.indexOf('Challenger Índice Fenzobot'),
    challengerCoverage: headers.indexOf('Challenger Cobertura %'),
    challengerEdge: headers.indexOf('Challenger Edge %'),
    market: operationalIndex_(headers, 'Tipo de mercado', 'market'),
    side: operationalIndex_(headers, 'Fav/Und', 'side'),
    odd: operationalIndex_(headers, 'Odd aposta', 'odd'),
    stake: operationalIndex_(headers, 'Stake (u)', 'stake'),
    result: operationalIndex_(headers, 'Resultado', 'result'),
    profit: operationalIndex_(headers, 'Lucro (u)', 'profit'),
    complete: PAPER_22BET_SYNC.trackingHeaders.every(header => indexes[header] >= 0),
  };
}

function operationalIndex_(headers, header, legacyKey) {
  const index = headers.indexOf(header);
  return index >= 0 ? index : PAPER_22BET_SYNC.legacyOperationalIndexes[legacyKey];
}

function marketName_(row, tracking) {
  const market = row[tracking.market];
  return market === 'Vencedor' ? 'Moneyline' : String(market);
}

function sideName_(row, tracking) {
  return String(row[tracking.side] || 'Sem perfil');
}

function isChallengerManualRow_(row, tracking) {
  return tracking.strategy >= 0 && String(row[tracking.strategy] || '').trim() === PAPER_22BET_SYNC.challengerManualStrategy;
}

function validateManualChallengerSelection_(row, tracking) {
  if (!String(row[tracking.snapshot] || '').trim()) return 'MISSING_SNAPSHOT_KEY';
  const selectedAt = new Date(row[tracking.selectedAt]);
  if (!row[tracking.selectedAt] || Number.isNaN(selectedAt.getTime())) return 'MISSING_SELECTION_TIMESTAMP';
  return Number(row[tracking.stake]) === PAPER_22BET_SYNC.challengerManualStakeUnits
    ? 'MANUAL_CHALLENGER_RECORDED'
    : 'INVALID_CHALLENGER_STAKE';
}

function challengerIndexBand_(row, tracking) {
  const index = Number(row[tracking.challengerIndex]);
  if (!Number.isFinite(index)) return 'N/D';
  if (index >= 90) return '90–100';
  if (index >= 80) return '80–89';
  if (index >= 70) return '70–79';
  return '<70';
}

function challengerCoverageBand_(row, tracking) {
  const raw = Number(row[tracking.challengerCoverage]);
  const coverage = raw > 1 ? raw / 100 : raw;
  if (!Number.isFinite(coverage)) return 'N/D';
  if (coverage >= 0.65) return '65%+';
  if (coverage >= 0.50) return '50–64,9%';
  return '<50%';
}

function challengerEdgeBand_(row, tracking) {
  const edge = Number(row[tracking.challengerEdge]);
  if (!Number.isFinite(edge)) return 'N/D';
  if (edge >= 5) return '5%+';
  if (edge >= 4) return '4–4,9%';
  if (edge >= 3) return '3–3,9%';
  return '<3%';
}

function manualLegType_(row, tracking) {
  const market = String(marketName_(row, tracking) || '').trim().toLowerCase();
  const odd = Number(row[tracking.odd]);
  if (!Number.isFinite(odd) || odd <= 1) return 'UNAVAILABLE';
  if (market === 'moneyline') return 'MONEYLINE';
  const line = Number(row[tracking.handicapLine]);
  if (market.indexOf('handicap') >= 0 && market.indexOf('game') >= 0 && Number.isFinite(line) && line > 0) {
    return 'POSITIVE_HANDICAP_GAMES';
  }
  return 'UNAVAILABLE';
}

function semanticFingerprintMaterial_(rowsWithoutValidationStatus, publicAggregates) {
  return JSON.stringify({sheet_rows: rowsWithoutValidationStatus, aggregates: publicAggregates});
}

function trackingColumnMap_(sheet) {
  const width = Math.max(PAPER_22BET_SYNC.columnCount, sheet.getLastColumn());
  const headers = sheet.getRange(PAPER_22BET_SYNC.headerRow, 1, 1, width).getValues()[0];
  const result = {};
  headers.forEach((header, index) => result[String(header)] = index + 1);
  return result;
}

function validateGuerraSelection_(row, tracking, byKey, indexAvailable) {
  if (!tracking.complete) return 'UNAVAILABLE';
  if (indexAvailable === false) return 'UNAVAILABLE';
  const key = String(row[tracking.snapshot] || '').trim();
  if (!key || !Object.prototype.hasOwnProperty.call(byKey, key)) return 'SNAPSHOT_NOT_FOUND';
  const cohort = byKey[key];
  if (!cohort.eligible) return 'NOT_GREEN_STRONG';
  const selectedAt = new Date(row[tracking.selectedAt]);
  if (!row[tracking.selectedAt] || Number.isNaN(selectedAt.getTime())) return 'MISSING_SELECTION_TIMESTAMP';
  const start = new Date(cohort.commence_time_utc);
  if (Number.isNaN(start.getTime())) return 'UNAVAILABLE';
  return selectedAt.getTime() < start.getTime() ? 'LINKED_EX_ANTE' : 'SELECTION_AFTER_START';
}

function moneylineReviewRoute_(rawOdd) {
  const odd = Number(rawOdd);
  if (!Number.isFinite(odd) || odd <= 1) return 'UNAVAILABLE';
  return odd >= 1.75 ? 'MONEYLINE_MANUAL_REVIEW' : 'HANDICAP_MANUAL_REVIEW';
}

function fetchGreenStrongIndex_(token, repository, branch) {
  if (!token || !repository) return {byKey: {}, eligibleCount: null, available: false};
  const url = 'https://api.github.com/repos/' + repository + '/contents/' + PAPER_22BET_SYNC.validationPath + '?ref=' + encodeURIComponent(branch);
  const response = UrlFetchApp.fetch(url, {method: 'get', headers: {Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json'}, muteHttpExceptions: true});
  if (response.getResponseCode() !== 200) return {byKey: {}, eligibleCount: null, available: false};
  try {
    const body = JSON.parse(response.getContentText());
    const document = JSON.parse(
      Utilities.newBlob(
        Utilities.base64Decode(String(body.content || '').replace(/\s/g, '')),
      ).getDataAsString(),
    );
    const rows = document.prospective_classifications || [];
    const byKey = {};
    rows.forEach(row => { if (row.snapshot_key) byKey[String(row.snapshot_key)] = row; });
    return {byKey: byKey, eligibleCount: rows.filter(row => row.eligible === true).length, available: true};
  } catch (error) {
    return {byKey: {}, eligibleCount: null, available: false};
  }
}

function newStats_() {
  return {total_entries: 0, settled: 0, pending: 0, wins: 0, losses: 0, pushes: 0, units: 0, stake: 0, odds: []};
}

function addRowToStats_(stats, row, tracking) {
  const indexes = tracking || PAPER_22BET_SYNC.legacyOperationalIndexes;
  stats.total_entries += 1;
  const result = String(row[indexes.result] || '').trim().toUpperCase();
  const odd = Number(row[indexes.odd]);
  const stake = Number(row[indexes.stake]);
  const profit = Number(row[indexes.profit]);
  if (Number.isFinite(odd)) stats.odds.push(odd);
  if (result === 'GANHOU' || result === 'PERDEU') {
    stats.settled += 1;
    stats.wins += result === 'GANHOU' ? 1 : 0;
    stats.losses += result === 'PERDEU' ? 1 : 0;
    if (Number.isFinite(stake)) stats.stake += stake;
    if (Number.isFinite(profit)) stats.units += profit;
  } else if (result === 'VOID') {
    stats.pushes += 1;
    if (Number.isFinite(profit)) stats.units += profit;
  } else {
    stats.pending += 1;
  }
}

function finishStats_(stats) {
  const round = value => Math.round(value * 1000) / 1000;
  return {
    total_entries: stats.total_entries,
    settled: stats.settled,
    pending: stats.pending,
    wins: stats.wins,
    losses: stats.losses,
    pushes: stats.pushes,
    win_rate_pct: stats.settled ? round(100 * stats.wins / stats.settled) : null,
    units: round(stats.units),
    roi_pct: stats.stake ? round(100 * stats.units / stats.stake) : null,
    average_odd: stats.odds.length ? round(stats.odds.reduce((total, odd) => total + odd, 0) / stats.odds.length) : null,
  };
}

function finishCollection_(collection) {
  const result = {};
  Object.keys(collection).forEach(key => result[key] = finishStats_(collection[key]));
  return result;
}

function newFlatStakeSimulation_() {
  return {
    includedResolvedEntries: 0,
    pendingEntries: 0,
    voidEntries: 0,
    excludedEntries: 0,
    netProfitEur: 0,
    exclusionReasons: {},
  };
}

function excludeFlatStakeEntry_(simulation, reason) {
  simulation.excludedEntries += 1;
  simulation.exclusionReasons[reason] = (simulation.exclusionReasons[reason] || 0) + 1;
}

function addRowToFlatStakeSimulation_(simulation, row, tracking) {
  const indexes = tracking || PAPER_22BET_SYNC.legacyOperationalIndexes;
  const stake = 10;
  const odd = Number(row[indexes.odd]);
  const result = String(row[indexes.result] || '').trim().toUpperCase();
  if (!Number.isFinite(odd) || odd <= 1) {
    excludeFlatStakeEntry_(simulation, 'INVALID_DECIMAL_ODD');
    return;
  }
  if (result === '' || result === 'PENDENTE' || result === 'PENDING') {
    simulation.pendingEntries += 1;
    return;
  }
  if (result !== 'GANHOU' && result !== 'PERDEU' && result !== 'VOID') {
    excludeFlatStakeEntry_(simulation, 'UNRECOGNIZED_RESULT');
    return;
  }
  simulation.includedResolvedEntries += 1;
  if (result === 'VOID') {
    simulation.voidEntries += 1;
    return;
  }
  simulation.netProfitEur += result === 'GANHOU' ? stake * (odd - 1) : -stake;
}

function finishFlatStakeSimulation_(simulation, sourceAvailable) {
  const round = value => Math.round(value * 100) / 100;
  const validEntries = simulation.includedResolvedEntries + simulation.pendingEntries;
  const observedEntries = validEntries + simulation.excludedEntries;
  const resolvedStake = 10 * simulation.includedResolvedEntries;
  let status = 'AVAILABLE';
  if (!sourceAvailable || observedEntries === 0) status = 'UNAVAILABLE';
  else if (simulation.excludedEntries > 0) status = 'DEGRADED';
  return {
    status: status,
    stake_per_entry_eur: 10.0,
    included_resolved_entries: simulation.includedResolvedEntries,
    pending_entries: simulation.pendingEntries,
    void_entries: simulation.voidEntries,
    excluded_entries: simulation.excludedEntries,
    resolved_stake_eur: resolvedStake,
    pending_exposure_eur: 10 * simulation.pendingEntries,
    net_profit_eur: simulation.includedResolvedEntries ? round(simulation.netProfitEur) : null,
    roi_pct: resolvedStake ? round(100 * simulation.netProfitEur / resolvedStake) : null,
    exclusion_reasons: simulation.exclusionReasons,
  };
}
